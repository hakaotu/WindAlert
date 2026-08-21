# 🏄 Wingfoil / Kite / Surf -tuuli-ilmoitin

Avoimen lähdekoodin tuuli-ilmoitin suomalaisille vesiurheilijoille.
Se seuraa Ilmatieteen laitoksen (FMI) avointa dataa valitsemaltasi lokaatiolta ja
lähettää ilmoituksen valitsemaasi kanavaan (Telegram, sähköposti, ntfy),
kun tuuli on juuri sinulle sopivissa lukemissa - oikeasta suunnasta ja
riittävän kauan.

Tää on suunniteltu niin, että kuka tahansa vähän tietokonetta käyttänyt voisi
ottaa tämän omaan käyttöön ilman että kenenkään
tarvitsee ylläpitää keskitettyä palvelinta. Palaute kiinnostaa, että onnistuuko :D Uskoisin, että kokemattomampikin käyttäjä saisi tän pystyyn AI-botin kanssa, mutta kertokaa, miten käy :)

## Ominaisuudet

**v0.1 / v0.2:**
- ✅ Konfiguroitava lokaatio (anna koordinaatit - lähin FMI-havaintoasema
  haetaan automaattisesti, tai määritä `fmi_station_id` itse)
- ✅ Tuulen ala- ja yläraja + **hystereesi** (ei turhia peräkkäisiä
  ilmoituksia tuulen heilahdellessa rajan tuntumassa)
- ✅ **Suuntafiltteri** - turvallisuuskriittinen ominaisuus rannikolla ja
  järvillä: rajaa pois esim. mantereesta pois päin puhaltavat (offshore) suunnat
- ✅ Ennuste seuraaville tunneille mukaan hälytysviestiin (HARMONIE-malli)

**v0.3 :**
- ✅ **ntfy.sh-kanava** - ilmainen push-ilmoitus puhelimeen, ei API-avainta
- ✅ **Graafi hälytysviestin mukana** (Telegram-kuva / sähköpostin
  liitetiedosto) - näyttää havaitun tuulen, puuskat ja ennusteen

**Kaikissa versioissa:**
- ✅ Telegram- ja sähköpostikanavat, plugin-arkkitehtuurilla uusien
  kanavien lisäämiseksi (ks. [docs/adding-a-notifier.md](docs/adding-a-notifier.md))
- ✅ Kolme dokumentoitua hostausvaihtoehtoa - et tarvitse minkäänlaista
  omaa palvelinta jos et halua
- ✅ Robustius: retry+backoff FMI-kutsuissa, ei kaadu puuttuvaan dataan,
  22 yksikkö- ja integraatiotestiä

## Pika-aloitus

Valitse yksi kolmesta hostauspolusta sen mukaan, mikä sopii sinulle:

| Tilanne | Polku |
|---|---|
| "En halua omaa palvelinta" | 👉 [docs/hosting-github-actions.md](docs/hosting-github-actions.md) - ilmainen, ei tarvita mitään laitetta |
| "Minulla on Raspberry Pi / VPS / kotipalvelin" | 👉 [docs/hosting-self-host.md](docs/hosting-self-host.md) - cron tai systemd |
| "Haluan Dockerin" | 👉 [docker/](docker/) - Dockerfile + compose |

Kaikissa poluissa lähtökohta on sama:

```bash
git clone <tämä repo tai forkkisi>
cd WindAlert
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # muokkaa lokaatio, tuulirajat, kanavat
cp .env.example .env                 # täytä Telegram/SMTP-salaisuudet
set -a && source .env && set +a      # lataa salaisuudet ympäristöön tätä testiajoa varten
PYTHONPATH=src python3 src/main.py --config config.yaml   # testiajo
```

## Konfiguraatio

Katso [config.example.yaml](config.example.yaml) - se on täysin
kommentoitu ja sisältää kaikki asetukset: lokaatio, tuulirajat,
hystereesi, suuntafiltteri, ennuste, ilmoituskanavat.

**Tärkeä turvallisuushuomio:** aseta `direction_filter`, jos
lokaatiollasi jokin tuulen suunta on vaarallinen (esim. puhaltaa
pois päin mantereesta eli voi ajautua kauas rannasta). Tyhjä lista
hyväksyy kaikki suunnat.

## Arkkitehtuuri lyhyesti

```
config.yaml → Core-engine (FMI-haku, hystereesi, viestin muodostus)
                   │
                   ▼
         Notifier-pluginit (Telegram, Email, ...)
```

Ydinlogiikka ei tiedä mitään yksittäisistä ilmoituskanavista - ne
toteuttavat yhteisen `Notifier`-rajapinnan (`src/notifiers/base.py`).
Uuden kanavan lisääminen on yhden tiedoston kirjoittamista, ks.
[docs/adding-a-notifier.md](docs/adding-a-notifier.md).

Täysi arkkitehtuurisuunnitelma: [ARCHITECTURE.md](ARCHITECTURE.md).

## Testit

```bash
pip install -r requirements.txt pytest
PYTHONPATH=src pytest tests/ -v
```

22 testiä kattaa hystereesilogiikan (mm. yksittäinen puuska ei laukaise
hälytystä, väärä tuulensuunta estää hälytyksen, puuttuva data ei kaada
ohjelmaa), configin validoinnin, graafin generoinnin, telemetrian
sijainnin pyöristyksen, ja lopuksi koko `main.py`-putken päästä päähän
mockatulla FMI-datalla (`tests/test_integration_smoke.py`) - tämä nappaa
virheet, jotka jäävät moduulien välisiin liitoskohtiin, vaikka
yksittäiset yksikkötestit menisivät läpi.

## Lisenssi

MIT, ks. [LICENSE](LICENSE). Contribuutiot tervetulleita - varsinkin
uudet notifier-pluginit ja muiden maiden sääpalveluiden tuki.
