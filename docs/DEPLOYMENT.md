# Deployment

This stack has been verified only as a **local development deployment**
(HTTP on `127.0.0.1`). Nothing below has been exercised on a public server;
treat it as the plan for a first staging deployment, and repeat the checks in
HANDOFF.md there before going live.

## Prerequisites

- A Linux server (Ubuntu 24.04 LTS or similar) with Docker Engine + Compose v2.
- Sizing for a small agency portal: 4 vCPU, 16 GB RAM, 100 GB+ SSD for data
  and backups (more for rasters). Set GeoServer's heap to 4 GB
  (`-Xms4G -Xmx4G` in `GEOSERVER_JAVA_OPTS`).
- A DNS name (e.g. `gis.example.org`) pointing at the server; ports 80 and 443
  open to users; SSH restricted to administrators.
- An SMTP relay for password-reset and notification emails.
- A basemap source licensed for the expected traffic (see *Basemaps*).
- Off-server storage for backups.

## Configuration

Generate a production `.env` on the server (never copy a development one):

```bash
python3 create-envfile.py --noinput --env_type=prod --https --hostname=gis.example.org --email=gis-admin@example.org
```

Then edit `.env`:

| Setting | Production value |
|---|---|
| `DEBUG` | `False` (set by `--env_type=prod`) |
| `HTTP_BIND` | `0.0.0.0` (only behind a host firewall) |
| `LETSENCRYPT_MODE` | `staging` for the first attempt, then `production` |
| `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | `True` |
| `SECURE_SSL_REDIRECT` | add `SECURE_SSL_REDIRECT=True` once HTTPS works |
| `EMAIL_ENABLE` + `DJANGO_EMAIL_*` | your SMTP relay |
| `GEOSERVER_JAVA_OPTS` | 4 GB heap |
| `DEFAULT_MAX_UPLOAD_SIZE` | agreed limit (applied at first start; later change it in *Admin → Upload size limits*) |
| `MEMCACHED_ENABLED` | `True` once tested |
| `ADMIN_PASSWORD` | random; change after first sign-in |
| `LETSENCRYPT_BASE_IMAGE_VERSION` | pin a digest as for the other images |

Keep `.env` mode 0600, owned by the deployment user, and back it up
separately from data backups (it contains every secret).

## HTTPS

Start with the `https` profile so the Let's Encrypt companion runs:

```bash
docker compose --profile https up -d
```

The GeoNode nginx image serves HTTPS on 443 using certificates from the
`nginx-certificates` volume; with `LETSENCRYPT_MODE=disabled` it uses a
self-signed placeholder. Alternatively terminate TLS on an existing reverse
proxy / load balancer and forward to the nginx container; then keep
`SITEURL` as the public `https://` URL.

### HTTPS terminated in front of nginx

If TLS ends at a load balancer, Cloudflare or another proxy that forwards plain
HTTP to the nginx container, keep `HTTPS_HOST` empty and set `SITEURL` (and the
`GEOSERVER_*_LOCATION` values) to the public `https://` address. The project's
`PublicSchemeMiddleware` then makes Django generate `https://` links and the
settings trust that origin for CSRF. Without it, the map client would receive
`http://` API URLs that browsers block on an HTTPS page. Make sure nginx is not
reachable except through that proxy.

## Hardening checklist

- Firewall: allow 80/443 (and SSH from admin addresses only). Never publish
  5432, 6379, 8080 or 11211; the compose file does not.
- Restrict `/geoserver/web/`, `/geoserver/rest/` and `/admin/` to
  administrator networks/VPN at the reverse proxy if possible. They already
  require administrator credentials.
- Keep `ACCOUNT_OPEN_SIGNUP=False`; create accounts as an administrator and add
  them to `avdp-viewers` / `avdp-editors`.
- Change the GeoServer `admin` password only via `.env` +
  `GEOSERVER_ADMIN_PASSWORD` before first start; afterwards change it in both
  GeoServer and `.env`.
- Review `CORS_ALLOW_ALL_ORIGINS=False` / `GEOSERVER_CORS_ALLOWED_ORIGINS`.
- Enable unattended OS security updates; update images by changing the pinned
  tag+digest pairs deliberately and re-testing.
- Ship container logs to central logging; monitor disk usage of volumes.

## Basemaps

