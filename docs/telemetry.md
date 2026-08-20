# Telemetria (v0.3, täysin valinnainen)

Oletuksena `telemetry.enabled: false` - mitään ei lähetetä minnekään,
tämä ohje on relevantti vain jos päätät ottaa sen käyttöön.

## Miksi tämä on olemassa

Projekti on hajautettu: jokainen asentaa oman instanssinsa omalle
laitteelleen tai omaan GitHub Actions -ympäristöönsä. Kenelläkään ei
ole automaattisesti näkyvyyttä siihen, kuinka moni tätä käyttää tai
missä päin Suomea. Jos tätä tietoa halutaan (esim. yhteisön kokoluokan
hahmottamiseksi), se vaatii tietoisen, läpinäkyvän "soita kotiin"
-toiminnon - ei piilotettua seurantaa.

## Mitä lähetetään, jos otat käyttöön

Yksi HTTP POST -kutsu jokaisen hälytyksen yhteydessä (`wind_start` /
`wind_stop`), sisältäen:

```json
{
  "instance_id": "satunnainen uuid, generoitu paikallisesti ensimmäisellä ajolla",
  "region_grid": "62.5,26.5",
  "date": "2026-08-20",
  "event": "wind_start"
}
```

- `region_grid`: koordinaattisi pyöristettynä ~0.5 asteen ruutuun
  (~50 km) - ei koskaan tarkkaa sijaintiasi.
- `instance_id`: satunnainen, ei yhdistettävissä Telegram-tiliisi,
  sähköpostiisi tai mihinkään muuhun. Tallennetaan paikallisesti
  `~/.wingfoil_instance_id`-tiedostoon.
- Ei viestien sisältöä, ei minuutin tarkkuudella olevia aikaleimoja.

Koodi: [`src/telemetry/reporter.py`](../src/telemetry/reporter.py) -
voit lukea sen itse tarkistaaksesi väitteen.

## Jos haluat ottaa telemetrian käyttöön

Tarvitset endpointin, jonne data lähetetään. Kaksi vaihtoehtoa:

1. **Yhteisön jaettu endpoint** (jos ylläpitäjä on julkaissut sellaisen)
   - katso projektin README/Discussions ajantasainen osoite.
2. **Pystytä oma** - `telemetry-server/`-kansiossa on esimerkki
   Cloudflare Workerina (ilmainen taso riittää pieneen käyttöön):
   ```bash
   cd telemetry-server
   npm install -g wrangler
   wrangler kv:namespace create WINGFOIL_KV
   # kopioi tuloksena saatu id wrangler.toml:iin
   wrangler deploy
   ```
   Aseta sitten omassa `config.yaml`:ssasi:
   ```yaml
   telemetry:
     enabled: true
     endpoint: "https://<oma-workerisi>.workers.dev"
   ```

## Referenssipalvelimen (worker.js) suunnittelu

Vaikka client lähettää `instance_id`:n, esimerkkipalvelin **jättää sen
tietoisesti tallentamatta** - se säilyttää ainoastaan aggregoituja
laskureita (`päivä + karkea alue + tapahtumatyyppi -> lukumäärä`).
Tämä tarkoittaa, että vaikka joku pääsisi käsiksi tietokantaan, siitä
ei voi rekonstruoida yksittäisen käyttäjän toimintaa - vain päivä- ja
aluetason kokonaismääriä. Tämä on tietoinen suunnitteluvalinta, ei
sattumaa - suosittelemme säilyttämään tämän periaatteen, jos muokkaat
palvelinkoodia.

Tämä ei ole lakineuvontaa - ks. [PRIVACY.md](../PRIVACY.md).
