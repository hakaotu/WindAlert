# Backlog

Status values: todo / in-progress / review / verifying / done. Status moves are the main session's.

## WA-1 — Alerts and reminders only in daylight and inside 6-22 Finnish local time

Status: done (owner closed 2026-10-26 on the 15:21Z observation below; morning one-alert case covered by tests, not yet seen live)

Verification observation (main session, 2026-10-26 15:21Z = 17:21 local): manual workflow_dispatch run 40348483380 on main logged "Outside alert window (07:36-14:41) - skipping this run."; nothing sent, no state commit. Earlier in-window run 09:54Z (11:54 local) ran the new code without error (state ALERTED, 7.0 m/s, no notification). Not yet observed: the first windy in-window morning run sending exactly one wind_start.

**Who and why.** The owner, who sails/kites on Tampere lakes. Messages arrive after dark and in the middle of the night, so they cannot be trusted as "you can go out now". Towards winter the usable time on the water shrinks because dark comes early, so the problem grows each week.

**Observation (owner, 2026-10-26, in chat):** "nyt viestejä tulee, vaikka aurinko on jo laskenut ja ilmeisesti tuulee ajokelpoisesti tulee myös asetetun aikahaarukan ulkopuolella ... talvea kohti ne mahdolliset ajat olla vesillä kapenee, kun pimeä tulee aikaisin." (Messages arrive after sunset, and also outside the configured time window.)

