# Cloudflare Tunnel runbook for dialekt-cloud

This runbook deploys `dialekt-cloud` on a founder-owned Linux server
behind a Cloudflare Tunnel. No inbound ports are opened. TLS is
terminated at Cloudflare's edge; your home router stays behind NAT.

Outcome after completing this runbook:

- `https://api.dias.now/health`          → FastAPI (cloud service)
- `https://admin.dias.now/admin/ui/login` → founder admin panel
- `https://dialekt.dias.now/`             → landing page

**Runtime cost:** $0. **One-time effort:** ~20 minutes.

---

## Prerequisites (verify before starting)

1. Linux server (Ubuntu 22.04 / Debian 12 / Fedora 38+) with:
   - `docker` and `docker compose v2` installed
   - 2+ GB free RAM
   - outbound HTTPS to `api.cloudflare.com`, `github.com`
   - a user in the `docker` group (`groups $USER` shows `docker`)
2. Cloudflare account (free plan is fine)
3. Domain `dias.now` added to that Cloudflare account, DNS active
4. Host-level DNS records **absent** for `api.dias.now`, `admin.dias.now`,
   `dialekt.dias.now` — the tunnel creates them.

Optional (recommended for pilots): a founder-owned SMTP account to send
license and invite emails. Without it, emails are logged but not sent.

---

## 1 · Prepare `.env`

On the server, in the repo clone:

```bash
cd ~/projects/dialekt/dialekt-cloud
cp .env.example .env
```

Fill in **every** variable in `.env`. Critical ones:

```
DATABASE_URL=postgresql://dialekt_cloud:CHANGE_ME@db:5432/dialekt_cloud
POSTGRES_PASSWORD=CHANGE_ME                      # must match DATABASE_URL password
DIALEKT_ADMIN_KEY=<64-char hex, generate with: python -c "import secrets; print(secrets.token_hex(32))">
JWT_SECRET=<another 64-char secret, same method>

SMTP_HOST=mail.your-provider.com
SMTP_PORT=587
SMTP_USER=noreply@your-domain.com
SMTP_PASSWORD=app-password-or-similar
SMTP_FROM="dias.now <noreply@your-domain.com>"
SMTP_TLS=true

APP_URL=https://api.dias.now
ADMIN_URL=https://admin.dias.now
LANDING_URL=https://dialekt.dias.now

INVOICE_SELLER_NAME="ИП Ваша Фамилия Имя"
INVOICE_SELLER_BIN=123456789012
INVOICE_SELLER_IBAN="KZ00 0000 0000 0000 0000"
INVOICE_SELLER_BANK="АО Kaspi Bank"
INVOICE_SELLER_BIK=CASPKZKA
INVOICE_SELLER_ADDRESS="г. Алматы, ул. ..."
INVOICE_SELLER_PHONE="+7 ..."
INVOICE_SELLER_EMAIL=hello@your-domain.com

ENV=production
LOG_LEVEL=INFO
```

If ИП/ТОО isn't registered yet, leave the INVOICE_* fields as placeholders —
nothing in the auth/license path uses them, only invoice PDF generation
does. Attempting to generate an invoice without real data produces a PDF
with placeholder text, which is fine for the first 1-2 pilots (you'll
invoice them manually anyway).

---

## 2 · Bring the stack up

```bash
cd ~/projects/dialekt/dialekt-cloud
docker compose pull           # pulls postgres:16-alpine + nginx:1.27-alpine
docker compose build api      # local build of FastAPI image
docker compose up -d          # start db + api + landing
docker compose ps             # should show 3 services, all "healthy" after ~15s
```

Verify locally from the same server:

```bash
curl -sS http://127.0.0.1:8080/health
# {"status":"ok","service":"dialekt-cloud","version":"0.9.0","uptime_seconds":...}

curl -sS -I http://127.0.0.1:8081/   # landing nginx
# HTTP/1.1 200 OK

curl -sS -I http://127.0.0.1:8080/admin/ui/login
# HTTP/1.1 200 OK
```

If any of these fails, check `docker compose logs -f api`.

---

## 3 · Install cloudflared on the host

```bash
# Debian/Ubuntu:
curl -L https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared

# Fedora/Arch: use the `cloudflared` binary download from
# https://github.com/cloudflare/cloudflared/releases
```

---

## 4 · Authenticate + create the tunnel

**You'll need a browser** for the first step — cloudflared opens a URL
you must paste into a browser logged into the Cloudflare account that
owns `dias.now`.

```bash
cloudflared tunnel login
# → follow the URL shown, approve in the browser, return to terminal
```

Create a named tunnel:

