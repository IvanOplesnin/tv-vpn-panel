# TV VPN Panel FastAPI

FastAPI/WebSocket rewrite of the Raspberry TV VPN panel.

The panel keeps the existing routing model:

- VPN off for a device: traffic goes through the main table / `eth0`.
- VPN on for a device: the panel adds `ip rule from DEVICE_IP/32 lookup 200`.
- Table `200` is still selected by the existing backend switch logic: OpenVPN `tun0`, fallback sing-box `sbtun0`, or no VPN default route.


## Recommended deployment: Git + systemd

For this project, Git-based deployment is the preferred workflow. The Raspberry Pi keeps a normal git checkout in `/opt/tv-vpn-panel-fastapi`; updates are done with `git fetch/reset`, dependency refresh, and systemd restart.

This keeps runtime data outside the repository:

- app code: `/opt/tv-vpn-panel-fastapi`
- existing device state: `/opt/tv-vpn-panel/devices.json`
- ESP32 remote bindings: `/opt/tv-vpn-panel/remotes.json`
- local service settings/secrets: `/etc/default/tv-vpn-panel`
- systemd unit: `/etc/systemd/system/tv-vpn-panel.service`

### First install from Git

Create a GitHub repository from this project, then run on the Raspberry Pi:

```bash
sudo TVVPN_REPO_URL=https://github.com/<user>/<repo>.git   TVVPN_BRANCH=main   bash -c "$(curl -fsSL https://raw.githubusercontent.com/<user>/<repo>/main/scripts/install-from-git.sh)"
```

If you do not want to use `curl | bash`, clone manually and run the installer from the repo:

```bash
sudo apt-get update
sudo apt-get install -y git
sudo git clone https://github.com/<user>/<repo>.git /opt/tv-vpn-panel-fastapi
cd /opt/tv-vpn-panel-fastapi
sudo TVVPN_REPO_URL=https://github.com/<user>/<repo>.git ./scripts/install-from-git.sh
```

### Update from Git

After pushing changes to GitHub, update the Raspberry Pi with:

```bash
sudo /opt/tv-vpn-panel-fastapi/scripts/update-from-git.sh
```

If you changed repository URL or branch:

```bash
sudo TVVPN_REPO_URL=https://github.com/<user>/<repo>.git   TVVPN_BRANCH=main   /opt/tv-vpn-panel-fastapi/scripts/update-from-git.sh
```

### Local configuration

Do not edit files inside `/opt/tv-vpn-panel-fastapi` on the Raspberry Pi for local secrets or settings. Edit:

```bash
sudo nano /etc/default/tv-vpn-panel
sudo systemctl restart tv-vpn-panel.service
```

Example trusted LAN mode, no token required:

```ini
TVVPN_API_TOKEN=
TVVPN_REMOTES_FILE=/opt/tv-vpn-panel/remotes.json
```

Example token, only if you later expose the panel outside a trusted LAN:

```ini
TVVPN_API_TOKEN=change-me
```

## Why systemd first

Docker is possible, but the first production version should run directly under systemd on the Raspberry Pi.

Reason: this service changes host `ip rule` state. A Docker version needs `network_mode: host`, `NET_ADMIN`, bind mounts for `devices.json` and `dnsmasq.leases`, and careful handling of host networking. The systemd version is simpler and closer to the current Flask app.

## Local dry-run development

For local UI/API testing on a development machine, enable dry-run mode. In this mode the app still updates its JSON state, but skips commands that mutate host network state:

- `ip rule del ...`
- `ip rule add ...`
- backend switch script execution from `/api/backend/refresh`

Read-only probes like `ip rule` and `ip route show/get` may still run so the status page can display local runtime information.

```bash
TVVPN_DRY_RUN=true \
TVVPN_DEVICES_FILE=/tmp/tvvpn-devices.json \
TVVPN_REMOTES_FILE=/tmp/tvvpn-remotes.json \
TVVPN_LEASES_FILE=/tmp/tvvpn-empty-leases \
TVVPN_ENABLE_PERIODIC_SYNC=false \
TVVPN_API_TOKEN= \
.venv/bin/uvicorn tv_vpn_panel.main:app --reload --host 127.0.0.1 --port 8090
```

Open:

```text
http://127.0.0.1:8090/
http://127.0.0.1:8090/docs
```

## API

### Health

```bash
curl http://192.168.50.1:8090/api/health
```

### List devices

```bash
curl http://192.168.50.1:8090/api/devices
```

### Get one device state

```bash
curl http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c
```