The viewer offers OpenStreetMap (default) and an empty background. The public
OSM tile servers (`tile.openstreetmap.org`) are run by volunteers for light use
under the [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
(no bulk downloading or offline caching, attribution required). Server-side
thumbnail generation also fetches tiles.

For production, and for a muted cartographic background that lets the
thematic layers stand out, use a provider you are licensed for (or your own
tile server) and set in `.env`:

```
AVDP_BASEMAP_URL=https://<provider>/<style>/{z}/{x}/{y}.png?key=<your key>
AVDP_BASEMAP_TITLE="Light basemap"
AVDP_BASEMAP_ATTRIBUTION="© <provider> © OpenStreetMap contributors"
```

It then becomes the default background in new and re-imported maps and in
thumbnails. Note: CARTO's public basemap URLs answer without a key but now
draw an "API KEY REQUIRED" watermark, so they cannot be used keyless.

## Storage

| Volume | Content | Back up? |
|---|---|---|
| `avdp_gis-dbdata` | PostgreSQL (application + vector data) | Yes — via `pg_dump`, not file copies |
| `avdp_gis-gsdatadir` | GeoServer catalogue, styles, GeoFence rules | Yes |
| `avdp_gis-statics` | Uploaded files (`uploaded/`), thumbnails, assets, static files | Yes (`uploaded/`, `assets/`) |
| `avdp_gis-data`, `avdp_gis-backup-restore` | Importer/backup working space | Optional |
| `avdp_gis-redisdata`, `avdp_gis-tmp` | Queues, temporary files | No |

Put Docker's data root (or these volumes) on a disk with enough space and
snapshot support where available.

## Backups

Run nightly (cron on the host), keep at least 7 daily + 4 weekly copies
off-server, and test restores quarterly.

```bash
ts=$(date +%Y%m%d%H%M)
docker compose exec -T db pg_dump -U postgres -Fc geonode_project > backup/geonode_project_$ts.dump
docker compose exec -T db pg_dump -U postgres -Fc geonode_project_data > backup/geonode_project_data_$ts.dump
docker run --rm -v avdp_gis-gsdatadir:/v:ro -v "$PWD/backup":/b alpine tar czf /b/gsdatadir_$ts.tgz -C /v .
docker run --rm -v avdp_gis-statics:/v:ro -v "$PWD/backup":/b alpine tar czf /b/statics_$ts.tgz -C /v uploaded assets
```

Verified locally: both `pg_dump` commands succeed, and the vector database
restores into a scratch database with correct feature counts. The volume
archives and a complete restore into a fresh stack have **not** been tested.

GeoNode's own backup/restore tooling (`geonode_project/br/backup.sh`,
`restore.sh`, `settings_docker.ini`) from geonode-project is kept and can be
used instead; see the GeoNode 5.x "Backup & Restore" documentation.

## Restore procedure (fresh server)

1. Install Docker, check out the same Git revision, restore `.env`.
2. Create volumes and start only the database:
   `docker compose up -d db` and wait until healthy.
3. Restore the databases:

    ```bash
    docker compose exec -T db pg_restore -U postgres --clean --if-exists -d geonode_project < backup/geonode_project_<ts>.dump
    ```

    ```bash
    docker compose exec -T db pg_restore -U postgres --clean --if-exists -d geonode_project_data < backup/geonode_project_data_<ts>.dump
    ```

4. Restore files:

    ```bash
    docker run --rm -v avdp_gis-gsdatadir:/v -v "$PWD/backup":/b alpine sh -c "rm -rf /v/* && tar xzf /b/gsdatadir_<ts>.tgz -C /v"
    ```

    ```bash
    docker run --rm -v avdp_gis-statics:/v -v "$PWD/backup":/b alpine tar xzf /b/statics_<ts>.tgz -C /v
    ```

5. `docker compose up -d`, wait for health, then sign in, open a dataset and
   the demo map, and run `python3 scripts/security_smoke.py` against the
   restored instance.
6. If the host name changed, run
   `docker compose exec django python manage.py migrate_baseurl --source-address=<old> --target-address=<new>`.

## Updating

1. Read the GeoNode release notes and the matching geonode-project branch.
2. Update `GeoNode==` in `src/pyproject.toml` and the image tag+digest pairs in
   `.env.example` *together*; copy them into `.env`.
3. Back up, then `docker compose build && docker compose up -d`; migrations
   run automatically.
4. Re-run the unit tests, `scripts/security_smoke.py` and the visual checks.