**Facts read from GitHub Actions logs (main session, 2026-10-26):**
- On 2026-10-25 the "Wind alert check" workflow sent Telegram messages at 17:15Z, 19:45Z and 22:05Z (19:15, 21:45 and 00:05 Finnish time, EET = UTC+2).
- Sunset in Tampere on 2026-10-25 was about 16:35 local. Two of the three messages (19:15, 21:45) were after sunset; the 00:05 one was also outside 6-22.
- `config.yaml` has `schedule.active_hours: "6-22"` with the comment "paikallinen aika" (local time). The check in `src/main.py` (`is_within_active_hours`) compares `datetime.now().hour`, which on the GitHub runner is UTC, so the 00:05 local message (22:05Z) passed the check and was sent (main session's reading of the code, not re-verified by pm).
- There is no daylight or sunset logic anywhere.

**Business rules (owner, answered 2026-10-26, docs/questions.md Q3):**
- Alerts and reminders are sent only in daylight: from sunrise until 2 hours before sunset.
- Never outside 6-22 Finnish local time (`active_hours` is read as Europe/Helsinki local time).

**Assumption (recorded):** the start-at-sunrise and the 6-22 limit were the default offered to the owner, who answered only the "2 hours before sunset" part and did not contradict the rest. Treated as agreed unless the owner says otherwise.

**Acceptance criteria** (location: Tampere; times are Europe/Helsinki local; the stricter of the two windows applies, i.e. the alert window is [max(sunrise, 06:00), min(sunset - 2 h, 22:00)]):
1. Given a day when sunset - 2 h is earlier than 22:00 and the wind meets the alert condition, When the check runs at a time after sunset - 2 h, Then no Telegram alert is sent. (Check: 2026-10-25, sunset ~16:35, so the window closes ~14:35 local; the runs at 19:15, 21:45 and 00:05 local would send nothing.)
2. Given the wind meets the alert condition and the check runs before sunrise, When it runs, Then no alert is sent, even if the time is within 6-22.
3. Given the wind meets the alert condition and the check runs at 00:05 Finnish time (22:05Z on a winter-time day), When it runs, Then no alert is sent. The same holds in summer time (EEST, UTC+3), e.g. 00:05 local = 21:05Z.
4. Given a run on a runner whose clock is UTC, When the 6-22 limit is evaluated, Then it is evaluated against Europe/Helsinki local time: a run at 04:30Z in winter (06:30 local) is inside the limit, and a run at 20:30Z in winter (22:30 local) is outside it.
5. Given a summer day when sunrise is before 06:00 or sunset - 2 h is after 22:00, When the check runs at 05:30 or 22:30 local, Then no alert is sent (6-22 still caps the window).
6. Given the wind meets the alert condition and the run is inside the window (e.g. 2026-10-25 at 12:00 local), When it runs, Then the alert is sent as it is today.
7. Given an alert reminder would be due, When the run is outside the daylight window, Then the reminder is not sent either (reminders follow the same window as alerts).
8. Given a run inside the window whose wind data would not trigger an alert, When it runs, Then nothing is sent (no new messages are introduced by this task).

**Open questions (not decided here):**
- What happens to an active alert when the daylight window closes: stay silent, or send a closing message ("window closed for today")? For the owner in business terms; architect to cost the options.
- Should the hourly table in the chart mark dark hours (or hours outside the window)? Needs designer input if yes.
- Where the sunrise/sunset times come from (computed from the location or fetched) and how the test clock is controlled is for the architect.
- Does the rule apply to manually triggered runs of the workflow? Not stated by the owner; assumption until told otherwise: yes.

**Risks:**
- The GitHub schedule runs in UTC and may be delayed by minutes; a run near the window edge may fall on either side. Acceptance criteria are given for times clear of the edge; boundary behaviour (exactly at sunrise or sunset - 2 h) needs a decision from the architect.
- Daylight saving changes (last Sunday of March and October) shift the UTC/local relationship; the 2026-10-25 observation falls on the day clocks changed back, so the local times quoted above should be rechecked against the log timestamps when verifying.
- Alert state is persisted in the repo (commits "Update alert state"); suppressing sends must not leave the state wrong, e.g. marking an alert as sent when it was not.

**Rationale:** the owner is told "go now" at times when going is impossible or unsafe; the fix is making the daylight and local-time rules the owner stated actually hold.

## WA-2 — No alert or reminder may be missed during the allowed hours

Status: todo

**Who and why.** The owner, who sails/kites on Tampere lakes and relies on the alert to know when to go. The scheduled check does not run when it should, so an alert or reminder that is due inside the WA-1 daylight window can go unsent for the whole window.

**Observation (owner, 2026-10-26 ~17:15 Finnish time, in chat):** "miksei oo tullu hälyä, vaikka tuuli on yli thresholdin?" (why no alert although the wind is above the threshold?)

**Facts (main session, from `gh run list --workflow run_alert.yml` and run logs, 2026-10-26; not re-verified by pm):**
- `.github/workflows/run_alert.yml` schedules `*/10 4-21 * * *` (every 10 min, 04-21 UTC).
- Actual runs on 2026-10-26: 08:35Z (manual workflow_dispatch), 09:54Z (scheduled), 15:21Z (manual). No scheduled run between 09:54Z and at least 15:21Z.
- Over the two weeks before, scheduled runs happened about 4-6 times a day, 2-5 h apart (e.g. 2026-10-25: 09:01Z, 13:41Z, 17:15Z, 19:45Z, 22:05Z).
- At 09:54Z (11:54 local) the alert was active, wind 7.0 m/s, last reminder 08:33Z, reminder interval 120 min, so the next reminder was due about 10:33Z (12:33 local). No run happened before the daylight window closed at 14:41 local, so the reminder never went out.

**Business rule (owner, answered 2026-10-26, docs/questions.md Q7):** fix this next. "Ei saada jäädä tulematta ilmoja sallittuun aikaan" — no alert may be missed during the allowed hours (the WA-1 daylight window).

**Acceptance criteria** (times Europe/Helsinki local; "window" = the WA-1 alert window; N = the maximum gap between checks, to be set by the architect and the owner, see open questions):
1. Given an alert or reminder becomes due at a time T inside the window and the wind meets the alert condition, When the window is considered from T to its close, Then at least one check runs within N minutes after T and the notification is sent by then. (Check against the 2026-10-26 case: reminder due ~12:33 local, window closes 14:41 local; a check must have run and sent the reminder before 12:33 + N.)
2. Given any full day, When the checks that actually executed inside the window are listed (e.g. from `gh run list --workflow run_alert.yml` or the equivalent run history of the chosen scheduler), Then no gap between consecutive checks inside the window is longer than N minutes. (Counter-example today: 2026-10-26, 09:54Z to 15:21Z, a gap of 5 h 27 min with only the manual run between.)
3. Given the same inputs as the 2026-10-26 case (alert active, 7.0 m/s, last reminder 08:33Z, interval 120 min), When checks run on schedule with no manual trigger, Then exactly one reminder is sent, at the first check at or after 10:33Z, not zero and not several.
4. Given a run outside the window, When it runs, Then WA-1 behaviour is unchanged: nothing is sent and the run does not break the alert state.
5. Given the fix is in place, When it is observed over at least one full in-window day without manual triggers, Then the run history shows the gap limit in criterion 2 holding. (This is the verification observation; a single run is not enough.)

**Open questions (not decided here):**
- How frequent must checks be to count as "not missed"? The owner gave the rule but no number. For the owner, in business terms: how many minutes late may an alert or reminder be? Default if the owner says "don't know": the architect proposes N from the wind data's own update rate and the reminder interval.
- Which hosting or scheduling approach to use? For the architect: the GitHub schedule evidently does not run at the configured frequency, so the options and their cost, reliability and maintenance need costing.
- Why the schedule is skipped is not established. The main session's facts show the symptom (gaps), not the cause. The architect should not assume the cause.

**Risks:**
- The failure is intermittent (about 4-6 runs a day against 108 configured, 04-21 UTC at 10-minute steps), so a fix that looks right on one day may still fail on another; criterion 5 needs a full day of observation.
- A more frequent or different scheduler could send duplicate alerts or reminders if the alert state is read and written by overlapping runs; criterion 3 guards the single-reminder case.
- Any new hosting may need secrets (Telegram, data access) moved or duplicated: an access question for the owner if so.

**Rationale:** the owner's rule is that no alert is missed in the allowed hours; today's scheduler leaves hours-long gaps, so a due reminder can fall entirely outside the window.
