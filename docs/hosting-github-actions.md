# Hostaus: GitHub Actions (suositeltu, ilmainen)

Tämä on helpoin tapa käyttää tuuli-ilmoitinta, jos sinulla ei ole omaa
palvelinta tai Raspberry Piä. Julkisilla GitHub-repoilla ajastetut
workflowt ovat täysin ilmaisia ja rajattomia.

## Vaiheet

1. **Forkkaa tämä repo** omaan GitHub-tunnukseesi.

2. **Ota Actions käyttöön.** Tämä on tärkein askel, jonka moni unohtaa:
   kun repo forkataan, GitHub poistaa ajastetut workflowt käytöstä
   oletuksena. Mene forkkisi **Actions**-välilehdelle, hyväksy
   "I understand my workflows, go ahead and enable them" ja varmista,
   että sekä `Wind alert check` että `Keep repository active` ovat
   käytössä (ei harmaana).

3. **Kopioi ja muokkaa config.yaml.**
   ```bash
   cp config.example.yaml config.yaml
   ```
   Muokkaa lokaatio, tuulirajat ja suuntafiltteri omaan tarpeeseesi.
   Committaa `config.yaml` reposi - se ei sisällä salaisuuksia, koska
   tokenit viitataan `${...}`-muodossa.

4. **Lisää salaisuudet.** Mene **Settings → Secrets and variables →
   Actions → New repository secret** ja lisää tarvitsemasi:
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (Telegram-kanavalle)
   - `SMTP_USER`, `SMTP_PASSWORD` (email-kanavalle, jos käytössä)

5. **Testaa manuaalisesti.** Actions-välilehdellä valitse
   `Wind alert check` → **Run workflow**, jotta näet heti lokeista
   toimiiko haku ja lähetys ennen kuin jäät odottamaan ajastusta.

6. **Odota tuulta.** Workflow ajaa itsensä `*/10 4-21 * * *` (UTC)
   -aikataululla; `config.yaml`in `active_hours` suodattaa lopulliset
   ajat paikallisajassa.

## Kaksi sudenkuoppaa, jotka kannattaa tietää etukäteen

- **Fork + scheduled workflow = oletuksena pois päältä.** Katso kohta 2.
- **60 päivän inaktiivisuussääntö.** Jos repossasi ei tapahdu mitään
  (ei committeja) 60 päivään, GitHub sammuttaa ajastetut workflowt
  automaattisesti. `keep_alive.yml` tekee kerran kuussa triviaalin
  committin juuri tämän estämiseksi - älä poista sitä, vaikket
  käyttäisikään mitään muuta automaatiota.

## Miksi tila committoidaan repoon?

Jokainen Actions-ajo käynnistyy täysin tyhjästä ympäristöstä, joten
hystereesin muisti (oliko edellinen tila IDLE vai ALERTED) pitää
tallentaa jonnekin pysyvään paikkaan ajojen välillä. `run_alert.yml`
kirjoittaa `state/wingfoil_alert_state.json`-tiedoston takaisin repoon
jokaisen ajon lopussa. Tämä näkyy commit-historiassasi pienenä
automaattisena committina - se on odotettua eikä vaadi toimenpiteitä.
