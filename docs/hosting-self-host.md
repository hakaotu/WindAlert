# Hostaus: oma laite (Raspberry Pi, kotipalvelin, VPS)

Sopii, jos sinulla on jo laite, joka on päällä ympäri vuorokauden.
Robustein vaihtoehto tilan pysyvyyden kannalta, koska `state.json` säilyy
levyllä normaalisti ajojen välillä ilman erillisiä temppuja.

## Vaihtoehto A: cron (yksinkertaisin)

```bash
git clone https://github.com/<sinun-tunnuksesi>/WindAlert.git
cd WindAlert
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # muokkaa
cp .env.example .env                 # täytä salaisuudet
```

Lisää crontabiin (`crontab -e`):

```cron
*/10 6-22 * * * cd /home/pi/WindAlert && set -a && . .env && set +a && .venv/bin/python src/main.py --config config.yaml >> /var/log/wingfoil_alert.log 2>&1
```

## Vaihtoehto B: systemd (suositeltu palvelimille)

`/etc/systemd/system/wingfoil-alert.service`:

```ini
[Unit]
Description=Wingfoil wind alert - single run
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/pi/WindAlert
EnvironmentFile=/home/pi/WindAlert/.env
ExecStart=/home/pi/WindAlert/.venv/bin/python src/main.py --config config.yaml
```

`/etc/systemd/system/wingfoil-alert.timer`:

```ini
[Unit]
Description=Aja wingfoil-alert 10 min välein klo 6-22

[Timer]
OnCalendar=*-*-* 06..22:00/10:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wingfoil-alert.timer
journalctl -u wingfoil-alert -f   # lokien seuranta
```

## Vaihtoehto C: Docker

```bash
cp config.example.yaml config.yaml   # muokkaa, aseta:
# state_path: "/data/wingfoil_alert_state.json"
cp .env.example .env

cd docker
docker compose build
docker compose run --rm wingfoil-alert   # yksi testiajo
```

Ajastukseen suosittelemme host-koneen cronia (`docker compose run --rm ...`
komennolla), koska se on yksinkertaisin ja läpinäkyvin tapa - kontti
itsessään ei tarvitse pyöriä jatkuvasti.

## Molemmissa vaihtoehdoissa

- Pidä `.env` tiedosto-oikeuksiltaan yksityisenä: `chmod 600 .env`
- Testaa aina yksi manuaalinen ajo (`python src/main.py --config config.yaml`)
  ennen ajastuksen käyttöönottoa, jotta näet virheet suoraan terminaalissa.
