# Déploiement sur un VPS Debian/Ubuntu

```bash
# 1. Paquets système
sudo apt install -y postgresql xvfb tesseract-ocr tesseract-ocr-fra ffmpeg python3-venv caddy
sudo useradd -r -m -s /usr/sbin/nologin manifestations

# 2. Code + dépendances (dans /opt/manifestations-bo)
sudo -u manifestations python3 -m venv /opt/manifestations-bo/.venv
sudo -u manifestations /opt/manifestations-bo/.venv/bin/pip install -r /opt/manifestations-bo/requirements.txt
sudo -u manifestations /opt/manifestations-bo/.venv/bin/playwright install --with-deps chromium

# 3. Base
sudo -u postgres createuser manifestations && sudo -u postgres createdb -O manifestations manifestations
psql "$DATABASE_URL" -f /opt/manifestations-bo/schema.sql
#   (base existante avec l'ancien schéma ? voir scripts/reset_events_schema.sql — DESTRUCTIF)

# 4. Configuration : cp .env.example .env ; chmod 600 ; renseigner
#    DATABASE_URL, API_TOKEN (openssl rand -hex 32), PERPLEXITY_API_KEY, CORS_ORIGINS, TIKTOK_QUERIES

# 5. Services
sudo cp deploy/manifestations-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now manifestations-api manifestations-worker manifestations-discover.timer

# 6. HTTPS : adapter deploy/Caddyfile puis le copier dans /etc/caddy/Caddyfile ; systemctl reload caddy
```

Vérifications : `curl http://127.0.0.1:8000/health`, `journalctl -u manifestations-worker -f`,
`python -m app.worker enqueue-tiktok "test"` pour lancer une découverte à la main.
