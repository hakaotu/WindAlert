# Arkkitehtuuri - wingfoil-wind-alert

Tämä dokumentti kuvaa projektin toteutetun arkkitehtuurin (v0.1-v0.3) ja
suunnitellut jatkoaskeleet. Alkuperäinen suunnitelmavaihe on tiivistetty
tähän vastaamaan sitä, mikä on oikeasti rakennettu ja testattu - katso
git-historiaa, jos haluat nähdä alkuperäisen, laajemman ideointivaiheen.

## 1. Kulmakivet (pysyneet muuttumattomina koko toteutuksen ajan)

1. **Zero-cost-by-default** - oletuspolku (GitHub Actions, Telegram,
   ntfy.sh) toimii täysin ilmaisilla palveluilla.
2. **Config over code** - kaikki käyttäjän säädöt yhdessä
   `config.yaml`-tiedostossa, salaisuudet ympäristömuuttujina.
3. **Plugin-arkkitehtuuri ilmoituskanaville** - ydinlogiikka ei tiedä
   mitään yksittäisistä kanavista.
4. **Robustius ennen ominaisuuksia** - retry-logiikka, tilan pysyvyys ja
   testit ovat MVP:tä, ei jälkikäteen lisättävää.
5. **Yksityisyys sisäänrakennettuna** - telemetria on opt-in ja
   anonymisoitu jo lähteellä, ei vasta palvelimella.

## 2. Toteutunut arkkitehtuuri

```
config.yaml
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  src/main.py  (orkestrointi)                             │
│    │                                                      │
│    ├─▶ core/fmi_client.py    havainnot + ennuste + retry  │
│    ├─▶ core/hysteresis.py    IDLE/ALERTED-tilakone        │
│    ├─▶ core/message.py       Alert-olion muodostus        │
│    ├─▶ core/chart.py         PNG-graafi (valinnainen)      │
│    └─▶ telemetry/reporter.py anonyymi opt-in-raportointi   │
│                                                            │
│  build_notifiers() lataa vain enabled: true -kanavat:      │
│    notifiers/telegram.py, notifiers/email_notifier.py,     │
│    notifiers/ntfy.py                                       │
└─────────────────────────────────────────────────────────┘
```

Ydinperiaate näkyy suoraan koodissa: `Notifier`-rajapinta
(`src/notifiers/base.py`) määrittää vain `send(alert) -> bool` ja
`name() -> str`. `main.py`:n `NOTIFIER_FACTORIES`-sanakirja on ainoa
paikka, joka tietää minkä tyyppisiä kanavia on olemassa - uuden
lisääminen ei vaadi mitään muutoksia `core/`-kansioon
(ks. [docs/adding-a-notifier.md](docs/adding-a-notifier.md)).

## 3. Repo-rakenne (toteutunut)

```
wingfoil-wind-alert/
├── README.md
├── ARCHITECTURE.md            # tämä tiedosto
├── PRIVACY.md
├── LICENSE                    # MIT
├── config.example.yaml
├── .env.example
├── requirements.txt
├── src/
│   ├── main.py                 # orkestrointi, NOTIFIER_FACTORIES
│   ├── core/
│   │   ├── models.py           # Alert, WindReading, ForecastPoint
│   │   ├── config.py           # lataus, validointi, ${ENV_VAR}-substituutio
│   │   ├── fmi_client.py       # FMI WFS-asiakas, retry+backoff, asemahaku
│   │   ├── hysteresis.py       # tilakone + state.json-persistointi
│   │   ├── message.py          # Alert-tekstin + graafin muodostus
│   │   └── chart.py            # matplotlib PNG-graafi (Agg-backend)
│   ├── notifiers/
│   │   ├── base.py             # Notifier-rajapinta
│   │   ├── telegram.py         # + kuvaliite (sendPhoto)
│   │   ├── email_notifier.py   # SMTP + kuvaliite
│   │   └── ntfy.py             # ntfy.sh push-ilmoitukset
│   └── telemetry/
│       └── reporter.py         # opt-in, anonymisoitu raportointi
├── telemetry-server/
│   ├── worker.js               # esimerkki-Cloudflare Worker (valinnainen)
│   └── wrangler.toml
├── .github/workflows/
│   ├── run_alert.yml           # ajastettu ajo + state.json-committointi
│   └── keep_alive.yml          # estää 60pv-inaktiivisuussammutuksen
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/
│   ├── hosting-github-actions.md
│   ├── hosting-self-host.md
│   ├── adding-a-notifier.md
│   └── telemetry.md
└── tests/
    ├── test_hysteresis.py       # 8 testiä
    ├── test_config.py           # 4 testiä
    ├── test_chart.py            # 3 testiä
    ├── test_telemetry.py        # 5 testiä
    └── test_integration_smoke.py  # 2 testiä, koko main.run()-putki mockatulla FMI-datalla
```

## 4. Hystereesi - toteutettu logiikka

`core/hysteresis.py`:n tilakone (`AlertState.IDLE` / `AlertState.ALERTED`):

- **IDLE → ALERTED**: vaatii, että vähintään kaksi peräkkäistä mittausta
  ylittää `min_speed_ms + trigger_margin_ms`, ja niiden aikaleimojen
  välinen kesto on ≥ `min_minutes_above`. Yksittäinen mittaus ei
  koskaan riitä - tämä oli myös yksi kehityksen aikana löytynyt ja
  testissä (`test_single_spike_does_not_trigger`) kiinni jäänyt bugi.
