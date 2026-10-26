# Plan: WA-1 — alerts only in daylight and inside 6-22 Finnish time

Backlog: `docs/backlog.md` WA-1. No design spec (the recommended defaults below add no user-visible text).

## 1. Context and constraints

### What the code does now (verified)

- **The time gate.** `src/main.py:70-73`:
  ```python
  def is_within_active_hours(cfg: AppConfig) -> bool:
      start, end = cfg.schedule.active_hours_range()
      now_hour = datetime.now().hour
      return start <= now_hour <= end
  ```
  It is called at `src/main.py:104`, before notifiers are built, before any FMI fetch and before state is loaded. If it fails, `run()` returns 0 at line 106 and state is neither read nor written.
- **The main session's claim, checked.** `datetime.now()` with no argument returns the naive wall-clock time in the process's local timezone. `run_alert.yml:28-35` sets no `TZ`, so the job runs in the runner's system timezone. I could not find a line in the repo that says what that timezone is. That GitHub-hosted Ubuntu runners use UTC is GitHub's documented default, not something the repo shows. The logs are consistent with it: a run at 22:05Z got through. In UTC the hour is 22, and `6 <= 22 <= 22` is true. In Helsinki time the hour would be 0 and the run would have been skipped. **Verdict: the claim holds, with one addition.** Because the comparison is inclusive on the end hour (`<= end`), `"6-22"` lets the whole hour 22:00-22:59 through even in local time. AC4 and AC5 need 22:30 to be outside the window, so the end bound has to become exclusive.
- **The schedule.** The cron at `run_alert.yml:5` is `*/10 4-21 * * *` (UTC), so the last scheduled run is 21:50Z. The 22:05Z run on 2026-10-25 was therefore either a 21:50Z run that GitHub started 15 minutes late or a manual `workflow_dispatch`. The repo cannot tell us which. Either way it goes through `main.run`, so the new gate covers manual runs too, matching the backlog assumption.
- **Config.** `ScheduleConfig` (`src/core/config.py:92-99`) has `active_hours: str = "0-23"` and `active_hours_range()`, which only splits on `-` and does no validation. The loader is at `config.py:219-223`. `config.yaml:153` has `active_hours: "6-22"` with the comment "paikallinen aika".
- **A local timezone already exists.** `src/core/chart.py:29` defines `LOCAL_TZ = ZoneInfo("Europe/Helsinki")` with the comment "FMI only covers Finland". `message.py:8` imports it and `main.py:21` imports `message`. So `zoneinfo` and tzdata already have to work at import time on every run, and this plan adds no new dependency on them.
- **Hysteresis state** (`src/core/hysteresis.py:34-38`) has `state`, `last_alert_at` and `last_reminder_at`. The timestamps are ISO strings taken from `latest.timestamp` (`hysteresis.py:135, 154`), which are timezone-aware UTC because FMI times are parsed with `Z -> +00:00` (`fmi_client.py:103`). A reminder (`wind_still`) is due once `reminder_interval_minutes` have passed since `last_reminder_at or last_alert_at` (`hysteresis.py:146-156`). `config.yaml:24` sets the interval to 120.
- **Production state now** (`state/wingfoil_alert_state.json`): `ALERTED`, `last_alert_at 2026-10-25T08:59:00+00:00`, `last_reminder_at 2026-10-26T08:33:00+00:00`. The alert started on the morning of 10-25 and has never been released, so the 2026-10-25 evening messages were most likely `wind_still` reminders. That is inferred from the 120-minute spacing, not read from logs.
- **No sunrise or sunset logic exists anywhere.** I grepped `src/` for `sun`, `daylight` and `zoneinfo`; the only hit is chart.py.
- **Dependencies** (`requirements.txt`): requests, PyYAML, matplotlib. No astronomy library.

### What must not break

- The `wind_start`, `wind_still` and `wind_stop` messages inside the window must be unchanged (AC6, AC8).
- The two existing smoke tests (`tests/test_integration_smoke.py`) use `datetime.now()` and a config with no `schedule:` block. With the defaults chosen below (whole day, daylight gate off) they keep passing at any hour, unchanged.
- State files already on disk (the production one above) must load. No new state fields are added.
- Outside the window, a run must neither read nor write state. The workflow only commits when `state/` changed (`run_alert.yml:41-42`), so night runs keep producing no commits.

## 2. Design summary

1. **A new pure module, `src/core/daylight.py`.** It computes sunrise and sunset locally with the standard sunrise equation (NOAA/Meeus simplified form), using only the stdlib (`math`, `datetime`, `zoneinfo`). From those it builds today's alert window in Europe/Helsinki:
   `[max(sunrise, start:00), min(sunset - margin, end:00))`.
   The window includes its opening instant and excludes its closing instant. That settles the boundary question in the backlog: a run exactly at the opening sends, a run exactly at the closing does not, and a run GitHub starts late falls on whichever side its actual start time is on.
2. **The gate stays where it is**, at the top of `run()`, before fetching or touching state. A run outside the window logs one line and returns 0. Nothing is evaluated, so nothing is suppressed after the fact, and no state can claim a send that did not happen.
3. **An alert carried over from a previous window is closed silently** at the first in-window run. If the state is `ALERTED`, the last notification was before the current window opened, and there was a closed period between the two windows, the state is set to `IDLE` before `evaluate()`. `last_alert_at` is kept, because it records a send that really happened; `last_reminder_at` is cleared. If the wind is still good, `evaluate()` then sends a fresh `wind_start` ("Tuulee ajokelpoisesti"). If it is not, nothing is sent: no late `wind_stop` for wind that died in the dark.
4. **Config:** `schedule.daylight_only` (default `false`) and `schedule.sunset_margin_minutes` (default `0`). The owner's `config.yaml` sets `true` and `120`. `active_hours` becomes Helsinki local time with an exclusive end, the default changes from `"0-23"` to `"0-24"`, and bad values fail at load.

