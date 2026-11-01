#!/usr/bin/env bash
# Restore an AVDP GIS Portal backup made with scripts/avdp-backup.sh.
#
#   scripts/avdp-restore.sh backups/avdp-backup-20261101-2100.tar.gz
#   scripts/avdp-restore.sh <archive> --yes      # skip the confirmation
#
# REPLACES ALL PORTAL DATA ON THIS COMPUTER (databases, layers, uploads,
# accounts) with the backup's. Use it to move the portal to another
# computer: clone the repository, build the images (docker compose build),
# copy the archive into the folder and run this script.
#
# If the archive contains .env, it becomes this portal's .env (the current
# one is kept as .env.before-restore-<date>). Otherwise the current .env is
# used and must be the one the backup was made with.
set -euo pipefail
cd "$(dirname "$0")/.."

archive="" assume_yes=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) assume_yes=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) archive="$arg" ;;
    esac
done
[ -n "$archive" ] && [ -f "$archive" ] || { echo "Usage: $0 <backup .tar.gz> [--yes]" >&2; exit 2; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar xzf "$archive" -C "$work"
for f in manifest.txt geonode.dump geodata.dump gsdatadir.tgz statics.tgz; do
    [ -f "$work/$f" ] || { echo "Not an AVDP backup (missing $f)." >&2; exit 1; }
done
echo "Backup to restore:"
sed 's/^/  /' "$work/manifest.txt"
echo

if [ -f "$work/env" ]; then
    env_source="the backup"
elif [ -f .env ]; then
    env_source="this folder (the backup has none)"
else
    echo "The backup has no .env and this folder has none either; cannot restore." >&2
    exit 1
fi
if [ "$assume_yes" != 1 ]; then
    echo "This deletes ALL current portal data on this computer and replaces it with the backup."
    echo "Settings (.env) will come from $env_source."
    read -r -p "Type RESTORE to continue: " answer
    [ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }
fi

if [ -f "$work/env" ]; then
    if [ -f .env ] && ! cmp -s .env "$work/env"; then
        cp .env ".env.before-restore-$(date +%Y%m%d-%H%M)"
    fi
    cp "$work/env" .env
    chmod 600 .env
fi
env_value() { grep "^$1=" .env | head -1 | cut -d= -f2-; }
DB=$(env_value GEONODE_DATABASE)
DB_USER=$(env_value GEONODE_DATABASE_USER)
GEODB=$(env_value GEONODE_GEODATABASE)
GEODB_USER=$(env_value GEONODE_GEODATABASE_USER)

echo "Stopping the portal and removing its current data volumes ..."
docker compose down -v --remove-orphans

echo "Starting the database ..."
docker compose up -d db
for _ in $(seq 1 90); do
    if docker compose exec -T db psql -U postgres -Atc "SELECT 1 FROM pg_roles WHERE rolname='$GEODB_USER'" 2>/dev/null | grep -q 1 \
        && docker compose exec -T db psql -U postgres -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$GEODB"; then
        break
    fi
    sleep 5
done

restore_db() {  # name owner dumpfile
    local name=$1 owner=$2 dump=$3
    echo "Restoring database $name ..."
    docker compose exec -T db psql -U postgres -q -c "DROP DATABASE IF EXISTS \"$name\";" -c "CREATE DATABASE \"$name\" OWNER \"$owner\";"
    docker compose exec -T db psql -U postgres -q -d "$name" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
    docker compose cp "$dump" "db:/tmp/restore.dump"
    # Extensions (and PostGIS's own spatial_ref_sys rows) come from CREATE EXTENSION
    # above, as superuser; everything else is restored as the database owner.
    docker compose exec -T db sh -c "pg_restore -l /tmp/restore.dump | grep -v -e ' EXTENSION ' -e ' spatial_ref_sys ' > /tmp/restore.list"
    docker compose exec -T db pg_restore -U postgres --no-owner --role="$owner" -d "$name" \
        -L /tmp/restore.list /tmp/restore.dump
    docker compose exec -T db rm -f /tmp/restore.dump /tmp/restore.list
}
restore_db "$DB" "$DB_USER" "$work/geonode.dump"
restore_db "$GEODB" "$GEODB_USER" "$work/geodata.dump"

echo "Restoring the GeoServer data directory and uploaded files ..."
docker compose run --rm --no-deps -T --entrypoint sh django -c \
    'tar xzf - -C /geoserver_data/data' < "$work/gsdatadir.tgz"
docker compose run --rm --no-deps -T --entrypoint sh django -c \
    'tar xzf - -C /mnt/volumes/statics' < "$work/statics.tgz"

echo "Starting the whole portal (first start takes several minutes) ..."
docker compose up -d
deadline=$((SECONDS + 1800))
while [ $SECONDS -lt $deadline ]; do
    states=$(docker compose ps --format '{{.Service}}:{{.Health}}')
    if [ -n "$states" ] && ! echo "$states" | grep -qv ':healthy'; then
        break
    fi
    sleep 15
done
docker compose ps --format 'table {{.Service}}\t{{.Health}}'
counts=$(docker compose exec -T django python manage.py shell -c "
from geonode.base.models import ResourceBase as R
from django.contrib.auth import get_user_model
print('resources=%d users=%d' % (R.objects.count(), get_user_model().objects.count()))" 2>/dev/null | tail -1)
echo
echo "Restored: $counts (backup said: $(grep -E '^resources=' "$work/manifest.txt"))"
echo "Open the portal at $(env_value SITEURL)"
