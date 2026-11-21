#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installs Bert with Docker. Run in the repository folder:  ./install.sh
#
# Asks a few questions, creates the passwords for the database and the admin account,
# creates a local certificate, writes the .env files and starts everything.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

ask() {  # ask VARIABLE "Question" ["default"]
  local variable="$1" prompt="$2" default="${3:-}" answer
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " answer
    answer="${answer:-$default}"
  else
    read -r -p "$prompt: " answer
  fi
  [ -n "$answer" ] || fail "An answer is required."
  case "$answer" in *\'*) fail "Please do not use a single quote (') in the answer." ;; esac
  printf -v "$variable" '%s' "$answer"
}

ask_secret() {  # ask_secret VARIABLE "Question"
  local variable="$1" prompt="$2" answer
  read -r -s -p "$prompt: " answer
  echo
  [ -n "$answer" ] || fail "An answer is required."
  case "$answer" in *\'*) fail "Please do not use a single quote (') in the password." ;; esac
  printf -v "$variable" '%s' "$answer"
}

random_hex() {  # 32 random hex characters
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi
}

# ---------------------------------------------------------------- checks
[ -e .env ] && fail "There is already an installation (.env exists). Use './epaper update' to update, or remove .env to install again."
[ -f docker-compose.yml ] || fail "docker-compose.yml not found. Run this script in the repository folder."

if ! command -v docker >/dev/null 2>&1; then
  read -r -p "Docker is not installed. Install it now (needs internet and sudo)? [Y/n]: " answer
  case "${answer:-Y}" in
    [Yy]*)
      curl -fsSL https://get.docker.com | sudo sh
      sudo usermod -aG docker "$USER"
      echo "Docker is installed. Please log out and log in again (so that you are in the docker group), then run ./install.sh again."
      exit 0
      ;;
    *) fail "Docker is required." ;;
  esac
fi
docker info >/dev/null 2>&1 || fail "Cannot talk to Docker. Is it running, and are you in the 'docker' group? (sudo usermod -aG docker \$USER, then log in again)"

# ---------------------------------------------------------------- questions
bold "Bert installation"
echo "A few questions. The passwords for the database and the admin account are created automatically."
echo

ask SCHOOL_NUMBER "School number (VpMobil24 / Stundenplan24)"
ask VP_USER "VpMobil24 user name"
ask_secret VP_PASSWORD "VpMobil24 password (input is hidden)"

