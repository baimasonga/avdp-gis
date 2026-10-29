#!/usr/bin/env bash
# Run a temporary AVDP GIS Portal demo inside a GitHub Codespace.
#
#   scripts/codespace-demo.sh setup   # create .env for this codespace's public URL
#   scripts/codespace-demo.sh start   # build (first time), start, wait until healthy
#   scripts/codespace-demo.sh seed    # load demo data once (real package if present)
#   scripts/codespace-demo.sh all     # setup + start + seed (used by the dev container)
#   scripts/codespace-demo.sh info    # print the portal URL and how to sign in
#
# Codespaces publishes port 80 at https://<codespace>-80.<forwarding domain>.
# HTTPS is terminated by GitHub, so nginx itself serves plain HTTP; SITEURL and
# the GeoServer URLs use the public https:// address. Outside Codespaces you can
# set DEMO_HOST yourself (e.g. for a rehearsal behind your own TLS proxy).
#
# This is for short-lived demonstrations, not production (see docs/CODESPACES.md).
set -euo pipefail
cd "$(dirname "$0")/.."

PACKAGE=data/demo/AVDP_Synthetic_GIS_Sample_Package.zip
SEED_MARKER=.local/demo-seeded

demo_host() {
    if [ -n "${DEMO_HOST:-}" ]; then
        echo "$DEMO_HOST"
    elif [ -n "${CODESPACE_NAME:-}" ] && [ -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
        echo "${CODESPACE_NAME}-80.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
    else
        echo "Not in a codespace: set DEMO_HOST to the public host name." >&2
        exit 1
    fi
}

setup() {
    local host
    host=$(demo_host)
    if [ -f .env ] && grep -q "^SITEURL=https://${host}/$" .env; then
        echo ".env already configured for https://${host}/"
        return
    fi
    if [ -f .env ]; then
        # Keep the existing secrets (they must match the database volumes);
        # only move the public host name.
        local old
        old=$(grep '^HTTP_HOST=' .env | cut -d= -f2)
        cp .env ".env.backup.$(date +%s)"
        sed -i -e "s#${old}#${host}#g" .env
        echo "Updated .env from ${old} to https://${host}/ (backup kept)."
        return
    fi
    # Generate random secrets for an HTTP site on this host, then switch the
    # public URLs to https:// (TLS is provided by the Codespaces proxy).
    python3 create-envfile.py --noinput --env_type=prod --hostname="$host" --email="demo@example.invalid" >/dev/null
    sed -i \
        -e "s#http://${host}#https://${host}#g" \
        -e "s#^HTTP_BIND=.*#HTTP_BIND=127.0.0.1#" \
        -e "s#^GEOSERVER_CORS_ALLOWED_ORIGINS=.*#GEOSERVER_CORS_ALLOWED_ORIGINS=https://${host}#" \
        .env
    # Smaller GeoServer heap: the codespace also runs PostGIS, Django and Celery.
    sed -i -e 's#-Xms1G -Xmx2G#-Xms512m -Xmx2G#' .env
    chmod 600 .env
    echo "Created .env for https://${host}/"
}

wait_healthy() {
    local deadline=$((SECONDS + 1200))
    echo "Waiting for all services to become healthy (first start takes several minutes)..."
    while [ $SECONDS -lt $deadline ]; do
        local states
        states=$(docker compose ps --format '{{.Service}}:{{.Health}}')
        if [ -n "$states" ] && ! echo "$states" | grep -qv ':healthy'; then
            echo "All services healthy."
            return 0
        fi
        sleep 10
    done
    docker compose ps
    echo "Services did not become healthy in time; see: docker compose logs django geoserver" >&2
    return 1
}

wait_django() {
    # Django's first start (migrations, static files) can take a long time.
    # A container can recover from "unhealthy", so keep waiting until it is
    # healthy or the deadline passes, instead of giving up on the first failure.
    local deadline=$((SECONDS + 1800)) state=""
    echo "Waiting for Django to finish its first start (migrations, static files)..."
    while [ $SECONDS -lt $deadline ]; do
        state=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q django)" 2>/dev/null || true)
        if [ "$state" = "healthy" ]; then
            echo "Django is healthy."
            return 0
        fi
        if [ -z "$(docker compose ps -q --status running django)" ]; then
            echo "The django container is not running:" >&2
            docker compose logs --tail 60 django >&2
            return 1
        fi
        sleep 15
    done
    echo "Django did not become healthy in time (last state: ${state:-unknown})." >&2
    docker compose logs --tail 60 django >&2
    return 1
}

start() {
    [ -f .env ] || setup
    docker compose build
    # Start Django and its dependencies first, wait for it, then the rest.
    docker compose up -d django || true
    wait_django
    docker compose up -d
    wait_healthy
}

seed() {
    mkdir -p .local
    if [ -f "$SEED_MARKER" ]; then
        echo "Demo data already loaded ($(cat "$SEED_MARKER")). Remove $SEED_MARKER to reload."
        return
    fi
    local source
    if [ -f "$PACKAGE" ]; then
        source=/usr/src/project/$PACKAGE
        echo "Importing the AVDP demonstration package."
    else
        echo "AVDP_Synthetic_GIS_Sample_Package.zip not found in data/demo/."
        echo "Loading the generated TEST FIXTURE instead (labelled synthetic; not AVDP data)."
        docker compose exec -T django python -m geonode_project.tests.make_test_package /tmp/avdp_test_fixture.zip
        source=/tmp/avdp_test_fixture.zip
    fi
    docker compose exec -T django python manage.py avdp_import_demo "$source"
    echo "$(basename "$source") $(date -u +%Y-%m-%dT%H:%MZ)" > "$SEED_MARKER"
}

info() {
    local host
    host=$(demo_host)
    cat <<EOF

AVDP GIS Portal demo
  URL:      https://${host}/
  Sign in:  user "$(grep '^ADMIN_USERNAME=' .env | cut -d= -f2)"; password: run  grep '^ADMIN_PASSWORD=' .env
  Sharing:  port 80 is private (your GitHub account only) unless you change its
            visibility in the Ports panel. Demo resources are private to the
            AVDP groups unless imported with --public.
  Stop:     the codespace stops after its idle timeout; data persists until the
            codespace is deleted.
EOF
}

case "${1:-all}" in
    setup) setup ;;
    start) start ;;
    seed) seed ;;
    info) info ;;
    all) setup; start; seed; info ;;
    *) echo "usage: $0 {setup|start|seed|info|all}" >&2; exit 2 ;;
esac
