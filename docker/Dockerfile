FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config.yaml ./config.yaml

# HUOM: aseta config.yamlissa state_path: "/data/wingfoil_alert_state.json"
# ja mountaa /data volyyminä (ks. docker-compose.yml), jotta hystereesin
# tila säilyy konttien uudelleenkäynnistysten yli.

CMD ["python", "src/main.py", "--config", "config.yaml"]