- **ALERTED → IDLE**: joko tuuli alittaa `min_speed_ms - release_margin_ms`,
  ylittää `max_speed_ms`, tai suunta ei enää täytä `direction_filter`-ehtoa.
- **Puuttuva data**: ei muuta tilaa, ei lähetä ilmoitusta, ei kaada ohjelmaa.
- **Tila persistoidaan** JSON-tiedostoon (`state_path`), koska jokainen
  cron-/systemd-/Actions-ajo on erillinen prosessi.

## 5. Ilmoituskanavat - toteutunut vertailu

| Kanava | Tila | Kuvaliite | Huomio |
|---|---|---|---|
| Telegram | ✅ toteutettu | ✅ `sendPhoto` | Oletuskanava |
| Email (SMTP) | ✅ toteutettu | ✅ MIME-liite | Universaali fallback |
| ntfy.sh | ✅ toteutettu (v0.3) | ei (tekstiviesti) | Ilmainen push, ei API-avainta |
| WhatsApp | ei ydinprojektissa | - | Jätetty tarkoituksella community-pluginiksi epävirallisten rajapintojen epävakauden vuoksi |

## 6. Graafit (v0.3)

`core/chart.py` piirtää matplotlibilla (Agg-backend, ei vaadi
näyttöä) havaitun tuulen, puuskan ja ennusteen samaan kuvaan, sekä
ala-/ylärajaviivat. `chart.enabled: false` oletuksena, koska se on
raskaampi riippuvuus ja hidastaa ajoa hieman - käyttäjä ottaa käyttöön
tietoisesti. Kuva liitetään `Alert.image_path`-kenttään, ja
Telegram/Email-notifierit tarkistavat sen olemassaolon ja lähettävät
liitteenä; ntfy.sh lähettää toistaiseksi vain tekstin.

## 7. Telemetria (v0.3) - toteutunut malli

`telemetry/reporter.py` toteuttaa suunnitelmassa kuvatut periaatteet
suoraan koodissa:
- Kaksoisvarmistus pois päältä (`enabled` JA `endpoint` pitää molemmat olla asetettuna).
- `round_to_grid()` pyöristää sijainnin ~0.5 asteen ruudulle ennen lähetystä.
- Satunnainen `instance_id` tallennetaan paikallisesti (`~/.wingfoil_instance_id`).
- Lähetys on fire-and-forget, virheet nielaistaan - ei voi koskaan estää
  oikeaa hälytystä.

`telemetry-server/worker.js` on valinnainen esimerkki
aggregointipalvelimesta (Cloudflare Worker), joka tietoisesti **ei**
tallenna `instance_id`:tä - vain päivä+alue-tason laskureita. Tämä ei
ole pakollinen osa projektia; kuka tahansa voi pystyttää oman tai
käyttää yhteisön jaettua endpointia. Täysi selitys:
[docs/telemetry.md](docs/telemetry.md), periaatteet: [PRIVACY.md](PRIVACY.md).

## 8. Hostaus - toteutunut

- **GitHub Actions** (`.github/workflows/run_alert.yml`): committoi
  `state/wingfoil_alert_state.json`-tiedoston takaisin repoon jokaisen
  ajon lopussa, koska Actions-ympäristö on kertakäyttöinen.
  `keep_alive.yml` tekee kerran kuussa triviaalin committin estämään
  GitHubin 60 päivän inaktiivisuussammutuksen.
- **Itsehostaus** (`docs/hosting-self-host.md`): cron- ja
  systemd-timer-esimerkit, tila säilyy suoraan levyllä.
- **Docker** (`docker/`): Dockerfile + compose, ajastus jätetään
  host-koneen cronin vastuulle.

## 9. Roadmap - päivitetty tilanne

**v0.1/v0.2/v0.3: ✅ toteutettu ja testattu** (22 testiä, ks. `tests/`).

**Seuraavaksi harkittavaa (ei aikataulutettu):**
- Community-notifierit: WhatsApp (CallMeBot-pohjainen, selkeästi
  merkitty epäviralliseksi), Discord-webhook, Signal.
- Web-lomake config.yamlin tekoon ei-tekniselle käyttäjälle.
- Muiden maiden sääpalveluiden tuki (rajapinta on jo eristetty
  `core/fmi_client.py`:hin, joten toinen maa tarkoittaisi vaihtoehtoista
  clientia saman `WindReading`/`ForecastPoint`-mallin taakse).
- ntfy.sh-kuvaliitteen tuki (tällä hetkellä vain Telegram/Email).

## 10. Yhteenveto alkuperäisiin kysymyksiin

- **Ilmoituskanavat**: ratkaistu plugin-rajapinnalla, kolme kanavaa
  toteutettuna (Telegram, Email, ntfy.sh), WhatsApp tarkoituksella
  ulkopuolella epävakauden vuoksi.
- **Hostaus**: kolme dokumentoitua, testattua polkua, kaikki ilmaisia
  tai käyttäjän oman laitteen varassa - projektin ylläpitäjä ei hostaa mitään.
- **Käyttöseuranta**: toteutettu opt-in, kaksoisvarmistetulla,
  anonymisoidulla telemetrialla, jonka koodin voi itse lukea, plus
  valinnainen esimerkkiaggregointipalvelin, joka ei tallenna
  yksilötason dataa.