```bash
cloudflared tunnel create dialekt-cloud
# → prints the tunnel UUID, e.g.
#   Created tunnel dialekt-cloud with id c3a4... and stored it at
#   ~/.cloudflared/c3a4....json
```

Record that UUID — you'll reference it as `<TUNNEL_UUID>` below.

---

## 5 · Configure the tunnel

```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/<TUNNEL_UUID>.json /etc/cloudflared/
sudo tee /etc/cloudflared/config.yml <<EOF
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: api.dias.now
    service: http://localhost:8080
  - hostname: admin.dias.now
    service: http://localhost:8080
  - hostname: dialekt.dias.now
    service: http://localhost:8081
  - service: http_status:404
EOF
```

Map the DNS records to the tunnel (cloudflared does this via the API):

```bash
cloudflared tunnel route dns dialekt-cloud api.dias.now
cloudflared tunnel route dns dialekt-cloud admin.dias.now
cloudflared tunnel route dns dialekt-cloud dialekt.dias.now
```

Each command should print a success line. Verify from the Cloudflare
dashboard → DNS: three new CNAMEs, each pointing at
`<TUNNEL_UUID>.cfargotunnel.com`.

---

## 6 · Run the tunnel as a systemd service

```bash
sudo cloudflared service install
# → enables + starts cloudflared.service
systemctl status cloudflared
# → "active (running)" with recent logs
```

The service restarts on reboot.

---

## 7 · Verify from an external network

From a **different** machine (phone hotspot, coffee shop, or the `curl`
below run from anywhere outside your LAN):

```bash
curl -sS https://api.dias.now/health
# {"status":"ok","service":"dialekt-cloud","version":"0.9.0","uptime_seconds":...}

curl -sS -I https://admin.dias.now/admin/ui/login | head -1
# HTTP/2 200

curl -sS https://dialekt.dias.now/ | head -1
# <!DOCTYPE html>
```

All three responding with 200 + valid Cloudflare TLS → **Blocker 2 is CLOSED**.

---

## Pointing desktop apps at this cloud

Every fresh install uses `https://api.dias.now` automatically — the value
comes from `DEFAULT_SETTINGS["cloud_api_url"]` in `python/server.py`.

Pilots with an unusual network environment can override it:

- Settings → Cloud → enter a different URL (e.g. `http://localhost:8080`
  for dev), save. The desktop caches the new URL until change.
- Or edit `~/.dialekt/config.json` and set `cloud_api_url`.

---

## Troubleshooting

**`cloudflared tunnel login` prints a URL but nothing loads in browser:**
Cloudflare sometimes blocks the OAuth flow in private-browsing mode. Use
a normal browser window logged into the correct Cloudflare account.

**`docker compose up` says "permission denied" on `/var/run/docker.sock`:**
`sudo usermod -aG docker $USER && newgrp docker`.

**`api.dias.now` returns 502 `no available service`:**
The tunnel is up but can't reach `127.0.0.1:8080` from where cloudflared
runs. Either:
- cloudflared is inside Docker and 127.0.0.1 means its own container —
  install cloudflared as a host service, OR
- the FastAPI container isn't listening on `127.0.0.1:8080` — check
  `docker compose ps` and `docker compose logs api`.

**`curl https://api.dias.now/health` returns Cloudflare 1033 error:**
The DNS route didn't take. Re-run `cloudflared tunnel route dns ...` and
check the Cloudflare DNS dashboard.

**Cold-start failures on first boot:**
Postgres takes ~10s to come ready on a fresh volume. The api container's
`depends_on: condition: service_healthy` handles this, but if you see
connection errors in the api logs, `docker compose restart api` once.

---

## Backup / recovery

Data lives in two Docker volumes:

- `dialekt-cloud_pgdata` — Postgres data (tenants, licenses, invites)
- `dialekt-cloud_invoices` — generated invoice PDFs

Back up weekly:

```bash
docker run --rm -v dialekt-cloud_pgdata:/data -v $(pwd):/backup \
  alpine tar czf /backup/pgdata-$(date +%F).tgz -C /data .
```

Restore:

```bash
docker compose down
docker volume create dialekt-cloud_pgdata
docker run --rm -v dialekt-cloud_pgdata:/data -v $(pwd):/backup \
  alpine tar xzf /backup/pgdata-2026-05-01.tgz -C /data
docker compose up -d
```

---

## Updating

```bash
cd ~/projects/dialekt
git pull
cd dialekt-cloud
docker compose build api
docker compose up -d api        # restart with new image
docker compose logs -f api      # watch for errors
```

Migrations run automatically on api startup (see `src/dialekt_cloud/db.py`).