### Hysteresis behaviour across the night (stated explicitly as requested)

| Situation | What happens |
|---|---|
| ALERTED, window closes at 14:43, still windy | Nothing is sent. State stays `ALERTED` on disk overnight. That is accurate: the last real messages were `wind_start` or `wind_still`. |
| Runs after the window closes (14:43 to midnight local, until the cron stops at 21:50Z) | Gate skips them. State is not read or written, and nothing is committed. |
| First in-window run next morning, still windy | The carry-over is cleared to `IDLE`, then `evaluate()` sends a fresh **`wind_start`**, with chart, spots and forecast. It does not send `wind_still`. |
| First in-window run next morning, wind gone | Cleared to `IDLE`. Nothing is sent. The state file changes, and the commit records `IDLE` with yesterday's `last_alert_at` and no reminder. |
| ALERTED during the day, wind drops at 13:00 (inside the window) | `wind_stop` is sent as today. |
| Reminder due while outside the window | Not sent and not recorded, because the run never reaches `evaluate()` (AC7). |

**Why reset rather than keep ALERTED overnight.** If the alert were kept, the first morning run would send "Tuuli on edelleen ajokelpoista" (still windy) to someone who has not been told it is windy today. If the wind had died, it would send "Tuuli laantui" (the wind dropped) about wind that dropped overnight. Neither is the "go now" message the owner asked for. The first is the owner's call, so it is Question 2.

**Why the reset happens in the morning and not at the first run after closing.** Doing it at the first run after closing depends on a run happening after the window closes. GitHub's schedule is best-effort, as the `hysteresis.py:12-16` docstring already notes. Doing it at the first in-window run only depends on the run that would send anyway.

**What "there was a closed period" means.** The previous day's window closed strictly before today's opened (`prev_close < today_open`), or the previous day had no window at all. With the owner's config this is true every day. It is false only for an always-open setup (`"0-24"` with the daylight gate off, or polar day with `"0-24"`), and that keeps today's behaviour for anyone running 24h.

## 3. Files to create or modify

### `src/core/daylight.py` (new)

- `LOCAL_TZ = ZoneInfo("Europe/Helsinki")`, with the same comment as chart.py. Do **not** import it from `chart.py`, because that would pull matplotlib into the gate. Leave chart.py alone.
- `sun_times(day: date, latitude: float, longitude: float) -> tuple[datetime, datetime] | None`
  - Returns `(sunrise_utc, sunset_utc)`, both timezone-aware UTC.
  - **Polar day:** returns `(local midnight of day, local midnight of day + 1)`, converted to UTC, meaning the sun is up all day.
  - **Polar night:** returns `None`.
  - **Algorithm.** Longitude is east-positive, angles are in degrees, and `sin`/`cos` take radians.
    ```
    n       = day.toordinal() - date(2000, 1, 1).toordinal()          # integer day count
    Jstar   = n - longitude / 360
    M       = (357.5291 + 0.98560028 * Jstar) % 360
    C       = 1.9148*sin(M) + 0.0200*sin(2M) + 0.0003*sin(3M)
    lam     = (M + C + 180 + 102.9372) % 360
    Jtransit= 2451545.0 + Jstar + 0.0053*sin(M) - 0.0069*sin(2*lam)
    sin_d   = sin(lam) * sin(23.4397)
    cos_w0  = (sin(-0.833) - sin(lat)*sin_d) / (cos(lat)*cos(d))
    cos_w0 < -1  -> polar day ; cos_w0 > 1 -> polar night
    w0      = degrees(acos(cos_w0))
    Jrise   = Jtransit - w0/360 ; Jset = Jtransit + w0/360
    JD -> datetime: datetime.fromtimestamp((JD - 2440587.5) * 86400, tz=timezone.utc)
    ```
    Sanity check on the longitude sign: Tampere's solar noon should come out near 10:09Z on 2026-10-25, which is the reference value below. If it comes out near 13:20Z, the sign is wrong.
  - **Accuracy.** This form is normally good to about 1 minute at mid-latitudes. At 61.5°N the low sun angle can stretch that to a couple of minutes. The tests allow ±3 minutes against published values, against a 10-minute poll interval. I did not run it, because I have no shell. The developer records the actual differences in the test docstring.
- `alert_window(day: date, latitude, longitude, active_hours: tuple[int, int], daylight_only: bool, sunset_margin_minutes: int) -> tuple[datetime, datetime] | None`
  - `day` is a Helsinki local date. The cap is `[local day 00:00 + start h, local day 00:00 + end h)`, built with `datetime(..., tzinfo=LOCAL_TZ)` and converted to UTC. This makes the DST shift automatic. Hour 24 means the next local midnight.
  - If `daylight_only` is set, intersect with `[sunrise, sunset - margin)`. If `sun_times` returns `None` (polar night), return `None`.
  - Return `None` if the intersection is empty (`open >= close`).
- `current_window(now_utc: datetime, latitude, longitude, active_hours, daylight_only, sunset_margin_minutes) -> tuple[tuple[datetime, datetime] | None, bool]`
  - Uses `day = now_utc.astimezone(LOCAL_TZ).date()`.
  - Returns `(window_for_day, follows_gap)`, where `follows_gap = prev is None or window is None or prev[1] < window[0]` and `prev = alert_window(day - 1 day, ...)`.
  - The caller checks `window and window[0] <= now_utc < window[1]`.

### `src/core/config.py`

- `ScheduleConfig`:
  - Default becomes `active_hours: str = "0-24"`.
  - Add `daylight_only: bool = False` and `sunset_margin_minutes: int = 0`.
  - Docstring/comment: active hours are Europe/Helsinki local time, start inclusive and end exclusive.
- `active_hours_range()`: unchanged signature.
- `load_config` (`config.py:219-223`):
  - Read the two new keys (`bool(...)`, `int(...)`).
  - Validate `active_hours`: it must parse as two ints with `0 <= start < end <= 24`, otherwise raise `ConfigError(f"schedule.active_hours '{value}' ...")`. Also require `sunset_margin_minutes >= 0`.
  - Today `"22-6"` silently never matched (`start <= h <= end` is never true), so making it an error is safe.

