# Plan: WA-2 — no alert or reminder missed during the allowed hours

Backlog: `docs/backlog.md` WA-2. Owner answer Q9 (`docs/questions.md:9`, 2026-10-26): during the WA-1 alert window an alert may arrive **at most 15 minutes late**. So **N = 15 min** in every WA-2 criterion.
No design spec: nothing the owner reads in Telegram changes.

## 1. Context and constraints

### What exists now (verified)

- **The trigger.** `.github/workflows/run_alert.yml:3-6` has `schedule: cron "*/10 4-21 * * *"` and `workflow_dispatch: {}` with no inputs. That is 108 slots a day, 04:00-21:50 UTC.
- **Concurrency.** `run_alert.yml:11-13` sets `group: wind-alert-check, cancel-in-progress: false`. GitHub allows one running and one pending run per group. A newer pending run replaces (cancels) an older pending one, so two checks never run at the same time.
- **Checkout.** `run_alert.yml:19` is `actions/checkout@v4` with no `ref`. In checkout v4 (`src/input-helper.ts`), an empty `ref` sets `result.ref = github.context.ref` and `result.commit = github.context.sha`. So a run checks out **the commit that was on `main` when its event was created, not when the run starts**. A pending run that waits behind a run that then commits new state starts from the old state file. This race exists today, and more frequent triggers make it more likely.
- **The state commit.** `run_alert.yml:37-43`: `git add state/`, then a commit only if something changed (`git diff --staged --quiet ||`), then `git push`. Nothing pulls or rebases. If someone else pushed in between, the push is rejected and the step fails.
- **`[skip ci]` in the bot's commits** (`run_alert.yml:42`, `keep_alive.yml:27`) has no bearing on the schedule. GitHub docs ("Skipping workflow runs"): "Skip instructions only apply to the `push` and `pull_request` events." Neither workflow has a `push` trigger.
- **The run itself.** `src/main.py:115-123`: the window gate runs first, and a run outside the window returns 0 without reading or writing state. Reminder timing is on the **observation clock**: `evaluate()` sets `now = latest.timestamp` (`src/core/hysteresis.py:125`). A reminder becomes due when `latest.timestamp - (last_reminder_at or last_alert_at) >= reminder_interval_minutes` (`hysteresis.py:169-179`). `config.yaml:24` sets the interval to 120.
- **Run duration** (API, see below): created-to-updated is 17-26 s for normal runs. On the page I read there is one outlier of 8 m 19 s (#809, run 39796709630, 2026-10-22) and one of 1 m 8 s (#805). I did not establish the cause of the outlier.
- **Repo visibility:** public (`https://github.com/hakaotu/WindAlert`, read 2026-10-26). Standard GitHub-hosted runner minutes are free for public repos, so run frequency costs nothing here.

### What I could and could not establish about the missing runs

Inputs, all read on 2026-10-26:
- (a) `https://api.github.com/repos/hakaotu/WindAlert/actions/workflows/run_alert.yml/runs?per_page=40`. Only the first 9 runs were read, because the response was truncated.
- (b) `https://github.com/hakaotu/WindAlert/actions/workflows/run_alert.yml?query=event%3Aschedule`, page 1: runs #804-#829, 25 runs. 822 scheduled runs in total.
- (c) GitHub docs: "Events that trigger workflows → schedule", "Skipping workflow runs" and "Actions limits".
- (d) Community discussion `https://github.com/orgs/community/discussions/209514`, opened 2026-10-04.

**Established:**
1. **The events are late or missing. Runners are not queueing them.** Every scheduled run in (a) has `created_at == run_started_at` to the second, for example 2026-10-25T13:41:10Z / 13:41:10Z. A run that exists starts at once, so the delay is in GitHub *creating* the schedule event. Two runs prove lateness outright: 2026-10-25T22:05:51Z and 2026-10-24T23:41:40Z. The last cron slot is 21:50Z, so these were created at least 15 min and at least 1 h 51 min after their slot.
2. **The volume** in (b) is 4-7 scheduled runs per UTC day against 108 slots, consistent with WA-2's facts. Examples: 2026-10-25 had 5 (#823-#827); 2026-10-23 had 4 (#812-#815).
3. **The workflow is not disabled.** Runs keep appearing, and repo activity is high (673 commits), so the 60-day inactivity rule (docs (c)) does not apply.
4. **GitHub documents this behaviour and gives no guarantee.** Quoted from (c): "The `schedule` event can be delayed during periods of high loads … High load times include the start of every hour … If the load is sufficiently high enough, some queued jobs may be dropped." There is no SLA.
5. **Other repos see the same pattern now.** In (d), an hourly cron at `51 * * * *` (off the hour) is "intermittent", with "many expected hourly runs … missing". Manual `workflow_dispatch` works there. No GitHub staff answer as of reading.
6. **Manual dispatches start immediately here too.** Runs 40293358573 (08:35:47Z) and 40348483380 (15:21:15Z) were created and started in the same second.

**Not established:**
- Why so many events are dropped on this repo. In particular, I could not tell whether this repo or account is being throttled individually or whether it is platform-wide load. Only GitHub Support can see dropped events; a dropped event leaves no record.
- Whether moving the cron off `:00` would materially help. (d) is off the hour and still loses most runs.

**Consequence for the design.** Nothing that keeps the GitHub `schedule` event as the only source of triggers can promise 15 minutes. `workflow_dispatch` events have so far started instantly, both here (point 6) and in (d).

### What must not break

- WA-1 behaviour (WA-2 AC4): the window gate, the carry-over expiry, and "outside the window nothing is read or written". No Python under `src/` changes.
- The single-reminder and single-`wind_start` guarantees from WA-1, Amendment 1. More frequent runs must not create duplicates.
- Fork users without the new pinger must keep today's behaviour: the cron stays, and `workflow_dispatch` from the UI keeps working without filling in any input.
- `state/wingfoil_alert_state.json` keeps the same shape and the same commit flow.

## 2. Design summary (recommended option)

**An external timer in the owner's Google account (Apps Script, free) calls GitHub's "run workflow" API every 5 minutes, 06:00-21:55 Europe/Helsinki.** The GitHub cron stays as a fallback.

1. **The pinger.** A new file, `tools/apps-script/pinger.gs`, is pasted into a Google Apps Script project. A time-driven trigger (`everyMinutes(5)`; allowed values are 1, 5, 10, 15 and 30) calls `ping()`.
   - `ping()` returns at once outside 06:00-22:00 Helsinki time.
   - Inside that time it sends `POST https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/run_alert.yml/dispatches` with body `{"ref":"main","inputs":{"trigger":"pinger"}}`.
   - It throws on any non-2xx response, so Apps Script records a failed execution and emails the failure.
2. **The token.** A **fine-grained personal access token**:
   - **Repository access:** only the `WindAlert` repo.
   - **Permission:** only **Actions: Read and write**. GitHub's permission table lists `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches` under "Actions", write.
   - **Where it is stored:** in the Apps Script project's Script Properties as `GITHUB_TOKEN`. It is not in the repo, and not in GitHub Secrets (the workflow does not need it).
   - **What a leaked token can do:** start, cancel and re-run workflow runs, and enable or disable workflows, in this one repo. It cannot push code, read secrets or edit workflow files. That needs Contents/Workflows permissions, which the token does not have.
   - **Expiration:** "No expiration" (allowed for personal accounts per GitHub docs). This avoids a silent yearly break. Revoke it at GitHub → Settings → Developer settings if the Google account is compromised.
3. **Workflow changes** (`run_alert.yml`), each needed by a criterion:
   - A `workflow_dispatch` input `trigger` (string, default `manual`) and `run-name: Wind alert check (${{ inputs.trigger || github.event_name }})`. The run history then shows which runs the pinger made, which ones a person clicked, and which ones the cron made. That separation is what lets AC5 ("without manual triggers") be checked from logs.
   - `actions/checkout` gets `ref: main`. With a non-SHA `ref`, checkout sets no commit and fetches the branch head at checkout time. A run that was pending behind another run then reads the state that run just pushed. This closes the stale-state duplicate path above and guards AC3.
   - The cron line and the concurrency block stay unchanged.
4. **No Python changes.** One integration test is added to prove that 5-minute checks send exactly one reminder (AC3).

### Why 5 minutes and not 10 (the N = 15 budget)

Measure T on the observation clock: the first observation time at which the alert or reminder is due. That is how `evaluate()` decides (`hysteresis.py:125, 172-173`). Worst-case delay from T to the message:

| Part | 10-min pinger | 5-min pinger | Source |
|---|---|---|---|
| FMI publishing lag (obs time → available) | ~3 min | ~3 min | WA-1 plan A.1, reviewer measurement from six runs; not re-measured |
| Wait for next check | ≤ 10 min | ≤ 5 min | cadence |
| Dispatch → run start | ~0 s | ~0 s | (a): `created_at == run_started_at` for dispatches |
| Run → Telegram sent | ~25 s (outlier 8 m 19 s) | same | (b) |
| **Total, normal** | **≤ ~13.5 min** | **≤ ~8.5 min** | |
| One missed or failed dispatch | 23.5 min — fails | 13.5 min — holds | |

AC2's gap limit is about checks alone, and the same reasoning applies there. At 10 minutes, one lost dispatch makes a 20-minute gap and AC2 fails. At 5 minutes, one lost dispatch makes a 10-minute gap and two make 15, so AC2 still holds. The cost is up to 192 runs per day (16 h × 12) of about 25 s each: free on a public repo, and 192 of the 20,000 UrlFetch calls a day Apps Script allows a consumer account.

### Overlap and state races (backlog risk)

- **Two checks running at once:** impossible. The existing concurrency group serializes them, and at most one run is pending. When a run is slow (the 8-minute outlier), the next dispatch waits as pending and any later dispatch replaces it. The superseded runs show as `cancelled` and do nothing.
- **A pending run reading old state:** fixed by `ref: main`, see section 2 item 3.
- **The cron fallback and the pinger:** both feed the same concurrency group. A late cron run in the evening hits the window gate and does nothing (WA-1).
- **Push rejected because another workflow pushed between checkout and push.** `keep_alive.yml` pushes once a month, at 06:00Z on the 1st. The consequence: the notification is sent but the state is not saved, so the next run may repeat it. This predates WA-2, and its likelihood is unchanged by this plan, since only the monthly keep-alive can cause it. It is listed for tech debt (section 10), not fixed here.

## 3. Files to create or modify

### `.github/workflows/run_alert.yml` (modify)

- After `name:`, add:
  ```yaml
  run-name: "Wind alert check (${{ inputs.trigger || github.event_name }})"
  ```
- Change `workflow_dispatch: {}` to:
  ```yaml
  workflow_dispatch:
    inputs:
      trigger:
        description: "Who started this run (the external pinger sends 'pinger')"
        type: string
        required: false
        default: manual
  ```
- Change the checkout step to:
  ```yaml
  - uses: actions/checkout@v4
    with:
      ref: main   # branch head at checkout time, not the event's commit: a pending run must see the state the previous run pushed
  ```
- Add a comment above `schedule:`: the GitHub schedule is best-effort and in practice runs a few times a day; the reliable trigger is the external pinger (`docs/hosting-github-actions.md`); the cron stays as a fallback.
- Leave the cron expression, `permissions: contents: write`, the concurrency block and the commit step unchanged.

### `tools/apps-script/pinger.gs` (new; `tools/` does not exist yet)

Plain Apps Script (V8). Contents:
- Constants `WORKFLOW_FILE = 'run_alert.yml'`, `START_HOUR = 6`, `END_HOUR = 22` and `TZ = 'Europe/Helsinki'`. A comment says that `START_HOUR`/`END_HOUR` must cover `schedule.active_hours` in `config.yaml`. It is safe to cover more, because the Python gate decides.
- `function ping()`:
  - `const h = Number(Utilities.formatDate(new Date(), TZ, 'H'))`; return if `h < START_HOUR || h >= END_HOUR`.
  - Read `GITHUB_TOKEN` and `GITHUB_REPO` (`owner/name`) from `PropertiesService.getScriptProperties()`. If either is missing, throw an `Error` naming it.
  - `UrlFetchApp.fetch(url, { method: 'post', contentType: 'application/json', muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' }, payload: JSON.stringify({ ref: 'main', inputs: { trigger: 'pinger' } }) })`.
  - If the status is not 2xx, throw `Error('GitHub dispatch failed: HTTP ' + code + ' ' + body.slice(0, 300))`. Otherwise `console.log('Dispatched (HTTP ' + code + ')')`.
- `function installTrigger()`:
  - Delete any existing project triggers whose handler is `ping`, so running it twice cannot double the rate.
  - Create `ScriptApp.newTrigger('ping').timeBased().everyMinutes(5).create()`.
  - Log `'Trigger installed: ping every 5 min'`.
  - Then call `ping()` once, so the first log shows `Dispatched (HTTP 2xx)` or the error. Outside 06-22 Helsinki it logs `'Outside pinger hours - no dispatch'` instead; `ping()` should log that line before returning.
- `function removeTrigger()`: deletes the `ping` triggers. This is the off switch.
- Header comment: what it does, the two Script Properties, the token scope, and a link to `docs/hosting-github-actions.md`.

### `docs/hosting-github-actions.md` (modify)

- Step 6 (lines 42-44): replace the claim that the workflow runs itself every 10 minutes. The cron is in the file, but GitHub runs it only when it has capacity, which in practice is a few times a day. For alerts on time, set up step 7.
- New **step 7, "Luotettava ajastus (suositeltu)"**, in Finnish like the rest of the file:
  - **7a, token:** the exact fine-grained PAT settings from section 2 item 2, including what *not* to pick (classic token, "All repositories", Contents permission).
  - **7b, Apps Script:** script.google.com → New project → paste `tools/apps-script/pinger.gs` → Project Settings → Script Properties `GITHUB_TOKEN` and `GITHUB_REPO` (`<your-user>/WindAlert`) → run `installTrigger` → accept the authorisation → the log shows `Dispatched (HTTP 2xx)`.
  - **7c, check:** the Actions tab shows a run titled "Wind alert check (pinger)".
  - **Error table:** the HTTP status in the log and what it means (section 10). Also a sentence for forks: any scheduler that can send this one POST works. Give the URL, the headers and the body, so a fork can use cron-job.org or similar instead.
- In "Kaksi sudenkuoppaa", add a third pitfall: forks must stay **public**. At 5-minute checks a private fork would use about 192 billed job-minutes a day (each job rounds up to a minute), which exceeds the free private-repo allowance within days.

### `tests/test_integration_smoke.py` (extend)

- Add `test_reminder_every_5_min_sends_exactly_one`, parametrised over `obs_lag` = `timedelta(0)` and `timedelta(minutes=3)`; details in section 7.

### Not changed

- `src/**`, `config.yaml` / `config.example.yaml`. `schedule.poll_interval_minutes` is parsed (`src/core/config.py:97, 241`) but read nowhere else, so leave it.
- `keep_alive.yml`, `docker/`, `docs/hosting-self-host.md`.

## 4. Data model / API / contract changes

- **`workflow_dispatch` gains an optional input `trigger`.**
  - The Actions UI "Run workflow" button shows it pre-filled with `manual`, so the owner's existing habit still works unchanged.
  - `gh workflow run run_alert.yml` without `-f` also still works.
  - **Ordering constraint:** GitHub rejects a dispatch with an undeclared input (HTTP 422, "Unexpected inputs provided"). The workflow change must therefore be on `main` before the pinger is switched on.
- **Run titles change** from "Wind alert check" to "Wind alert check (schedule|manual|pinger)". Nothing in the repo reads run titles.
- **State file and `main.run` contract:** unchanged.

## 5. Architecture doc impact (`docs/architecture.md`)

1. §7, line 128-129: "**GitHub Actions** (`run_alert.yml`): cron `*/10 4-21 * * *` (UTC) sekä `workflow_dispatch`; molemmat kulkevat `main.run`in ikkunatarkistuksen läpi."
   - Becomes misleading by omission. The primary trigger is now the external pinger, `tools/apps-script/pinger.gs`, which calls `workflow_dispatch` every 5 min at 06-22 Helsinki with `trigger=pinger`. The cron is a best-effort fallback.
   - `run-name` shows the trigger.
   - Checkout uses `ref: main`, so a pending run reads the latest state.
2. "Open questions", lines 138-139: "Kesäaamut 06:00-07:00 paikallista aikaa: cron alkaa 04:00 UTC = 07:00 EEST, joten ikkunan alku ennen sitä ei koskaan tule tarkistetuksi (cron + `config.yaml`)."
   - Becomes false once the pinger is live, because it starts at 06:00 Helsinki year-round.
   - Scribe should remove it, or reword it as "true only for forks without the pinger".
3. §4 tree:
   - `tools/apps-script/pinger.gs` is missing.
   - "91 testiä" becomes false (+2 parametrised cases); scribe writes the count pytest reports.
4. Still true, no edit needed: §1 "Jokainen ajo on erillinen prosessi". The module docstring at `hysteresis.py:12-16` ("best-effort and can be delayed by hours") is still accurate.

## 6. Ordered steps

1. **The workflow change** (section 3).
   *Check (developer, before merge):* `python -c "import yaml; d=yaml.safe_load(open('.github/workflows/run_alert.yml')); print(d['run-name']); print(d[True]['workflow_dispatch']['inputs']['trigger']['default']); print(d['jobs']['check']['steps'][0]['with']['ref'])"` prints the run-name, `manual`, `main`. PyYAML parses the key `on:` as `True`. If `actionlint` is installed, it reports nothing.
2. **The AC3 test** (section 7).
   *Check:* `PYTHONPATH=src python -m pytest tests/test_integration_smoke.py -k every_5_min` passes, and so does the full suite (`PYTHONPATH=src python -m pytest`). Then do two scratch edits, reverting each afterwards and committing neither.
   - **(i)** In the test, pass the initial state to every run instead of the previous run's `after`. The test must fail with more than one sending run. This proves it detects duplicates.
   - **(ii)** Change `reminder_minutes` to `reminder_minutes - 5` at `hysteresis.py:173`. The test must fail, with the send landing one run early. This proves it pins *which* run sends, not only how many.
3. **`tools/apps-script/pinger.gs`.**
   *Check:* `node --check tools/apps-script/pinger.gs` if Node is available (Apps Script V8 is plain JS). The reviewer reads it against section 3. It cannot be run outside Google.
4. **Docs** (`docs/hosting-github-actions.md`).
   *Check:* every Script Property name, function name and input value in the doc matches the code: `GITHUB_TOKEN`, `GITHUB_REPO`, `installTrigger`, `trigger`, `pinger`. Grep for each.
5. **Merge to `main`.** Then the main session runs verification step 1 (section 8). The pinger must not be switched on before this.
6. **Owner manual steps M1, then M2** (section 9), one per message.
7. **Observation day** (section 8, step 3).

## 7. Test plan, criterion by criterion

| AC | How it is checked | Passes when | A failure looks like |
|---|---|---|---|
| 1 (sent within 15 min of becoming due) | Two parts. (a) The new test proves the code sends at the first check whose observation is due, not later. (b) Section 8 step 3 proves checks happen every ≤ 15 min. Together with the section 2 budget (≤ ~8.5 min) this gives AC1. On a windy day: state commit times against due times (section 8 step 4). | (a) green; (b) max gap ≤ 15; (c) every reminder commit is ≤ 120 + 15 min after the previous notification commit | a reminder commit more than 135 min after the previous notification while windy |
| 2 (no gap > 15 min) | Real environment only, section 8 step 3. The scheduler cannot be unit-tested. | max gap ≤ 15.0 min, including window open → first check and last check → window close | e.g. `max_gap=20.0` (a lost dispatch at 10-min cadence would show this), or the first check 06:20 local |
| 3 (exactly one reminder, at the first check at or after 10:33Z) | `tests/test_integration_smoke.py::test_reminder_every_5_min_sends_exactly_one[obs_lag]`. State = production state 2026-10-26: `{"state":"ALERTED","last_alert_at":"2026-10-25T08:59:00+00:00","last_reminder_at":"2026-10-26T08:33:00+00:00"}`. Runs every 5 min from `_utc(2026,10,26,9,55)` to `_utc(2026,10,26,11,30)` inclusive (20 runs) via `_run_at(now, state, speed=7.0, obs_lag=obs_lag)`, each run's `after` fed into the next. Collect the run times whose `mock_post.called` is True. | Exactly one sending run. For `obs_lag=0` it is 10:35Z; for `obs_lag=3min` it is 10:40Z (its observation is 10:37, the first ≥ 10:33). The caption contains "edelleen ajokelpoista". The final state has `last_reminder_at` = that run's observation time. | Zero sends (the carry-over expiry wrongly fired: 10-26 08:33 is after the 10-25 close at ~12:43Z, so it must be kept); two or more sends (the reminder stamp was not saved between runs); the send at 10:35Z with `obs_lag=3min` (due-ness on the run clock instead of the observation clock) |
| 4 (outside the window unchanged) | Existing WA-1 tests in `test_integration_smoke.py` (`test_no_send_after_sunset_margin_2026_10_25`, `test_reminder_not_sent_outside_window`, etc.) stay green, with no Python change. Real environment: pinger runs after the window closes log `Outside alert window (...)`. | suite green; no "Update alert state" commit timestamped after that day's window close | a state commit after close |
| 5 (a full in-window day without manual triggers) | Section 8 step 3 on the first full day after M2. | `manual=0`, `max_gap ≤ 15` | any gap > 15, or the day needed a manual run |

**Note on AC3's wording.** The criterion says "at the first check at or after 10:33Z". With real FMI lag (~3 min), the check at 10:35Z sees an observation from about 10:32, which is not yet due, so the reminder goes at the next check, 10:40Z. That is still 7 min after 10:33, inside N. The test pins both cases explicitly, so this reading is visible and not hidden.

## 8. Verification in the real environment

**Step 1: after merge, main session, no owner involvement.**
```
gh workflow run run_alert.yml --repo hakaotu/WindAlert --ref main -f trigger=verify
sleep 60
gh run list --repo hakaotu/WindAlert --workflow run_alert.yml --limit 3 --json databaseId,displayTitle,event,conclusion,createdAt,startedAt
```
- **Right answer:** the newest run is titled `Wind alert check (verify)`, `event: workflow_dispatch`, `conclusion: success`.
- **Then** `gh run view <id> --repo hakaotu/WindAlert --log | grep -m2 -E "refs/heads/main|fetch"`. The checkout fetch should name `refs/heads/main`, not a 40-character SHA. This expected log text is not verified: it follows from `input-helper.ts` setting no commit, but I have not seen the log line.

**Step 2: after owner step M2.**
- The owner's pasted Apps Script log shows `Dispatched (HTTP 204)` or `(HTTP 200)`. GitHub's docs page currently documents 200 with run details; older behaviour was 204. Both are success.
- Main session: `gh run list ... --limit 5 --json displayTitle,createdAt`. A `Wind alert check (pinger)` run appears within a minute of the owner's run, then one every ~5 min. Check at least three consecutive `createdAt` values, about 5 min apart.

**Step 3: the AC2/AC5 check for a day D, main session.** D is a full UTC day after M2.
```
D=2026-10-28   # example; use the first full day after M2
gh run list --repo hakaotu/WindAlert --workflow run_alert.yml --created "$D" --limit 500 \
  --json databaseId,event,displayTitle,status,conclusion,startedAt > "$SCRATCH/runs-$D.json"
PYTHONPATH=src python - "$SCRATCH/runs-$D.json" "$D" <<'EOF'
import json, sys
from datetime import date, datetime
from core import daylight
runs = json.load(open(sys.argv[1])); d = date.fromisoformat(sys.argv[2])
open_, close = daylight.alert_window(d, 61.5177, 23.7538, (6, 22), True, 120)
ok = [r for r in runs if r["conclusion"] == "success"]
manual = [r for r in ok if r["event"] == "workflow_dispatch" and "(pinger)" not in r["displayTitle"]]
checks = sorted(datetime.fromisoformat(r["startedAt"].replace("Z", "+00:00"))
                for r in ok if r not in manual)
inside = [t for t in checks if open_ <= t < close]
pts = [open_] + inside + [close]
gaps = [(b - a).total_seconds() / 60 for a, b in zip(pts, pts[1:])]
L = daylight.LOCAL_TZ
print(f"window {open_.astimezone(L):%H:%M}-{close.astimezone(L):%H:%M} local, "
      f"checks_in_window={len(inside)}, max_gap={max(gaps):.1f} min, manual={len(manual)}, "
      f"cancelled={sum(r['conclusion']=='cancelled' for r in runs)}")
EOF
```
- **Inputs to record with the result:** D, the `gh` command above, and the coordinates and window settings, which are `config.yaml:10-11, 153-155`.
- **Right answer:** `max_gap` ≤ 15.0 and `manual=0`. With a healthy 5-min pinger, expect `checks_in_window` ≈ window length / 5 (late October: ~7 h → ~84) and `max_gap` ≈ 5-6.
- `--created` is a UTC date. The Tampere window always lies inside one UTC day (latest close 22:00 EEST = 19:00Z), so one UTC day covers it.
- If `gh run list --created` misbehaves, the fallback is `gh api "repos/hakaotu/WindAlert/actions/workflows/run_alert.yml/runs?created=$D&per_page=100" --paginate`, with the same fields in snake_case.
- **The day counts for WA-2 AC5 only if `manual=0`.** The main session records D, the printed line and the time it ran into the task.

**Step 4: AC1/AC3 on the first windy in-window day (main session):**
`git log --since="$D" --until="$D 23:59" --format='%cI %s' -- state/wingfoil_alert_state.json` and `git show <commit>:state/wingfoil_alert_state.json` for each commit.
- **Right answer:** while windy, consecutive `last_reminder_at` values are 120-135 min apart, never two reminders within 120 min, and every commit is ≤ ~3 min after the observation stamp it records plus ≤ 5 min of cadence.
- The run log for each such commit contains exactly one `Sent alert via telegram`.

**What only the owner can see:** whether the Telegram reminders actually arrive on the phone at those times. Ask only if the logs and the phone disagree.

## 9. Setup steps only the owner can do

There are two, each a separate message when it is time; the main session writes them out then. **M2 depends on step 5 (merge) and M1.**

- **M1, GitHub token (a GitHub page he has likely not used before, so it needs the full click-by-click form).**
  - Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
  - Name `WindAlert pinger`; Expiration **No expiration**.
  - Repository access **Only select repositories → WindAlert**.
  - Permissions → Repository permissions → **Actions: Read and write**. Leave everything else at "No access".
  - Generate, and copy the token.
  - **Do not** choose "Tokens (classic)", "All repositories", or Contents/Workflows permissions. **Do not** paste the token into chat or into the repo.
- **M2, Apps Script (a tool he already runs, per the 2026-10-02 calibration note; short form).**
  - New project at script.google.com, paste the file `tools/apps-script/pinger.gs`.
  - Script Properties: add `GITHUB_TOKEN` = the token from M1, and add `GITHUB_REPO` = `hakaotu/WindAlert`.
  - Run `installTrigger` once and accept the authorisation prompt.
  - The log should show `Trigger installed: ping every 5 min` and then `Dispatched (HTTP 204)` (or 200), or `Outside pinger hours - no dispatch` if run after 22:00 Helsinki.
  - **Do not** run `installTrigger` repeatedly to "make sure" (it is idempotent, but there is no need), and **do not** run `removeTrigger`.

**Questions for the owner: none required.**
- Everything above is free (Apps Script consumer quota; public-repo Actions minutes).
- The token expiry default ("No expiration", narrow scope) is a security trade-off the plan takes. Ask only if the owner has a rule against non-expiring keys. The alternative is 366 days and a yearly re-do of M1 and the M2 property.

## 10. Alternatives considered

| Option | Meets 15 min? | Owner effort / operation | Fork-friendly | Verdict |
|---|---|---|---|---|
| **Apps Script timer → `workflow_dispatch`** (recommended) | Yes, with margin at 5 min (section 2 table). Trigger accuracy of `everyMinutes` is not documented by Google; AC5 observes it. | 2 steps, in a tool he knows; nothing to run or patch afterwards. Failures are emailed by Apps Script. | Yes: the file is in the repo; each fork uses its own Google account and token. | **Chosen** |
| cron-job.org (free, donation-funded) → `workflow_dispatch` | Same mechanism; minimum interval 1 min, history and failure emails (cron-job.org front page). | 3 steps in a new tool: account, then a job with URL, method, 4 headers, body, schedule and time zone typed into a web form. The token sits with a third party. | Yes. Documented as the alternative in hosting docs (the raw request is given). | Rejected as primary: more error-prone setup for this owner, nothing in the repo to review. |
| Cloudflare Worker cron trigger (repo already has `telemetry-server/`) | Yes | Needs `wrangler` CLI deploy and a Worker secret: an engineer's task. | Moderate | Rejected: CLI deploy is beyond the owner. |
| Cron offset tweaks (`7-59/10`, several cron lines) | **No guarantee.** The losses are dropped or late *event creation* (section 1, established 1), which docs say can drop jobs at any load peak. (d) loses most runs at `:51`. | trivial | yes | Rejected as a fix. Harmless but not done, to keep the diff to what the criteria need. |
| Long-running workflow that loops (check, sleep 5 min) and re-dispatches itself with `GITHUB_TOKEN` (allowed: "`workflow_dispatch` and `repository_dispatch` events always create workflow runs") | Only if the chain never breaks. Jobs cap at 6 h, so it must hand over 3-4 times a day. Overnight it must either hold a runner idle or rely on the flaky cron to restart in the morning, and the morning start is exactly when it is needed. | none for owner | yes, no external account | Rejected: holds a runner ~16-24 h/day, which GitHub's terms flag ("burden … disproportionate", "serverless application"). A broken chain is silent and recovers only via the unreliable cron. |
| Self-hosted GitHub runner | **No**: events are created late or never; runners are idle when runs exist (`created_at == run_started_at`). | high | no | Rejected: does not address the cause. |
| Self-host the check (Pi / VPS, `docs/hosting-self-host.md`) | Yes (local cron is punctual) | Buy/keep a device on 24/7, OS updates, power/network outages at home, `.env` secrets, log reading via SSH. State moves from the repo to the device. | Already documented | Rejected for this owner (not an engineer). Remains documented for forks. |

## 11. Risks and open questions

- **Apps Script trigger punctuality is not documented** (the `everyMinutes` reference says nothing on accuracy). Mitigated by the 5-min cadence (one miss still meets 15) and caught by AC5's full-day observation. If AC5 fails on trigger gaps, the next fallback is to add cron-job.org as a second pinger. That works without code changes, because concurrency dedupes.
- **`workflow_dispatch` could itself be delayed under load.** It has been instant here and in (d), but GitHub promises nothing. Again caught by AC5. If it fails there, the only fully independent option left is self-hosting, which is the owner's call at that point.
- **The token or setup breaks silently?** No: a non-2xx response throws in `ping()`, and Apps Script emails failed executions. The default notification is a daily digest; the owner can set "immediately" in the trigger settings. Not required.
- **Diagnosing M2 from the log** (for the main session):
  - HTTP 401: the token was mistyped or revoked.
  - HTTP 403 "Resource not accessible by personal access token": Actions permission is not Read and write.
  - HTTP 404: the repo is not selected in the token, or `GITHUB_REPO` is wrong.
  - HTTP 422 "Unexpected inputs": the workflow change is not on `main` yet.
  - HTTP 422 "No ref found": the branch is not `main`.
- **Cancelled runs in history** when a run is slow (pending replaced). Harmless. If GitHub emails the owner about cancelled runs, `cancel-in-progress` stays false; revisit only if it is noisy.
- **The FMI publishing lag (~3 min) is assumed from WA-1's measurement**, which I did not re-measure. If it is much larger on some days, AC1's delay grows by the same amount, and no scheduler can fix that.

### For `docs/tech-debt.md` (from reading code, no observed harm; the main session files these, not pm)

- **The state push is not retried.** `run_alert.yml:43` makes a bare `git push`. If `keep_alive.yml` pushes between checkout and push, the push is rejected and the sent notification is not recorded, so the next run may repeat it. A `git pull --rebase origin main && git push` retry would close this. The two workflows touch different files, so the rebase would not conflict.
- **State is saved even when every channel failed** (`src/main.py:197, 213`). This repeats the WA-1 finding and is still open.

Sources consulted (2026-10-26):
- [GitHub docs: events that trigger workflows](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows)
- [Triggering a workflow (GITHUB_TOKEN exceptions)](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [Skip workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)
- [Actions limits](https://docs.github.com/en/actions/reference/limits)
- [Workflow dispatch REST](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [Fine-grained PAT permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)
- [Managing PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [GitHub additional product terms (Actions)](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features)
- [Community discussion #209514](https://github.com/orgs/community/discussions/209514)
- [actions/checkout input-helper.ts](https://raw.githubusercontent.com/actions/checkout/v4/src/input-helper.ts)
- [Apps Script ClockTriggerBuilder](https://developers.google.com/apps-script/reference/script/clock-trigger-builder)
- [Apps Script quotas](https://developers.google.com/apps-script/guides/services/quotas)
- [cron-job.org](https://cron-job.org/en/)