### Enable VPN

```bash
curl -X POST http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c/vpn \
  -H 'Content-Type: application/json' \
  -d '{"vpn": true}'
```

### Disable VPN / direct traffic

```bash
curl -X POST http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c/vpn \
  -H 'Content-Type: application/json' \
  -d '{"vpn": false}'
```

### Toggle VPN

```bash
curl -X POST http://192.168.50.1:8090/api/devices/b8:87:6e:4a:cd:2c/toggle
```


### ESP32 remotes

List remotes:

```bash
curl http://192.168.50.1:8090/api/remotes
```

Add or update a remote binding:

```bash
curl -X POST http://192.168.50.1:8090/api/remotes \
  -H 'Content-Type: application/json' \
  -d '{"remote_id":"remote-bedroom-01","name":"Bedroom remote","target_mac":"b8:87:6e:4a:cd:2c"}'
```

Bind an existing remote to a TV:

```bash
curl -X POST http://192.168.50.1:8090/api/remotes/remote-bedroom-01/bind \
  -H 'Content-Type: application/json' \
  -d '{"target_mac":"b8:87:6e:4a:cd:2c"}'
```

Unbind a remote:

```bash
curl -X POST http://192.168.50.1:8090/api/remotes/remote-bedroom-01/unbind
```

Delete a remote:

```bash
curl -X DELETE http://192.168.50.1:8090/api/remotes/remote-bedroom-01
```

Remote bindings are stored separately from devices in `/opt/tv-vpn-panel/remotes.json`.

## WebSocket for ESP32

Connect:

```text
ws://192.168.50.1:8090/ws?remote_id=remote-bedroom-01
```

Optional first message:

```json
{
  "type": "hello",
  "remote_id": "remote-bedroom-01",
  "remote_name": "Bedroom remote",
  "remote_mac": "aa:bb:cc:dd:ee:ff",
  "target_mac": "b8:87:6e:4a:cd:2c",
  "firmware": "0.1.0"
}
```

Set VPN:

```json
{
  "type": "set_vpn",
  "vpn": true
}
```

Direct:

```json
{
  "type": "set_vpn",
  "vpn": false
}
```

Request state:

```json
{
  "type": "get_state"
}
```

## Install with systemd from a local copy

Git install is preferred. Local install still exists for testing before publishing the repository:

```bash
sudo systemctl stop tv-vpn-panel.service || true
cd tv-vpn-panel-fastapi
sudo ./scripts/install-systemd.sh
```

Open:

```text
http://192.168.50.1:8090/
```

or from the main LAN:

```text
http://192.168.1.25:8090/
```

## Optional API token

Edit `/etc/default/tv-vpn-panel` and add:

```ini
TVVPN_API_TOKEN=change-me
```

Then restart:

```bash
sudo systemctl restart tv-vpn-panel.service
```

HTTP clients can send one of:

```bash
-H 'X-API-Token: change-me'
# or
-H 'Authorization: Bearer change-me'
# or
?token=change-me
```

WebSocket:

```text
ws://192.168.50.1:8090/ws?remote_id=remote-bedroom-01&token=change-me
```

## Optional Docker run

Use only after the systemd version works.

```bash
cd deploy/docker
docker compose up -d --build
```

The compose file uses `network_mode: host` and `NET_ADMIN`, because the panel must change host routing rules.

## Environment variables

| Name | Default | Meaning |
|---|---:|---|
| `TVVPN_DEVICES_FILE` | `/opt/tv-vpn-panel/devices.json` | Persistent devices file |
| `TVVPN_REMOTES_FILE` | `/opt/tv-vpn-panel/remotes.json` | ESP32 remote bindings file |
| `TVVPN_LEASES_FILE` | `/var/lib/misc/dnsmasq.leases` | dnsmasq leases file |
| `TVVPN_TABLE_ID` | `200` | VPN policy routing table |
| `TVVPN_AP_INTERFACE` | `enx00e04c2a7a88` | TV/AP interface for route probes |
| `TVVPN_ROUTE_TEST_IP` | `8.8.8.8` | Target for route probe |
| `TVVPN_API_TOKEN` | empty | If set, API and WebSocket require token |
| `TVVPN_POLL_INTERVAL` | `10` | Periodic sync/broadcast interval in seconds |
| `TVVPN_ENABLE_PERIODIC_SYNC` | `true` | Enable background sync loop |
| `TVVPN_ALLOW_BACKEND_REFRESH` | `false` | Allow `/api/backend/refresh` to run backend switch script |