### `src/core/hysteresis.py`

- Add `expire_carried_over_alert(state: HysteresisState, window_open: datetime) -> HysteresisState`.
- If `state.state == ALERTED` and the latest of `last_alert_at`/`last_reminder_at` (parsed with `datetime.fromisoformat`, as at line 150) is before `window_open`, or both are `None`, return `HysteresisState(IDLE, state.last_alert_at, None)`. Otherwise return `state` unchanged.
- Keep it pure. The decision about whether there was a gap stays in main.
- Docstring: the persisted state still contains only the transition times; this function does not invent a send.

### `src/main.py`

- Replace `is_within_active_hours` (lines 70-73) with `alert_window_now(cfg, now) -> tuple[bool, window, follows_gap]`, a thin wrapper over `daylight.current_window` using `cfg.location.latitude/longitude` and `cfg.schedule`. Delete the old function; nothing else references it (grep: only `main.py:70, 104`).
- Change the signature to `run(config_path: str, now: datetime | None = None) -> int`, with `now = now or datetime.now(timezone.utc)` right after the config loads. `main()` keeps calling `run(args.config)`. This is how tests control the clock: no monkeypatching of `datetime`.
- Lines 104-106 become the window check. When outside, log `"Outside alert window (%s) - skipping this run."` with the window shown as local `HH:MM-HH:MM`, or `"no window today"`, and return 0. This is log text only and is not user-visible.
- After `state = hysteresis.load_state(...)` (line 138), add: if `follows_gap`, run `state = hysteresis.expire_carried_over_alert(state, window[0])`, and log at INFO when it changed something.
- Nothing else in `run()` changes.

### `config.yaml` and `config.example.yaml`

- `schedule:` block:
  - `active_hours: "6-22"`, with the comment changed to "Suomen aika; 6-22 = klo 06:00-22:00".
  - Add `daylight_only: true`, commented "hälytykset vain auringonnoususta auringonlaskuun miinus marginaali".
  - Add `sunset_margin_minutes: 120`.
- Use the same three keys in `config.example.yaml`.

### Tests (detail in section 7)

- `tests/test_daylight.py` (new)
- `tests/test_config.py` (extend)
- `tests/test_hysteresis.py` (extend)
- `tests/test_integration_smoke.py`: extend. Add a second config template that uses Tampere coordinates and a `schedule:` block, with `reminder_interval_minutes: 120`.

### Not changed

- `chart.py` and the hourly table: dark-hour marking is out of scope.
- `message.py`: no text changes.
- `run_alert.yml`.
- `requirements.txt`.

## 4. Data model / API / contract changes

- **State JSON:** shape unchanged. Old files load as before (`from_json` ignores unknown keys, `hysteresis.py:44-47`). Only `IDLE`/`ALERTED` values are written, and the new function only ever writes values the old code could have written.
- **`config.yaml` schedule keys:**
  - Two new optional keys.
  - `active_hours` meaning changes in two ways: it is now Helsinki local time instead of process local time, and the end is exclusive. Readers: only `ScheduleConfig.active_hours_range` and `main.py`.
  - Anyone with `"0-23"` loses 23:00-23:59. Only the default had that value, and the default becomes `"0-24"`.
- **`main.run` signature:** gains an optional `now`. Callers are `main()` and the tests; both keep working.

## 5. Architecture doc impact

The repo has `ARCHITECTURE.md` at the root, not `docs/architecture.md`. These are the statements this plan makes false or incomplete:

1. §4, the ALERTED → IDLE line becomes false because it is exhaustive. The current text: "**ALERTED → IDLE**: joko tuuli alittaa `min_speed_ms - release_margin_ms`, ylittää `max_speed_ms`, tai suunta ei enää täytä `direction_filter`-ehtoa." The new path: at the first in-window run, when the last notification precedes the window opening after a closed period, the state goes to IDLE silently.
2. §4, the reminder line now needs "only inside the alert window": "**ALERTED-tilan muistutus**: jos `reminder_interval_minutes` > 0 ja tuuli on pysynyt hyvänä sen verran pitkään ilman uutta hälytystä/muistutusta, lähtee `wind_still`-ilmoitus ilman tilan vaihtumista."
3. §2 diagram and §3 tree list the `core/` modules, and `core/daylight.py` is missing from both. The §3 test counts will also become false: "test_hysteresis.py # 13 testiä", "test_config.py # 4 testiä", "test_integration_smoke.py # 2 testiä". `test_daylight.py` will also be missing from the tree.
4. Already false before this plan: §9 "(22 testiä, ks. `tests/`)" and the §3 tree, which omit test_chart/test_message/test_open_meteo/test_spots and the core modules `open_meteo.py` and `spots.py`. Scribe may correct these in passing; this plan does not cause them.

No statement in ARCHITECTURE.md mentions `active_hours` or a time gate (grep), so nothing about the gate becomes false. Scribe adds one sentence describing it.

`docs/hosting-github-actions.md:42-44` says "`config.yaml`in `active_hours` suodattaa lopulliset ajat paikallisajassa". That is false today and becomes true with this change. No edit is needed.

## 6. Ordered steps

1. **Config.** Add the `ScheduleConfig` fields, the new default, loading and validation. Add the config tests.
   *Check:* `PYTHONPATH=src python -m pytest tests/test_config.py` passes, and the four existing tests are unchanged.
2. **`daylight.sun_times`** and its reference tests only.
   *Check:* the three reference dates are within ±3 min and the polar day/night cases behave. **This is the hard part; see the note below.**
3. **`daylight.alert_window` and `current_window`** with the window tests (AC4 and AC5, boundaries, DST, `follows_gap`).
   *Check:* `pytest tests/test_daylight.py` passes, and the dry-run command in section 8 prints the expected 2026-10-25 window.
