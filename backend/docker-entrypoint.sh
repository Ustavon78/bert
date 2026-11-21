#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# "api": update the database schema, then start the API server.
# Anything else is run as it is (worker, make_certs.py, devices_cli.py ...).
set -e

case "$1" in
  api)
    python init_db.py
    # --proxy-headers: the real client address comes from nginx (needed for the login limit).
    # The API port is only reachable inside the Docker network, so trusting nginx is safe.
    exec uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  *)
    exec "$@"
    ;;
esac