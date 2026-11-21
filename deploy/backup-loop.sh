#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs in the "backup" container: dumps the database once at start and then every day at
# BACKUP_HOUR, and deletes dumps older than BACKUP_KEEP_DAYS.
set -uo pipefail

KEEP="${BACKUP_KEEP_DAYS:-14}"
HOUR="${BACKUP_HOUR:-3}"

backup() {
  local file="/backups/epaper-$(date +%Y-%m-%d_%H%M).sql.gz"
  if MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb-dump --single-transaction --routines -h db -u root epaper | gzip > "$file.tmp"; then
    mv "$file.tmp" "$file"
    echo "backup written: $file"
  else
    rm -f "$file.tmp"
    echo "backup FAILED" >&2
  fi
  find /backups -name 'epaper-*.sql.gz' -mtime +"$KEEP" -delete
}

backup
while true; do
  now=$(date +%s)
  next=$(date -d "today ${HOUR}:00" +%s)
  if [ "$next" -le "$now" ]; then
    next=$(date -d "tomorrow ${HOUR}:00" +%s)
  fi
  sleep $((next - now))
  backup
done