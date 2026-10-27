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
   **Tärkeää:** aseta myös
   ```yaml
   state_path: "state/wingfoil_alert_state.json"
   ```
   oletuksen `~/.wingfoil_alert_state.json` tilalle - Actions-ajo käynnistyy
   joka kerta tyhjästä koneesta, joten koti-hakemistoon kirjoitettu tila
   katoaisi ajojen välissä ja hystereesi ei toimisi (näkisit ilmoituksen
   uudestaan joka ajolla). Committaa `config.yaml` reposi - se ei sisällä
   salaisuuksia, koska tokenit viitataan `${...}`-muodossa.

4. **Lisää salaisuudet.** Mene **Settings → Secrets and variables →
   Actions → New repository secret** ja lisää tarvitsemasi:
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (Telegram-kanavalle)
   - `SMTP_USER`, `SMTP_PASSWORD` (email-kanavalle, jos käytössä)

5. **Testaa manuaalisesti.** Actions-välilehdellä valitse
   `Wind alert check` → **Run workflow**, jotta näet heti lokeista
   toimiiko haku ja lähetys ennen kuin jäät odottamaan ajastusta.

6. **Odota tuulta.** `run_alert.yml`:ssä on ajastus `*/10 4-21 * * *`
   (UTC), mutta GitHub ajaa sen vain silloin kun sillä on kapasiteettia,
   ja käytännössä se tarkoittaa muutamaa ajoa päivässä (GitHubin omien
   ohjeiden mukaan ajastettuja ajoja voidaan viivästää tai pudottaa
   kokonaan, eikä sille ole takuuta). `config.yaml`in `active_hours`
   suodattaa lopulliset ajat paikallisajassa. Jos haluat ilmoitukset
   ajoissa, tee vaihe 7.

7. **Luotettava ajastus (suositeltu).** Ulkopuolinen ajastin käynnistää
   workflow'n 5 minuutin välein GitHubin "run workflow" -rajapinnalla.
   Näin tarkistus tehdään vähintään 15 minuutin välein myös silloin kun
   GitHubin oma ajastus jättää ajoja väliin. GitHubin ajastus jää
   varalle. **Tee tämä vasta kun tämä muutos on `main`-haarassa** -
   muuten GitHub hylkää kutsun virheellä 422.

   **7a. Token.** GitHub → **Settings → Developer settings → Personal
   access tokens → Fine-grained tokens → Generate new token**:
   - Nimi: `WindAlert pinger`
   - Expiration: **No expiration** (muuten ajastus lakkaa hiljaa, kun
     token vanhenee)
   - Repository access: **Only select repositories** → forkkisi
   - Permissions → Repository permissions → **Actions: Read and write**.
     Kaikki muut jäävät arvoon "No access". Metadata: Read-only tulee
     mukaan automaattisesti, eikä sitä voi muuttaa; se on oikein.
   - **Älä valitse** "Tokens (classic)", "All repositories" äläkä
     Contents- tai Workflows-oikeutta. Jos token vuotaa, sillä voi vain
     käynnistää, perua ja ottaa pois päältä tämän yhden repon
     workflow-ajoja; koodia sillä ei voi muuttaa. Jos epäilet vuotoa,
     poista token samasta paikasta.
   - Kopioi token talteen. Älä liitä sitä keskusteluun tai repoon.

   **7b. Apps Script.** Mene osoitteeseen script.google.com → **New
   project** → liitä tiedoston `tools/apps-script/pinger.gs` sisältö →
   **Project Settings → Script Properties** ja lisää:
   - `GITHUB_TOKEN` = vaiheessa 7a luotu token
   - `GITHUB_REPO` = `<käyttäjätunnuksesi>/WindAlert`

   Aja funktio `installTrigger` kerran ja hyväksy luvat. Lokin pitää
   näyttää `Trigger installed: ping every 5 min` ja sen jälkeen
   `Dispatched (HTTP 204)` (tai 200). Jos ajat sen klo 22-06 välillä
   Suomen aikaa, loki näyttää `Outside pinger hours - no dispatch`.
   Ajastin kutsuu GitHubia vain klo 06-22 Suomen aikaa. `installTrigger` voi ajaa uudestaan
   turvallisesti (se poistaa ensin vanhan ajastimen), ja `removeTrigger`
   sammuttaa pingerin.

   **7c. Tarkistus.** Actions-välilehdellä pitäisi muutaman minuutin
   sisällä näkyä ajo nimeltä **Wind alert check (pinger)**, ja sen
   jälkeen uusi noin 5 minuutin välein. Käsin käynnistetyt ajot näkyvät
   nimellä `(manual)` ja GitHubin oma ajastus nimellä `(schedule)`.

   **Virhetaulukko.** Apps Scriptin loki näyttää GitHubin vastauksen
   HTTP-koodin; Apps Script lähettää myös epäonnistuneista ajoista
   koosteen sähköpostiin kerran päivässä.

   | Loki | Syy |
   |---|---|
   | `HTTP 401` | token on kirjoitettu väärin tai poistettu |
   | `HTTP 403` "Resource not accessible by personal access token" | Actions-oikeus ei ole "Read and write" |
   | `HTTP 404` | forkkiä ei ole valittu tokeniin tai `GITHUB_REPO` on väärin |
   | `HTTP 422` "Unexpected inputs" | `run_alert.yml`:n muutos ei ole vielä `main`-haarassa |
   | `HTTP 422` "No ref found" | haaran nimi ei ole `main` |

   **Muu ajastin kuin Apps Script.** Mikä tahansa palvelu, joka osaa
   lähettää tämän yhden POST-kutsun 5 minuutin välein (esim.
   cron-job.org), käy:
   ```
   POST https://api.github.com/repos/<käyttäjä>/WindAlert/actions/workflows/run_alert.yml/dispatches
   Authorization: Bearer <token>
   Accept: application/vnd.github+json
   X-GitHub-Api-Version: 2022-11-28
   Content-Type: application/json

   {"ref":"main","inputs":{"trigger":"pinger"}}
   ```

## Kolme sudenkuoppaa, jotka kannattaa tietää etukäteen

- **Fork + scheduled workflow = oletuksena pois päältä.** Katso kohta 2.
- **60 päivän inaktiivisuussääntö.** Jos repossasi ei tapahdu mitään
  (ei committeja) 60 päivään, GitHub sammuttaa ajastetut workflowt
  automaattisesti. `keep_alive.yml` tekee kerran kuussa triviaalin
  committin juuri tämän estämiseksi - älä poista sitä, vaikket
  käyttäisikään mitään muuta automaatiota.
- **Forkin pitää pysyä julkisena.** Julkisilla repoilla Actions-minuutit
  ovat ilmaisia. Yksityisellä forkilla 5 minuutin tarkistus kuluttaisi
  noin 192 laskutettavaa minuuttia päivässä (jokainen ajo pyöristyy
  minuuttiin), mikä ylittää yksityisen repon ilmaiskiintiön muutamassa
  päivässä.

## Miksi tila committoidaan repoon?

Jokainen Actions-ajo käynnistyy täysin tyhjästä ympäristöstä, joten
hystereesin muisti (oliko edellinen tila IDLE vai ALERTED) pitää
tallentaa jonnekin pysyvään paikkaan ajojen välillä. `run_alert.yml`
kirjoittaa `state/wingfoil_alert_state.json`-tiedoston takaisin repoon
jokaisen ajon lopussa. Tämä näkyy commit-historiassasi pienenä
automaattisena committina - se on odotettua eikä vaadi toimenpiteitä.
