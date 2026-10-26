# Questions

## Open

- **Q4 (decision, 2026-10-26)** — Approve the plan for daylight-only alerts (alerts only from sunrise until 2 h before sunset, within 6-22 Finnish time) so it can be built? Default if "don't know": approve. [WA-1, docs/plans/wa-1-daylight-window.md]
- **Q5 (decision, 2026-10-26)** — When the daylight window closes while an alert is on, should the bot stay silent, or send a short "no more alerts today" note? Default: silent.
- **Q6 (decision, 2026-10-26)** — If it is still windy the next morning, should the first message be the full "it's windy, go" alert or the shorter "still windy" reminder? Default: the full alert.

## Answered

- **Q3 (decision, 2026-10-26)** — Should alerts come only in daylight, and how long before sunset should they stop? **Answer (2026-10-26): stop 2 h before sunset.** Start at sunrise and the 6-22 Finnish-time limit taken from the default (not contradicted).
- **Q1 (decision, 2026-10-26)** — Merge yesterday's changes (spot recommendations, Tampere spots, Windy link, hourly forecast table, model comparison) so they go live? **Answer (2026-10-26): yes.** Merged into main.
- **Q2 (decision, 2026-10-26)** — At what wind speed should the alert arrive? **Answer (2026-10-26): 7.5 m/s.** Lower limit raised 6.0 → 7.0 m/s (trigger margin 0.5 unchanged).