4. **`hysteresis.expire_carried_over_alert`** with its unit tests.
   *Check:* `pytest tests/test_hysteresis.py` passes: 13 old tests plus the new ones.
5. **`main.py` wiring**: the `now` parameter, the gate swap and the reset call. Add the integration tests.
   *Check:* `pytest tests/test_integration_smoke.py` passes, including the two old tests unchanged.
6. **`config.yaml` / `config.example.yaml`** keys and comments.
   *Check:* `PYTHONPATH=src python -c "from core.config import load_config; print(load_config('config.yaml').schedule)"` shows `daylight_only=True, sunset_margin_minutes=120, active_hours='6-22'`. This needs `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` set to any dummy value.
7. **Full suite:** `PYTHONPATH=src python -m pytest`.

**Step 2 note (the hard part).** A sign or epoch error here moves every window by hours, and nothing at runtime notices; messages would simply arrive at the wrong times. The reference tests are the only defence, so they must use real published values (below) and not values computed by the same code. If the implementation cannot get within ±3 min on all three dates, **stop and report**. Do not widen the tolerance and do not swap in a library; that is a plan change.

## 7. Test plan

**Clock control.** `run(config_path, now=...)` for integration tests. Pure functions take `day`/`now` arguments. FMI observations in the integration tests are built relative to the injected `now` (`now - 20/10/0 min`, 8.5 m/s, 225°). Fetches are patched as in the existing smoke tests (`core.fmi_client.fetch_observations`, `fetch_forecast`, `notifiers.telegram.requests.post`).

**Reference sun times.** Source: `https://api.sunrise-sunset.org/json?lat=61.5177&lng=23.7538&date=<D>&formatted=0`, fetched 2026-10-26, using the standard -0.833° horizon. Coordinates are `config.yaml:10-11`.

| Date | Sunrise (UTC) | Sunset (UTC) | Local (Helsinki) |
|---|---|---|---|
| 2026-10-25 | 05:34:53 | 14:43:14 | 07:35 – 16:43 EET |
| 2026-06-21 | 00:41:17 | 20:12:18 | 03:41 – 23:12 EEST |
| 2026-12-21 | 07:42:35 | 13:03:26 | 09:43 – 15:03 EET |

The backlog's "sunset about 16:35" on 10-25 is about 8 min early against this source. The window therefore closes about 14:43 local, not 14:35. The criteria's outcomes do not change.

Note: in Tampere, sunset minus 2 h is never later than about 21:12 local (midsummer, above), so **the 22:00 cap never binds there**. Only the 06:00 cap binds, on summer mornings. AC5's evening half is tested with a polar-day location, where it does bind.

### Worked example: 2026-10-25 (clocks went back at 01:00Z that day; EET = UTC+2 from then on)

Window for local date 2026-10-25 = `[max(05:34:53Z, 04:00Z), min(14:43:14Z - 2 h, 20:00Z))` = **`[05:34:53Z, 12:43:14Z)`**, which is 07:35-14:43 local.

| Run (UTC) | Local | Local date | Old gate (`main.py:72-73`) | New gate | Blocked by |
|---|---|---|---|---|---|
| 10:00Z | 12:00 | 10-25 | passes (10) | **open → send** (AC6) | — |
| 17:15Z | 19:15 | 10-25 | passes (17) | closed | sunset - 2 h (AC1) |
| 19:45Z | 21:45 | 10-25 | passes (19) | closed | sunset - 2 h (AC1); still inside 6-22 |
| 22:05Z | 00:05 | **10-26** | passes (`22 <= 22`) | closed | before 06:00 and before sunrise (AC1, AC3) |

### Tests, criterion by criterion

| AC | Test (file :: name) | Setup | Passes when | A failure looks like |
|---|---|---|---|---|
| 1 | `test_integration_smoke.py::test_no_send_after_sunset_margin_2026_10_25` (parametrised over 17:15Z, 19:45Z, 22:05Z) | Tampere config, windy obs, state file pre-written as `IDLE` | `mock_post.called is False`; `fetch_observations` not called; state file bytes identical to before | Telegram mock called (the gate is missing or using the wrong timezone), or the state file rewritten |
| 2 | `...::test_no_send_before_sunrise_inside_6_22` | `now = 2026-10-25T05:00Z` (07:00 local, sunrise 07:35) | no post | post called: the daylight gate is ignored and only 6-22 is applied |
| 3 | `...::test_no_send_at_0005_local_winter_and_summer` | `2026-10-25T22:05Z` and `2026-06-21T21:05Z` (00:05 EEST) | no post in either case | the summer case sends: the offset is hard-coded to +2 instead of using the zone |
| 4 | `test_daylight.py::test_active_hours_are_helsinki_time` | `daylight_only=False`, `(6, 22)`. Winter `2026-11-15T04:30Z` in, `20:30Z` out. Summer `2026-07-15T03:30Z` in, `19:30Z` out | in/out as listed | 20:30Z reported inside: UTC hour or an inclusive end |
| 5 | `test_daylight.py::test_six_am_cap_in_summer_tampere` and `::test_22_cap_on_polar_day` | Tampere `2026-06-21T02:30Z` (05:30 EEST) out. Utsjoki (69.9, 27.0) on `2026-06-21`, `daylight_only=True`, margin 120: `18:30Z` (21:30) in, `19:30Z` (22:30) out | as listed | 22:30 inside on polar day: the cap is not applied when there is no sunset |
| 6 | `test_integration_smoke.py::test_sends_inside_window_2026_10_25_noon` | `now = 2026-10-25T10:00Z`, `IDLE` | post called once with `sendPhoto`; state `ALERTED` | no post: the window is computed wrong (sign or epoch error) |
| 7 | `...::test_reminder_not_sent_outside_window` plus control `...::test_reminder_sent_inside_window` | State `ALERTED`, `last_alert_at 2026-10-25T06:59Z`, reminder 120. Runs at 17:15Z and at 10:00Z | 17:15Z: no post, state file unchanged (no `last_reminder_at`). 10:00Z: post called, `last_reminder_at` set | 17:15Z writes `last_reminder_at`: a suppressed send recorded as sent |
| 8 | `...::test_inside_window_weak_wind_sends_nothing` | 10:00Z, 2.0 m/s | no post | any post |

