# Running Bert with Docker

Everything runs in five containers that are started and kept alive by Docker:

| Container | Task |
|---|---|
| `db` | MariaDB. No port to the outside, only the other containers can reach it. |
| `api` | The API for the displays and the admin page. Applies the database migrations on start. |
| `worker` | Runs the scraper and then the renderer in a loop. |
| `web` | nginx: HTTPS, the admin page, forwards `/api/` to the API. The only container with open ports (80, 443). |
| `backup` | Dumps the database every night at 03:00 into `backups/`, keeps the last 14. |

## Requirements

- A Raspberry Pi 4 or 5 (64-bit OS) or any Linux machine, with internet access.
- A fixed IP address (static or DHCP reservation). The server certificate and every display know it.
- Recommended: a USB SSD instead of the SD card (the database writes a lot).

## Install

```bash
git clone <repository> bert && cd bert
chmod +x install.sh epaper          # needed if the files were downloaded
./install.sh
```

The script asks for the school number, the VpMobil24 login, the IP address and the time zone. The
database and admin passwords are created automatically, a local certificate is created and
everything is started. The admin password is shown once at the end.

Afterwards open `https://<ip>/admin/`. The browser warns until it trusts the local CA: download
`http://<ip>/pki/ca.crt` and import it as a trusted authority.

## Adding a display

On the admin page, or `./epaper add-device ROOM`. A display needs its WiFi, the server address, the
CA certificate, its id and its token. They are typed into the serial console of the display (press
reset, then type within 3 seconds); the commands are shown when the display is created:

```
set ssid <WiFi name>
set pass <WiFi password>
set server https://<ip>
set ca <content of certs/public/ca.b64>
set id <id>
set token <token>
start
```

## Daily use

| Command | Meaning |
|---|---|
| `./epaper status` | containers, server answer, latest backup, disk space |
| `./epaper logs [api\|worker\|web\|db\|backup]` | follow the logs |
| `./epaper update` | backup, `git pull`, rebuild, restart (database migrations run automatically) |
| `./epaper backup` / `restore FILE` | database backup now / restore |
| `./epaper devices list` | displays, firmware, last contact |
| `./epaper firmware-add FILE BOARD VERSION` | make a firmware file available, then `./epaper devices fw all VERSION` |
| `./epaper teachers-import FILE.csv` | teacher names (`abbreviation;name`) |
| `./epaper admin-password` | new admin password |
| `./epaper certs --ip ADDRESS` | new server certificate (after an IP change) |

After a power failure everything starts again by itself (`restart: unless-stopped`).

## Certificates

`install.sh` creates a local CA and a server certificate (`certs/`):

- `certs/ca/ca.key` is the private key of the CA. It is not mounted into any container. **Keep a copy
  somewhere else.** Without it no new server certificate can be created.
- `certs/public/ca.crt` goes into the browsers, `certs/public/ca.b64` (one line) into the displays.
- The displays only trust this CA. If the IP address changes, run `./epaper certs --ip NEW-ADDRESS`:
  the CA stays the same, so the displays keep working.
- The certificates are valid from 2020 to 2060 on purpose: a display has no reliable clock and would
  reject a certificate that starts "today". Only Bert trusts this CA.

## Security notes

- Only ports 80 (redirect and CA download) and 443 are open. The database and the API are not reachable
  from the network.
- `.env` and `.env.db` contain secrets (mode 600). Do not commit them (see `gitignore-additions.txt`).
- The admin API asks for the login itself, nginx adds HTTPS and request limits. Optionally restrict
  `/admin/` to the admin PC in `web/nginx.conf`.
- Keep the OS updated (`unattended-upgrades` on Debian/Raspberry Pi OS).

## Troubleshooting

- **The server does not answer:** `./epaper status`, then `./epaper logs api`.
- **502 Bad Gateway:** the API container is not (yet) healthy: `./epaper logs api`.
- **A display cannot connect:** is the server address in `set server` the IP of the certificate? Was `set ca`
  entered? Is the display in the same WiFi? The serial monitor shows the reason.
- **Admin login blocked (429):** too many wrong passwords from one address, wait 10 minutes.