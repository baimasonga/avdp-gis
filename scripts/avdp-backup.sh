#!/usr/bin/env bash
# Back up everything the AVDP GIS Portal needs into one archive.
#
#   scripts/avdp-backup.sh                 # -> backups/avdp-backup-<date>.tar.gz
#   scripts/avdp-backup.sh --no-secrets    # leave .env out (keep it elsewhere)
#
# The archive holds both PostgreSQL databases (pg_dump), the GeoServer data
# directory (layers, styles, security rules), uploaded files and thumbnails,
# and by default the .env file, whose passwords must match the data. Restore
# it on this or another computer with scripts/avdp-restore.sh.
#
# The stack must be running. The archive contains passwords unless
# --no-secrets is given: store it like a password.
set -euo pipefail
cd "$(dirname "$0")/.."

include_env=1
for arg in "$@"; do
    case "$arg" in
        --no-secrets) include_env=0 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

[ -f .env ] || { echo "No .env here: run this from the portal folder." >&2; exit 1; }
env_value() { grep "^$1=" .env | head -1 | cut -d= -f2-; }
DB=$(env_value GEONODE_DATABASE)
GEODB=$(env_value GEONODE_GEODATABASE)

for service in db django; do
    if [ -z "$(docker compose ps -q --status running "$service")" ]; then
        echo "The '$service' service is not running. Start the portal first: docker compose up -d" >&2
        exit 1
    fi
done

stamp=$(date +%Y%m%d-%H%M)
mkdir -p backups
work=$(mktemp -d "backups/.avdp-backup-$stamp.XXXX")
trap 'rm -rf "$work"' EXIT

echo "Dumping database $DB ..."
docker compose exec -T db pg_dump -U postgres -Fc "$DB" > "$work/geonode.dump"
echo "Dumping database $GEODB (layer data) ..."
docker compose exec -T db pg_dump -U postgres -Fc "$GEODB" > "$work/geodata.dump"
echo "Archiving the GeoServer data directory ..."
docker compose exec -T django tar czf - -C /geoserver_data/data \
    --exclude=./logs --exclude=./temp --exclude=./tmp . > "$work/gsdatadir.tgz"
echo "Archiving uploaded files and thumbnails ..."
docker compose exec -T django sh -c 'cd /mnt/volumes/statics && tar czf - $(ls -A | grep -vx static)' > "$work/statics.tgz"
if [ "$include_env" = 1 ]; then
    cp .env "$work/env"
fi

counts=$(docker compose exec -T django python manage.py shell -c "
from geonode.base.models import ResourceBase as R
from django.contrib.auth import get_user_model
print('resources=%d users=%d' % (R.objects.count(), get_user_model().objects.count()))" 2>/dev/null | tail -1)
{
    echo "AVDP GIS Portal backup"
    echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "git_commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "geonode_image=$(env_value GEONODE_BASE_IMAGE_VERSION)"
    echo "databases=$DB,$GEODB"
    echo "$counts"
    echo "includes_env=$include_env"
} > "$work/manifest.txt"

out="backups/avdp-backup-$stamp.tar.gz"
tar czf "$out" -C "$work" .
chmod 600 "$out"
echo
cat "$work/manifest.txt"
echo
echo "Backup written: $out ($(du -h "$out" | cut -f1))"
if [ "$include_env" = 1 ]; then
    echo "It contains the portal's passwords (.env): keep it somewhere safe."
else
    echo "No .env inside: restoring needs the .env this portal uses now."
fi