**State across the night** (the extra requirement):

- `test_hysteresis.py::test_carried_over_alert_expires_before_window_open`: ALERTED, last reminder `2026-10-25T12:30Z`, `window_open=2026-10-26T05:37Z`. Expect `IDLE`, `last_alert_at` kept, `last_reminder_at` None.
- `::test_alert_from_current_window_is_kept`: last reminder after `window_open`. Expect it unchanged.
- `::test_idle_state_untouched`.
- `::test_alerted_without_timestamps_expires`.
- `test_integration_smoke.py::test_morning_after_sends_fresh_wind_start`: state ALERTED from 10-25 12:30Z, run `2026-10-26T07:00Z`, windy. Expect a post whose caption starts with "🏄 Tuulee ajokelpoisesti" and not "edelleen". A failure is a `wind_still` caption.
- `...::test_morning_after_no_wind_sends_nothing_and_goes_idle`: state ALERTED, run 10-26 07:00Z, 2.0 m/s. Expect no post and the state file showing `IDLE`. A failure is a "Tuuli laantui" post.

**`daylight.py` unit tests:**

- `test_sun_times_match_reference` for the three dates, ±3 min.
- `test_polar_night_has_no_window`: Utsjoki 2026-12-21, so `alert_window` is None and every run is closed.
- `test_window_open_inclusive_close_exclusive`: `now == open` is in, `now == close` is out.
- `test_dst_switch_day`: 2026-10-25 cap is 04:00Z–20:00Z; 2026-10-24 cap is 03:00Z–19:00Z.
- `test_follows_gap`: true for `(6,22)`; false for `(0,24)` with daylight off.

**`test_config.py`:**

- `test_schedule_defaults`: `"0-24"`, False, 0.
- `test_schedule_keys_parsed`.
- `test_invalid_active_hours_raises`, parametrised over `"22-6"`, `"6-25"` and `"abc"`, matching `ConfigError`.

## 8. Verification in the real environment

1. **Before merge (developer or main session, local):**
   ```
   PYTHONPATH=src python -c "from datetime import date; from core import daylight; w=daylight.alert_window(date(2026,10,25),61.5177,23.7538,(6,22),True,120); print([t.astimezone(daylight.LOCAL_TZ).strftime('%H:%M') for t in w])"
   ```
   The right answer is about `['07:35', '14:43']` (±3 min). Swap the date for today's and compare against `https://api.sunrise-sunset.org/json?lat=61.5177&lng=23.7538&date=<today>&formatted=0`. The second time should be that sunset minus 2 h, shown in Helsinki time.
2. **After merge, from GitHub logs. The main session can do this with no owner involvement**, using `gh run list --workflow run_alert.yml --limit 60` and `gh run view <id> --log`:
   - For a run after today's window closes, the log contains `Outside alert window (HH:MM-HH:MM)` with the times from step 1 for that date, and no `Sent alert via telegram`.
   - For the first in-window run of a windy day, the log contains `Sent alert via telegram`.
   - `git log --since=<deploy date> --format='%cI %s' -- state/wingfoil_alert_state.json`: no "Update alert state" commit is timestamped after the day's window close.
   - The first morning commit after an overnight ALERTED shows `"state": "IDLE"` or a fresh `last_alert_at`.
3. **What only the owner can see:** whether any Telegram message arrived after about 14:40 (late October, falling roughly 2-3 min a day). The logs already answer this, so ask only if the logs and the phone disagree. Optionally, also whether the first message of a windy morning reads as a fresh "Tuulee ajokelpoisesti".

## 9. Alternatives considered

- **The `astral` library.** Accurate, pure Python, but a new dependency installed on every run to replace about 30 lines of well-known formula. Rejected. It is the fallback only if the reference tests cannot be met, and switching to it needs a plan change.
- **Fetching sunrise and sunset** (Open-Meteo `daily=sunrise,sunset`, which the codebase already calls, or sunrise-sunset.org). Rejected. It adds a network failure mode to the gate, which would then either block all alerts or let night alerts through. Local computation cannot fail.
- **Evaluate, then suppress the send outside the window.** Rejected. `evaluate()` writes `last_alert_at`/`last_reminder_at`/`ALERTED` as if it had sent, which is exactly the false state the backlog warns about. It would also need a fetch on every night run.
- **Setting `TZ: Europe/Helsinki` in the workflow.** Rejected. It fixes neither daylight nor the inclusive 22:59 end, and it does nothing for self-hosted or Docker setups.
- **Changing the cron to encode the window.** Rejected. Cron cannot follow sunset or DST.
- **Keeping ALERTED overnight and sending `wind_still` in the morning.** This is Question 2, and the default is rejected for the reasons given in section 2.
- **Sending the existing `wind_stop` ("Tuuli laantui") when the window closes.** Rejected. The text would be false: the wind did not drop.
- **Resetting the state at the first run after the window closes.** Rejected because it depends on that run existing (section 2).
- **Default `daylight_only: true` in code.** Rejected. It would make the existing smoke tests depend on the time of day and change behaviour for any other config. The owner's `config.yaml` turns it on explicitly.

## 10. Risks and open questions

- **Misconfiguration fails open.** If `daylight_only` is mistyped in `config.yaml`, the daylight gate is silently off and only 6-22 applies. The verification log line (the window shown in `Outside alert window (...)`) makes this visible on the first evening.
- **Sun-time error.** See the step 2 note. It is bounded by the reference tests.
- **Late scheduled runs.** A run GitHub starts minutes late near closing time will be skipped. That is correct by the rule but may feel like a lost last alert. Accepted.
- **The morning `wind_start` is a behaviour change**, for the owner to confirm in Question 2.

