# Arkkitehtuuri - WindAlert

Kuvaa koodin sellaisena kuin se on. Suunnitelmat ja perustelut:
`docs/plans/`, tehtävät: `docs/backlog.md`.

## 1. Ajon kulku (`src/main.py`, `run(config_path, now=None)`)

Jokainen ajo on erillinen prosessi (Actions, cron, systemd, Docker). Järjestys:

1. Konfiguraation lataus ja validointi (`core/config.py`, virhe -> poistuminen).
2. **Ilmoitusikkuna** (`alert_window_now` -> `core/daylight.py`): ikkunan
   ulkopuolella ajo kirjaa yhden rivin ja palaa 0:lla. Mitään ei haeta,
   tilaa ei lueta eikä kirjoiteta.
3. `build_notifiers()`; ei yhtään käyttökelpoista -> paluuarvo 1.
4. FMI-havainnot (`core/fmi_client.py`, retry+backoff). Virhe -> 1, ei havaintoja -> 0.
5. **Vanhentuneen havainnon vahti**: jos viimeisin havainto on vanhempi kuin
   `cutoff` (ks. §3), ajo palaa 0:lla lukematta tai kirjoittamatta tilaa.
6. Ennuste (valinnainen), `load_state`, `expire_carried_over_alert` (vain jos
   `cutoff` ei ole None), `hysteresis.evaluate`.
7. Jos `should_notify`: viesti `core/message.py`:llä (kuva `core/chart.py`,
   `core/spots.py`, `core/open_meteo.py` mallivertailu), lähetys kaikille
   kanaville erikseen (yhden kanavan virhe ei estä muita), telemetria jos päällä.
8. `save_state` aina ilmoituspolun jälkeen. `send_alert` ei palauta
   tulosta, joten tila tallentuu myös silloin kun kaikki kanavat epäonnistuivat.

Ajon kello on `now` (UTC, oletus `datetime.now(timezone.utc)`); testit
syöttävät sen parametrina. `now` ei riipu ajoympäristön aikavyöhykkeestä.

`Notifier`-rajapinta (`src/notifiers/base.py`): `send(alert) -> bool`, `name() -> str`.
`NOTIFIER_FACTORIES` (`main.py`) on ainoa paikka, joka tuntee kanavatyypit;
vain `enabled: true` -kanavat ladataan ([adding-a-notifier.md](adding-a-notifier.md)).

## 2. Ilmoitusikkuna (`core/daylight.py`, puhdas, vain stdlib)

- Ikkuna päivälle (Europe/Helsinki-päivä) on `[max(auringonnousu, start:00),
  min(auringonlasku - marginaali, end:00))`. Alku on mukana, loppu ei.
  Auringonnousu/-lasku lasketaan paikallisesti (NOAA/Meeus, ei verkkoa).
  Napapäivä = koko päivä, kaamos = ei ikkunaa (`alert_window` -> None).
- Asetukset `schedule:` (`ScheduleConfig` `core/config.py`): `active_hours`
  (Suomen aika, oletus `"0-24"`, loppu poissulkeva), `daylight_only`
  (oletus `false`), `sunset_margin_minutes` (oletus `0`). Lataus epäonnistuu,
  ellei `0 <= start < end <= 24` ja marginaali >= 0. `config.yaml` ja
  `config.example.yaml`: `"6-22"`, `true`, `120`.
- `current_window()` palauttaa `(ikkuna, cutoff)`. `cutoff` = edellisen
  ikkunan sulkeutumishetki (tai paikallinen keskiyö, jos eilen ei ollut
  ikkunaa); `None`, jos suljettua jaksoa ei ollut (esim. `"0-24"` ilman
  daylight-tarkistusta) tai tänään ei ole ikkunaa.
- `LOCAL_TZ` on määritelty sekä `daylight.py`:ssä että `chart.py`:ssä
  (`daylight.py` ei tuo matplotlibia).

## 3. Hystereesi (`core/hysteresis.py`)

Tila `IDLE`/`ALERTED`, persistoitu JSON:iin (`state_path`; Actionsissa
`state/wingfoil_alert_state.json`): `state`, `last_alert_at`, `last_reminder_at`.

- **IDLE -> ALERTED** (`wind_start`): vähintään kaksi havaintoa >=
  `min_speed_ms + trigger_margin_ms` ja niiden väli >= `min_minutes_above`,
  laskettuna FMI:n tämän ajon havaintohistoriasta (`required_window_minutes()`),
  ei ajojen välisestä tilasta.
- **ALERTED -> IDLE** (`wind_stop`, ilmoitus lähtee): nopeus alle
  `min_speed_ms - release_margin_ms`, yli `max_speed_ms` tai suunta ei kelpaa.
- **ALERTED -> IDLE ilman ilmoitusta** (`expire_carried_over_alert(state, cutoff)`):
  ensimmäisellä ikkunan sisäisellä ajolla suljetun jakson jälkeen ALERTED-tila,
  jonka kaikki ilmoitusleimat ovat `< cutoff` (tai niitä ei ole), muuttuu
  IDLE:ksi; `last_alert_at` säilyy, `last_reminder_at` tyhjenee. Jos tuuli on
  yhä hyvä, `evaluate` lähettää uuden `wind_start`.