default_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
ask SERVER_IP "IP address of this server (it must never change: use a static IP or a DHCP reservation)" "$default_ip"
[[ "$SERVER_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || fail "'$SERVER_IP' is not an IPv4 address."
read -r -p "DNS name of this server (optional, Enter to skip): " SERVER_HOST
case "$SERVER_HOST" in *\'*|*' '*) fail "Invalid DNS name." ;; esac

default_tz="$(cat /etc/timezone 2>/dev/null || timedatectl show -p Timezone --value 2>/dev/null || echo Europe/Berlin)"
ask TIMEZONE "Time zone" "$default_tz"
ask ADMIN_USER_NAME "Name of the admin user" "admin"

# ---------------------------------------------------------------- configuration
bold "Creating the configuration..."
DB_PASSWORD="$(random_hex)"
DB_ROOT_PASSWORD="$(random_hex)"
PUBLIC_HOST="${SERVER_HOST:-$SERVER_IP}"
# Create the folders that are mounted into the containers ourselves. If they are missing, Docker
# creates them as root and the certificates could not be written.
mkdir -p certs/ca certs/public certs/server backups

# From here on a failed installation is removed again, so that ./install.sh can simply be run again.
INSTALL_DONE=0
cleanup_after_failure() {
  if [ "$INSTALL_DONE" != 1 ]; then
    echo
    echo "The installation did not finish. Removing the partial installation..."
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f .env .env.db
    echo "You can run ./install.sh again."
  fi
}
trap cleanup_after_failure EXIT

umask 077   # the files below contain secrets: readable for the owner only
cat > .env <<ENV
# Created by install.sh. Contains secrets: do not share it, do not commit it.
TZ=$TIMEZONE
SCHULNUMMER='$SCHOOL_NUMBER'
BENUTZERNAME='$VP_USER'
PASSWORT='$VP_PASSWORD'
DB_PASSWORD='$DB_PASSWORD'
ADMIN_USER='$ADMIN_USER_NAME'
PUBLIC_URL=https://$PUBLIC_HOST
ALL_ROOMS=[]
OTA_WINDOW=21:00-05:00
MIN_WAKE_GAP_SECONDS=900
WAKE_JITTER_SECONDS=120
WORKER_INTERVAL_SECONDS=300
ENV
cat > .env.db <<ENVDB
MARIADB_ROOT_PASSWORD=$DB_ROOT_PASSWORD
MARIADB_PASSWORD=$DB_PASSWORD
ENVDB
umask 022

# ---------------------------------------------------------------- image, certificate, admin password
bold "Building the Docker image (the first time this takes several minutes)..."
compose build api

bold "Creating the local certificate..."
[ -w certs/ca ] && [ -w certs/public ] && [ -w certs/server ] \
  || fail "The folder certs/ is not writable for your user (probably created by Docker as root). Remove it with: sudo rm -rf certs   and run ./install.sh again."
cert_args=(--out /certs-out --ip "$SERVER_IP")
[ -n "$SERVER_HOST" ] && cert_args+=(--host "$SERVER_HOST")
compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -v "$PWD/certs:/certs-out" api \
  python make_certs.py "${cert_args[@]}"

bold "Creating the admin password..."
credentials="$(compose run --rm --no-deps -T api python admin_passwd.py --generate)"
ADMIN_PASSWORD="$(printf '%s\n' "$credentials" | sed -n 's/^ADMIN_PASSWORD=//p')"
ADMIN_HASH_LINE="$(printf '%s\n' "$credentials" | grep '^ADMIN_PASSWORD_HASH=' || true)"
[ -n "$ADMIN_PASSWORD" ] && [ -n "$ADMIN_HASH_LINE" ] || fail "Could not create the admin password."
printf '%s\n' "$ADMIN_HASH_LINE" >> .env

# ---------------------------------------------------------------- start
bold "Starting Bert..."
compose up -d

echo -n "Waiting until the server answers"
ready=0
for _ in $(seq 1 90); do
  if curl -ksf "https://127.0.0.1/api/health" >/dev/null 2>&1; then ready=1; break; fi
  echo -n "."
  sleep 2
done
echo
if [ "$ready" != 1 ]; then
  INSTALL_DONE=1   # keep the containers and the logs for inspection
  fail "The server did not start. Look at the logs with:  docker compose logs
       To start over:  docker compose down -v && rm -f .env .env.db"
fi
INSTALL_DONE=1

compose exec -T api python seed_schedule.py || true   # default wake-up schedule

read -r -p "Install the command 'epaper' for easier use (needs sudo)? [Y/n]: " answer
case "${answer:-Y}" in
  [Yy]*) sudo ln -sf "$PWD/epaper" /usr/local/bin/epaper && echo "Done. Try:  epaper status" ;;
esac

# ---------------------------------------------------------------- summary
bold "Bert is running"
cat <<SUMMARY

  Admin page:     https://$PUBLIC_HOST/admin/
  Admin user:     $ADMIN_USER_NAME
  Admin password: $ADMIN_PASSWORD
  >>> Write the password down now. It is shown only once.
      A new one can be created with:  ./epaper admin-password

  Certificate:    The browser shows a warning until it trusts the local CA.
                  Download http://$SERVER_IP/pki/ca.crt and import it as a trusted authority
                  (or keep clicking through the warning).
                  The file is also here: certs/public/ca.crt

  Displays:       Add a display on the admin page (or: ./epaper add-device ROOM).
                  The display needs the CA, the server address and its id and token
                  over the serial console. The commands are shown when a display is created.

  Backups:        every night at 03:00 in the folder backups/ (the last 14 are kept)

  Important:      keep a copy of certs/ca/ca.key and of backups/ somewhere else.
                  Without the CA key a new server certificate cannot be created
                  and every display would need to be set up again.

SUMMARY