### Findings for `docs/tech-debt.md` (from reading code, not observed harm; for the main session to file, not for pm)

- **Summer mornings 06:00-07:00 local are never checked.** The cron `*/10 4-21` UTC (`run_alert.yml:5`) starts at 07:00 EEST. This is not covered by any WA-1 criterion; changing the cron to `3-21` would close the gap.
- **State is saved even when every channel failed to send.** `send_alert` ignores the result (`main.py:84-93`) and `save_state` runs regardless (`main.py:187`), so a failed Telegram send is still recorded as sent. This predates WA-1 and is out of scope.

### Questions for the owner (rewrite before asking; both have defaults the plan already implements)

1. **When the alert window closes for the day (2 hours before sunset) and it is still windy, should the bot stay silent, or send a short "no more alerts today" note?**
   Default: stay silent. Reason: no new message is needed, and the criteria say this task adds none. If the owner wants the note, it is new message text, so it needs a designer pass and becomes a separate task.
2. **If it was windy in the evening and is still windy the next morning, should the first morning message be the full "it's windy, go now" alert (with chart and spots), or the shorter "still windy" reminder?**
   Default: the full alert. Reason: the owner has not been told anything that day, and the full alert is the "go now" message they asked for. This uses existing messages only; no text changes.

The backlog's question about manual runs is resolved as assumed: the rule applies to them too, because they go through the same `run()`. No question is needed.

---

## Amendment 1 (2026-10-26) — carry-over threshold, after review of da06542

Sections 1-10 above stay as approved. Where this amendment contradicts them, this amendment wins; the superseded passages are listed in A.6. The owner decisions are unchanged: silent when the window closes, and exactly one full `wind_start` on the first in-window morning run if it is still windy.

### A.1 The defect (reviewer finding, re-verified against the code)

- `evaluate()` stamps every notification with the observation time, not the run time: `now = latest.timestamp` (`src/core/hysteresis.py:122`), written at lines 155 (`wind_start`) and 174 (`wind_still`).
- `expire_carried_over_alert` keeps the state only if `max(notified) >= window_open` (`src/core/hysteresis.py:84`), and `main.run` passes `window[0]` (`src/main.py:157`).
- `follows_gap` is true on **every** in-window run with the owner's config, not just the first (`src/core/daylight.py:110` depends only on the local date), so the check is repeated on every run of the day.
- FMI observations lag the run. The reviewer measured about 3 min from six production state commits against `gh run` start times: run 22:05:51Z → obs 22:03, 19:45:24Z → 19:43, 17:15:24Z → 17:13, 13:41:10Z → 13:38, 08:35:47Z → 08:33, 09:01:20Z → 08:59. Script: `/private/tmp/claude-503/-Users-tuomo-hakaoja-Documents-Coding-WindAlert/d7ed8708-326d-4419-bc70-1584426d9607/scratchpad/lag.py`. I did not rerun it.
- The result: if the first in-window run starts less than the lag after the window opens, its fresh `wind_start` is stamped *before* `window_open`. The next run sees an ALERTED state whose last notification is "before the window", expires it and sends `wind_start` again. Reviewer's reproduction: window opens 05:36:24Z on 2026-10-26, runs at 05:38:20Z, 05:48:20Z and 05:58:20Z, each with obs 3 min earlier, gives two `wind_start` posts.
- The integration tests missed it because `_observations(now)` puts the latest reading exactly at `now` (`tests/test_integration_smoke.py:132`).

The root mistake is in the plan (section 3, `hysteresis.py` bullet): it compared a timestamp from the observation clock with an instant from the run clock.

### A.2 The fix: compare against the start of the closed period, not the window opening

**New rule.** The cut-off is the instant the closed period before today's window began:

