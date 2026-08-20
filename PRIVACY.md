# Tietosuoja ja käyttöseuranta

**Oletustila: ei mitään telemetriaa lähetetä minnekään.**
`telemetry.enabled` on `false` oletuksena, ja vaikka asettaisit sen
todeksi, mitään ei lähde liikkeelle ellet myös aseta `telemetry.endpoint`
-osoitetta. Tämä on toteutettu versiossa v0.3, katso koodi
[`src/telemetry/reporter.py`](src/telemetry/reporter.py) ja tarkempi
käyttöohje [docs/telemetry.md](docs/telemetry.md).

## Periaatteet

1. **Oletuksena pois päältä**, ja kaksinkertaisella varmistuksella
   (enabled + endpoint pitää molemmat olla asetettuna).
2. **Anonymisointi tapahtuu paikallisesti**, koneellasi, ennen kuin
   mitään lähtee liikkeelle - ei koskaan keskuspalvelimella jälkikäteen.
3. **Ei koskaan tarkkaa sijaintia.** Koordinaatit pyöristetään ~0.5
   asteen ruudulle (~50 km) ennen lähetystä (`round_to_grid()`).
4. **Satunnainen instanssitunniste**, joka generoidaan paikallisesti
   ensimmäisellä ajolla ja tallennetaan `~/.wingfoil_instance_id`-
   tiedostoon. Ei koskaan yhdistetä Telegram-tiliin, sähköpostiin tai
   mihinkään muuhun tunnisteeseesi.
5. **Ei viestien sisältöä eikä minuutin tarkkuudella olevia
   aikaleimoja** - vain päivätason tapahtuma (`wind_start`/`wind_stop`)
   karkealta alueelta.
6. **Telemetria ei koskaan voi estää oikeaa hälytystä.** Lähetys
   tapahtuu vasta hälytyksen lähetyksen jälkeen, ja kaikki virheet
   nielaistaan hiljaisesti (`reporter.py`:n `report_event`) - hitaasti
   vastaava tai kaatunut telemetriaendpoint ei koskaan viivytä tai
   estä oikeaa tuulihälytystä.
7. **Täysi läpinäkyvyys.** Koska koko projekti on avointa lähdekoodia,
   voit itse lukea täsmälleen, mitä lähetetään - katso koodi, ei vain
   tätä tekstiä.
8. **Referenssipalvelin ei tallenna instanssitunnistetta.**
   [`telemetry-server/worker.js`](telemetry-server/worker.js) lukee
   `instance_id`-kentän mutta jättää sen tietoisesti tallentamatta -
   ainoastaan aggregoidut päivä+alue-laskurit persistoidaan. Tämä on
   suositeltu käytäntö, jos rakennat oman aggregointipalvelimen.

## GDPR-arvio lyhyesti

Yllä kuvatulla mallilla (opt-in, kaksoisvarmistus, karkea sijainti,
ei PII:tä, ei per-instanssi-dataa serveripuolella) data ei tyypillisesti
ole yhdistettävissä yksittäiseen luonnolliseen henkilöön kohtuullisin
keinoin, jolloin se ei ole GDPR:n tarkoittamaa henkilötietoa. Tämä ei
ole lakineuvontaa - jos rakennat tälle pohjalle laajempaa palvelua,
tarkista tilanne tarvittaessa tietosuojaviranomaisen ohjeista.

## Miksi näin varovaisesti?

Projekti on hajautettu - jokainen käyttäjä ajaa omaa instanssiaan omalla
laitteellaan tai omassa GitHub Actions -ympäristössään. Keskitetty
käyttöseuranta vaatii siis tietoisen, läpinäkyvän ja vapaaehtoisen
toiminnon - ei koskaan oletusarvoista piilotettua seurantaa.
