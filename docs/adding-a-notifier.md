# Uuden ilmoituskanavan lisääminen

Ydinlogiikka (FMI-haku, hystereesi, viestin muodostus) ei tiedä mitään
Telegramista tai sähköpostista - se tuottaa vain `Alert`-olion
(`src/core/models.py`). Uuden kanavan lisääminen tarkoittaa yhden
uuden tiedoston kirjoittamista.

## 1. Toteuta `Notifier`-rajapinta

Luo `src/notifiers/oma_kanava.py`:

```python
from core.models import Alert
from .base import Notifier

class OmaKanavaNotifier(Notifier):
    def __init__(self, **options):
        ...  # lue tarvittavat asetukset

    def name(self) -> str:
        return "oma_kanava"

    def send(self, alert: Alert) -> bool:
        try:
            ...  # lähetä alert.title / alert.body
            return True
        except Exception as e:
            log.error("Lähetys epäonnistui: %s", e)
            return False
```

## 2. Rekisteröi se `src/main.py`:ssä

```python
NOTIFIER_FACTORIES = {
    ...
    "oma_kanava": lambda opts: OmaKanavaNotifier(**opts),
}
```

## 3. Lisää esimerkki `config.example.yaml`:aan

```yaml
    - type: oma_kanava
      enabled: false
      jokin_asetus: "${OMA_KANAVA_SECRET}"
```

## 4. Kirjoita testi

Notifiereille ei tarvitse testata oikeaa verkkokutsua - riittää, että
`send()` palauttaa oikean arvon onnistuessaan/epäonnistuessaan ja ettei
se kaadu odottamattomiin poikkeuksiin.

## Huomioita erityisesti epävirallisille rajapinnoille (esim. WhatsApp)

Jos kanavasi nojaa epäviralliseen tai kolmannen osapuolen rajapintaan
(esim. CallMeBot), merkitse se selvästi docstringissä ja READMEssä
"community-ylläpidetyksi": kerro käyttäjälle rehellisesti, että
rajapinta voi muuttua tai lakata toimimasta ilman erillistä varoitusta,
eikä ydinprojekti takaa sen toimivuutta pitkällä aikavälillä.