- **Muistutus** (`wind_still`): `reminder_interval_minutes` > 0 ja se on
  kulunut edellisestä ilmoitusleimasta. Lähtee vain ikkunan sisällä, koska
  ikkunan ulkopuolella `evaluate` ei ajeta.
- **Puuttuva data**: tila ei muutu, ei ilmoitusta.
- **Invariantti**: `last_alert_at`/`last_reminder_at` ovat viimeisimmän
  havainnon aikaleima (`evaluate`: `now = latest.timestamp`), eivät ajon
  kello; havainnot jäävät ajosta jälkeen. Siksi `cutoff` on sulkeutumishetki,
  ei ikkunan avautuminen: päivän ikkunan sisällä kirjoitettu leima on aina
  `>= cutoff`, joten samana päivänä tallennettua tilaa ei vanhenneta uudelleen
  (ei kaksoisviestiä aamulla).
- Vanhat tilatiedostot latautuvat (`from_json` ohittaa tuntemattomat kentät);
  korruptoitu tiedosto -> tuore tila.

## 4. Repo-rakenne

```
README.md, PRIVACY.md, LICENSE
config.yaml, config.example.yaml, .env.example, requirements.txt (requests, PyYAML, matplotlib)
src/main.py                 # ajon kulku, NOTIFIER_FACTORIES
src/core/
  models.py                 # Alert, WindReading, ForecastPoint, AlertState
  config.py                 # lataus, validointi, ${ENV_VAR}-substituutio
  daylight.py               # ilmoitusikkuna, auringonnousu/-lasku
  fmi_client.py             # FMI WFS, retry+backoff, asemahaku
  open_meteo.py             # mallivertailuennusteet (kaavio)
  hysteresis.py             # tilakone + state.json
  message.py                # Alert-tekstit
  chart.py                  # matplotlib PNG (Agg)
  spots.py                  # spottisuositukset tuulensuunnan mukaan
src/notifiers/              # base.py, telegram.py (sendPhoto), email_notifier.py, ntfy.py (vain teksti)
src/telemetry/reporter.py   # opt-in, anonymisoitu
telemetry-server/           # valinnainen Cloudflare Worker
.github/workflows/          # run_alert.yml, keep_alive.yml
docker/                     # Dockerfile, docker-compose.yml
docs/                       # architecture.md (tämä), hosting-*.md, adding-a-notifier.md,
                            # telemetry.md, backlog.md, questions.md, plans/
state/                      # wingfoil_alert_state.json (Actions committoi)
tests/                      # test_{chart,config,daylight,hysteresis,integration_smoke,
                            #  message,open_meteo,spots,telemetry}.py - 91 testiä
```

Testit ajetaan: `PYTHONPATH=src python -m pytest`.

## 5. Ilmoituskanavat ja kuvat

Telegram (kuva `sendPhoto`) ja Email (SMTP, MIME-liite) lähettävät
`Alert.image_path`-kuvan, jos se on asetettu; ntfy.sh lähettää vain tekstin.
Kaavio (`chart.enabled`, oletus `false`) piirtää havainnon, puuskan, ennusteen
ja rajaviivat. WhatsApp ei ole ydinprojektissa.

## 6. Telemetria (`telemetry/reporter.py`)

- Päällä vain jos `enabled` JA `endpoint` on asetettu.
- `round_to_grid()` pyöristää sijainnin ~0.5 asteen ruudulle ennen lähetystä.
- Satunnainen `instance_id` tallennetaan paikallisesti (`~/.wingfoil_instance_id`).
- Lähetys on fire-and-forget, virheet nielaistaan.
- `telemetry-server/worker.js` ei tallenna `instance_id`:tä. Katso
  [telemetry.md](telemetry.md), [PRIVACY.md](../PRIVACY.md).

## 7. Hostaus

- **GitHub Actions** (`run_alert.yml`): cron `*/10 4-21 * * *` (UTC) sekä
  `workflow_dispatch`; molemmat kulkevat `main.run`in ikkunatarkistuksen
  läpi. Ajo asettaa `PYTHONPATH=src`, ei `TZ`:ta. Lopuksi `git add state/` ja
  commit vain jos tila muuttui, joten ikkunan ulkopuoliset ajot eivät
  tuota committeja. `keep_alive.yml` (cron `0 6 1 * *`) tekee kuukausittaisen committin.
- **Itsehostaus** ([hosting-self-host.md](hosting-self-host.md)): cron/systemd.
- **Docker** (`docker/`): ajastus host-koneen croniin.

## Open questions

- Kesäaamut 06:00-07:00 paikallista aikaa: cron alkaa 04:00 UTC = 07:00 EEST,
  joten ikkunan alku ennen sitä ei koskaan tule tarkistetuksi (cron + `config.yaml`).
- `fetch_observations` ottaa oman `datetime.now()`:nsa (`fmi_client.py`) portin
  `now`in jälkeen; ei vaikuta ikkunatarkistukseen, mutta ajon kello ei ole yksi.
