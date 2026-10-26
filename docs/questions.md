# Questions

## Open

- **Q8 (decision, 2026-10-26)** — The daylight rule was seen working this evening (a check at 17:21 was skipped, nothing sent). Mark it finished now, or wait until tomorrow's first windy morning shows exactly one new alert? Default: mark finished now.

## Answered

- **Q7 (priority, 2026-10-26)** — The wind check is set to run every 10 minutes but GitHub runs it only every 2-5 hours (on 2026-10-26 only at 10:35 and 11:54 Finnish time, so a reminder due ~12:35 never went out; owner noticed no alert while the wind was above the limit). Fix this next, once the daylight rule is verified? Default: yes, next. **Answer (2026-10-26): yes, fix next — no alert may be missed during allowed hours.**
- **Q4 (decision, 2026-10-26)** — Approve the daylight-only alerts plan? **Answer (2026-10-26): yes.**
- **Q5 (decision, 2026-10-26)** — When the daylight window closes with an alert on: silent or a note? **Answer (2026-10-26): silent.**
- **Q6 (decision, 2026-10-26)** — Still windy next morning: full alert or short reminder? **Answer (2026-10-26): full new alert.**

- **Q3 (decision, 2026-10-26)** — Should alerts come only in daylight, and how long before sunset should they stop? **Answer (2026-10-26): stop 2 h before sunset.** Start at sunrise and the 6-22 Finnish-time limit taken from the default (not contradicted).
- **Q1 (decision, 2026-10-26)** — Merge yesterday's changes (spot recommendations, Tampere spots, Windy link, hourly forecast table, model comparison) so they go live? **Answer (2026-10-26): yes.** Merged into main.
- **Q2 (decision, 2026-10-26)** — At what wind speed should the alert arrive? **Answer (2026-10-26): 7.5 m/s.** Lower limit raised 6.0 → 7.0 m/s (trigger margin 0.5 unchanged).