- `cutoff = prev[1]` (yesterday's window close) when yesterday had a window and `prev[1] < window[0]`;
- `cutoff = today's local midnight` (Helsinki, as UTC) when yesterday had no window (polar night, or an empty intersection);
- no cut-off (`None`) when there was no closed period (`prev[1] >= window[0]`, i.e. always-open setups), or when today has no window (the gate has already returned in that case).

An ALERTED state is expired iff every notification time is `< cutoff` (or there are none). The comparison itself is unchanged from `hysteresis.py:84`; only the instant it compares against changes.

**Why this is correct, in both directions.**

1. *Yesterday's notifications are always expired.* Every notification from yesterday's window was stamped with an observation time ≤ that run's fetch time, and the run itself passed the gate, so it started before `prev[1]`. The stamp is therefore `< prev[1]` (see the residual case in A.7). For the "no window yesterday" case, every earlier notification is before today's local midnight by definition.
2. *Today's notifications are never expired, however old the observation is.* Any stamp written today is `latest.timestamp` from a fetch made today. This is safe as long as that observation is newer than the cut-off. That rests on a structural margin, not on a lag allowance. With the owner's config, the shortest closed period in Tampere is around midsummer: close `min(sunset 20:12Z − 2 h, 19:00Z) = 18:12Z`, next open `max(sunrise 00:41Z, 03:00Z) = 03:00Z`, so about **8 h 48 min** (inputs: the section 7 reference table, 2026-06-21; the 20th differs by seconds). The fetch lookback is `max(60, 30, 8 × 60) = 480` min (`src/main.py:132-134`, with `chart.enabled: true` and `lookback_hours: 8` at `config.yaml:32-33`). So no observation FMI returns on an in-window run can be older than the cut-off: open − 8 h is later than open − 8 h 48 min. A 3-minute or a 45-minute FMI delay makes no difference.
3. *A guard makes point 2 unconditional* for other configs: another location, a longer `lookback_hours`, or polar night yesterday with an early sunrise today. See A.3, `main.py`. If the latest observation is older than the cut-off, it describes the closed period or earlier, so it cannot be the basis of a "go now" alert. The run logs a warning and returns 0 without loading or saving state. Together with point 2, this gives the invariant: **on a run after a closed period, every stamp `evaluate()` writes is `>= cutoff`, and the cut-off is the same for every run in the window, so a state written today is never expired today.** "Exactly one `wind_start`" follows from that. With the owner's config the guard cannot fire (point 2); it exists so that the invariant does not depend on a lookback setting.

**Why the cut-off does not move during the day.** It depends only on the Helsinki local date of `now` (`daylight.py:106`), and a window never crosses local midnight, because the cap ends at hour ≤ 24 and the close is exclusive.

### A.3 Files to modify (amendment)

**`src/core/daylight.py` — `current_window`**
- Return `(window, carry_over_cutoff)` instead of `(window, follows_gap)`, where `carry_over_cutoff: Optional[datetime]` follows A.2:
  ```
  if window is None:            cutoff = None
  elif prev is None:            cutoff = _local_midnight_utc(day)
  elif prev[1] < window[0]:     cutoff = prev[1]
  else:                         cutoff = None
  ```
  `_local_midnight_utc` already exists (`daylight.py:33`). Update the docstring to say what the cut-off means and why it is the close and not the open (one sentence: "notification stamps are observation times, which lag the run").
- Callers: `src/main.py:75` and `tests/test_daylight.py` (`test_follows_gap`, `test_current_window_uses_helsinki_date`, `test_six_am_cap_in_summer_tampere`, `test_polar_night_has_no_window`, which unpack `window, _`). Those that discard the second element need no change.

**`src/core/hysteresis.py` — `expire_carried_over_alert`**
- Rename the parameter `window_open` to `cutoff`. The body is unchanged (`max(notified) >= cutoff` keeps the state). Update the docstring: the cut-off is the start of the closed period, and it is deliberately not the window opening, because stamps are observation times (line 122) that lag the run.

**`src/main.py`**
- `alert_window_now` (lines 71-84): return `(is_open, window, carry_over_cutoff)`. Keep the line-83 comparison exactly as it is.
- `run()`: rename `follows_gap` to `cutoff` at line 116.
- **Stale-observation guard**, immediately after `latest = observations[-1]` (line 144) and before the forecast fetch:
  ```python
  if cutoff is not None and latest.timestamp < cutoff:
      log.warning("Latest observation %s predates the closed period (since %s) - skipping this run.",
                  latest.timestamp.isoformat(), cutoff.isoformat())
      return 0
  ```
  This returns before `load_state`, so state is not read or written, the same as the outside-window path.
- Lines 156-160: `if cutoff is not None: expired = hysteresis.expire_carried_over_alert(state, cutoff)`. Keep the log line.

No other file changes. `config.py` is untouched (see A.5 for the bool parsing decision).

### A.4 Ordered steps (amendment; do them on `wa-1-daylight` on top of da06542)

1. **Regression tests first, and see them fail on da06542.** Add the A.5 tests marked *(regression)*.
   *Check:* `PYTHONPATH=src python -m pytest tests/test_integration_smoke.py -k lagged tests/test_hysteresis.py -k cutoff` fails. The integration test should show `mock_post.call_count == 2`, and the second caption should start with "Tuulee ajokelpoisesti". If it passes on unchanged code, the test is not exercising the lag: check that the first run's observation is before `window_open`.
2. **`daylight.current_window`** returns the cut-off; update `test_follows_gap` → `test_carry_over_cutoff`.
   *Check:* `pytest tests/test_daylight.py` passes.
3. **`hysteresis.expire_carried_over_alert`** parameter rename and docstring; update the unit tests per A.5.
   *Check:* `pytest tests/test_hysteresis.py` passes.
4. **`main.py`**: the rename, the cut-off passed to expire, and the stale guard.
   *Check:* the step 1 tests now pass, and every test in `tests/test_integration_smoke.py` passes.
5. **Should-fix test changes** (A.5, items S1-S3).
   *Check:* `PYTHONPATH=src python -m pytest`: full suite green. Also run S1 against a deliberately broken copy, temporarily dropping `min(close_at, …)`'s cap operand at `daylight.py:85` in a scratch edit and reverting it. The new test must fail, and the old one at margin 120 would not have failed. Do not commit the break.

### A.5 Test plan (amendment)

| # | Test (file :: name) | Setup | Passes when | A failure looks like |
|---|---|---|---|---|
| R1 *(regression)* | `test_integration_smoke.py::test_lagged_morning_runs_send_one_wind_start`, parametrised over `obs_lag` = 3 min and 45 min | `open_ = daylight.alert_window(date(2026,10,26), 61.5177, 23.7538, (6,22), True, 120)[0]` (computed, not hard-coded; about 05:36Z). Start from `ALERTED_STATE`. Three runs at `open_ + 2 min`, `+ 12 min` and `+ 22 min`, each with the latest observation at `run − obs_lag`, so the first one is before `open_`. Each run's `after` state is passed in as the next run's `state_json`. Windy. | Total posts across the three runs == 1. The first run's caption contains "Tuulee ajokelpoisesti" and not "edelleen". Runs 2 and 3 do not post. The final state is `ALERTED` with `last_alert_at` equal to the first run's observation time. | Run 2 posts a second `wind_start` (the bug); or run 1 posts `wind_still` (the carry-over was not expired) |
| R2 *(regression)* | `test_hysteresis.py::test_notification_before_window_open_but_after_cutoff_is_kept` | `CUTOFF = 2026-10-25T12:43:00Z`. ALERTED, `last_alert_at = 2026-10-26T05:35:20Z` (before a 05:36Z opening) | returned state is unchanged | state goes IDLE |
| R3 | `test_hysteresis.py::test_cutoff_boundary` | ALERTED with the latest notification exactly at `CUTOFF`, and again at `CUTOFF − 1 s` | at `CUTOFF`: kept; at `− 1 s`: IDLE | inverted boundary (`>` instead of `>=`) |
| R4 | `test_integration_smoke.py::test_stale_observation_after_gap_is_ignored` | Run `2026-10-26T07:00Z`, `ALERTED_STATE`, observations ending `2026-10-25T12:30Z` (before the 10-25 close at about 12:43Z), windy | no post; `fetch_observations` called; state text after == before | a `wind_start` built from yesterday's data, or a rewritten state |
| R5 | `test_daylight.py::test_carry_over_cutoff` (replaces `test_follows_gap`) | Tampere 6-22 / daylight / 120 at `2026-10-26T07:00Z`; the same with `(0,24)` and daylight off; Utsjoki 2027-01-17 (polar night the day before; the developer confirms with `sun_times` that the 16th is `None` and the 17th is not, or picks the first such date and records it) | cut-off == `alert_window(date(2026,10,25), …)[1]`; `None`; == Helsinki midnight of the Utsjoki date | the cut-off equals the window opening (old behaviour), or it is set for 0-24 |

Changes to existing tests:
- `test_hysteresis.py`: replace `WINDOW_OPEN` with `CUTOFF = datetime(2026, 10, 25, 12, 43, tzinfo=timezone.utc)`. The existing four tests keep their intent. `test_alert_from_current_window_is_kept` still holds (06:10Z on 10-26 > cut-off).
- `test_integration_smoke.py`: `_observations(now, speed, lag=timedelta(0))` puts the three readings at `now − lag − 20/10/0 min`; `_run_at` gains `obs_lag` and passes it through. Existing callers are unchanged.

Should-fix items from the review:
- **S1.** `test_daylight.py::test_22_cap_on_polar_day`. On Utsjoki 2026-06-21, margin 120 puts sunset − 120 min at exactly 19:00Z (= 22:00 EEST), so the cap was never exercised. Parametrise over `sunset_margin_minutes` 0 and 60. Assert `window[1] == utc(2026, 6, 21, 19, 0)` exactly, 18:30Z (21:30 EEST) open and 19:30Z (22:30 EEST) closed. Without the cap the close would be 21:00Z or 20:00Z, and 22:30 would read as open.
- **S2.** Replace `test_daylight.py::test_window_open_inclusive_close_exclusive`, which tests the test file's own `is_open` helper, with `test_integration_smoke.py::test_alert_window_now_open_inclusive_close_exclusive`. Write `WINDOW_CONFIG_TEMPLATE` to a temp dir, load it with `core.config.load_config` (env vars set as in the other tests), take `open_, close = daylight.alert_window(date(2026,10,25), …)`, and assert that `main.alert_window_now(cfg, t)[0]` is True at `open_` and at `close − 1 s`, and False at `open_ − 1 s` and at `close`. A failure means `src/main.py:83` changed `<`/`<=`.
- **S3 (optional nice-to-have, taken).** After `WINDOW_CONFIG_TEMPLATE` is built, add module-level asserts that `"latitude: 61.5177"`, `"longitude: 23.7538"` and `"reminder_interval_minutes: 120"` are in it. A silent no-op `.replace` (if `CONFIG_TEMPLATE` is edited) would otherwise run every window test against the wrong coordinates.
- **Declined: strict bool parsing of `daylight_only`** (`src/core/config.py:242`). Every flag in the loader uses `bool(...)` (lines 227, 234, 249), so a strict parser for this one key breaks the pattern. The only misparse is a quoted string: `"false"` → True, which turns the gate *on*, the restrictive direction. An unquoted YAML `false`/`no` already parses correctly. If it is wanted, it should be done for all flags as a separate debt item.

### A.6 Superseded passages in sections 1-10

- §2 item 3, "the last notification was before the current window opened" → "every notification was before the start of the closed period that precedes the current window".
- §2 table row "First in-window run next morning…": unchanged in outcome; the mechanism is the cut-off.
- §3 `daylight.current_window` return value and `follows_gap` formula → A.3.
- §3 `hysteresis.py` bullet "is before `window_open`" → "is before `cutoff`".
- §3 `main.py` bullet "run `expire_carried_over_alert(state, window[0])`" → `(state, cutoff)`, plus the stale guard.
- §7 "FMI observations … are built relative to the injected `now` (`now - 20/10/0 min`)" → the lag-aware helper above; `test_follows_gap` → R5.

### A.7 Risks and open questions (amendment)

- **Residual edge, accepted.** `fetch_observations` takes its own `datetime.now()` (`src/core/fmi_client.py:162`), after the gate's `now`. An observation stamped at or after `prev[1]` could therefore be returned by a run that passed the gate just before closing, if the fetch (with retries) finished ≥ ~3 min after closing and a new 10-min reading was published in between. That stamp would then be `≥ cutoff`. The consequence: the next morning would keep ALERTED and send `wind_still` ("still windy") instead of `wind_start`. It is never a duplicate and never a night message. I judge it too unlikely to justify clamping stamps to the gate time, which would change `evaluate()`'s reminder arithmetic.
- **The lag numbers are the reviewer's.** I rely on them only for the existence of a lag. The fix does not depend on its size.

### A.8 Owner-visible change

**None intended.** The messages, their texts and the times they may arrive are unchanged. The only observable difference is that a duplicate morning `wind_start` (two "Tuulee ajokelpoisesti" about 10 min apart, if the first run happens within ~3 min of the window opening) can no longer happen. The stale-data guard cannot trigger with the owner's config (A.2 point 2). No new question for the owner.

### A.9 Architecture doc impact (amends §5)

§5 item 1 stands, with the new path described accurately. Scribe should write it as: at the first in-window run after a closed period, an ALERTED state whose last notification is older than the start of that closed period (the previous window's close) goes to IDLE silently. Not "older than the window opening". Add to the gate sentence §5 promised that a run whose latest FMI observation predates that closed period is skipped without touching state. No other statement in `ARCHITECTURE.md` is affected beyond the §5 list.
