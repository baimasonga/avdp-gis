# Architecture

## Starting point

The repository was a **geonode-project** checkout already converted into a
concrete Django project (`src/geonode_project`), so no `django-admin
startproject` generation step is needed. It tracked the `master` line, which
installs **unreleased GeoNode master** and floating container tags. It was
re-aligned with the stable **geonode-project 5.1.x** scaffolding and
**GeoNode 5.1.1** (latest stable release at the time of writing), whose own
`docker-compose.yml` defines the service versions used here. Master-only
scaffolding (Redis cache, no GeoServer data container) was not kept because it
depends on unreleased GeoNode changes.

## Components and versions (verified in the running stack)

| Service (compose name) | Image / package | Version | Role |
|---|---|---|---|
| `django` | `avdp_gis/geonode:5.1.1-avdp` built from `geonode/geonode-base:latest-ubuntu-24.04` (digest-pinned) | GeoNode 5.1.1, Django 5.2.18, Python 3.12.3, GDAL 3.8.4, uWSGI 2.0.30, Ubuntu 24.04 | Web application, REST API, importer |
| `celery` | same image | Celery 5.6.3 | Imports, thumbnails, permission sync, harvesting |
| `geonode` | `geonode/nginx:1.31.7-latest` (digest-pinned) | nginx 1.31.7 | Only published service; proxies Django and `/geoserver/`, serves static/media |
| `geoserver` | `geonode/geoserver:2.28.6-latest` (digest-pinned) | GeoServer 2.28.6 + GeoFence | WMS/WFS/WCS, styles, legends, GetFeatureInfo |
| `data-dir-conf` | `geonode/geoserver_data:2.28.6-latest` (digest-pinned) | 2.28.6 | Seeds the GeoServer data directory volume |
| `db` | `geonode/postgis:15-3.5-latest` (digest-pinned) | PostgreSQL 15.17, PostGIS 3.5.5 | `geonode_project` (application) and `geonode_project_data` (vector data) databases |
| `redis` | `redis:7-alpine` (digest-pinned) | Redis 7.4 | Celery broker/results |
| `memcached` | `memcached:1.6-alpine` (digest-pinned) | 1.6 | Optional Django cache (`MEMCACHED_ENABLED`) |
| `letsencrypt` | `geonode/letsencrypt:2.6.0-latest` | 2.6.0 | Only with `--profile https` |
| Front end | `django-geonode-mapstore-client` | 5.1.1 | MapStore-based catalogue, viewer, metadata editor |

Pins live in `.env.example` (`*_BASE_IMAGE_VERSION` tag + `*_BASE_IMAGE_DIGEST`)
and `src/pyproject.toml` (`GeoNode==5.1.1`). Change them together, and only to a
combination published for the same GeoNode release.

```
browser ──► nginx (127.0.0.1:80) ──► django (uWSGI :8000) ──► PostgreSQL/PostGIS
                     │                     │        ▲
                     └──► /geoserver/ ──► GeoServer ┘ (reads geonode_project_data)
                                           ▲
          celery workers ◄── redis ◄───────┘ (async import, styles, thumbnails, GeoFence rules)
```

### Persistent volumes

`avdp_gis-dbdata` (databases), `avdp_gis-gsdatadir` (GeoServer catalogue,
styles, GeoFence rules), `avdp_gis-statics` (uploaded files, static files,
thumbnails), `avdp_gis-data`, `avdp_gis-redisdata`, `avdp_gis-backup-restore`,
`avdp_gis-dbbackups`, `avdp_gis-nginx*`, `avdp_gis-tmp`. The volume prefix comes
from `COMPOSE_PROJECT_NAME`.

### Network exposure

Only nginx publishes ports, bound to `HTTP_BIND` (default `127.0.0.1`).
GeoServer (8080), PostgreSQL (5432), Redis and memcached are reachable only on
the internal Docker network. The GeoServer and Django admin UIs are reachable
through nginx at `/geoserver/web/` and `/admin/` and require administrator
credentials; restrict them further in production (see DEPLOYMENT.md).

## AVDP customisations

All in supported extension points:

| Area | Where | Mechanism |
|---|---|---|
| Theme (blue/green/white, text brand) | `templates/geonode-mapstore-client/snippets/custom_theme.html`, `static/avdp/css/avdp.css` | MapStore CSS variables via the client's custom-theme hook |
| Navigation | `snippets/brand_navbar.html`, `brand_navbar_default_left_menu_items.html` | Template overrides (`{% extends %}` of the upstream template where possible). *Upload Data* appears only for users with `base.add_resourcebase`. |
| Homepage | `templates/index.html`, `snippets/hero.html` | Extends the client's `index.html`; keeps the upstream resource grids |
| Footer | `snippets/footer.html` | Template override, keeps "Powered by GeoNode" |
| Data guide page | `templates/avdp/upload_guide.html`, `urls.py` (`/upload-guide/`) | `TemplateView` |
| Synthetic-data banner in viewers | `templates/geonode-mapstore-client/_geonode_config.html` | Small script: reads the open resource's keywords from `/api/v2/resources/<pk>` and shows the notice when the `avdp-synthetic-demo` keyword is present |
| Catalogue categories | `thesauri/avdp-categories.rdf`, `thesauri/avdp-data-status.rdf` | GeoNode thesaurus autoload; `avdp_setup` marks them as single-choice facets |
| Roles | `management/commands/avdp_setup.py` | `GroupProfile` groups `avdp-viewers`, `avdp-editors`; Django permission `base.add_resourcebase` on editors |
| Default map view / basemaps | end of `settings.py` | Sierra Leone centre; OpenStreetMap + empty background only |
| Demo import | `avdp/demo_package.py`, `avdp/styles.py`, `avdp/demo_map.py`, `management/commands/avdp_*` | GDAL validation; GeoNode importer API; resource manager; maps API |

`avdp_setup` runs on every Django container start (idempotent). Demo import
never runs automatically.

### Roles mapped to GeoNode

| AVDP role | GeoNode mechanism |
|---|---|
| Visitor | Anonymous user. Sees only resources whose `anonymous` permission is not `none`. |
| Viewer | Any registered account (`registered-members`); members of `avdp-viewers` receive view+download on resources shared with that group. |
| Editor | Member of `avdp-editors`: may upload (`base.add_resourcebase`) and edit resources shared with the group. |
| Administrator | Django superuser (`is_superuser`): users, groups, GeoNode admin, GeoServer. |

Defaults set in `.env.example`: `DEFAULT_ANONYMOUS_PERMISSIONS=none`,
`DEFAULT_REGISTERED_MEMBERS_PERMISSIONS=none`,
`AUTO_ASSIGN_REGISTERED_MEMBERS_TO_CONTRIBUTORS=False`,
`ACCOUNT_OPEN_SIGNUP=False`, `EDITORS_CAN_MANAGE_ANONYMOUS_PERMISSIONS=False`.
GeoNode synchronises these permissions to GeoServer (GeoFence), so they also
apply to WMS/WFS/GetFeatureInfo/downloads. WFS feature access counts as
*download*.

## Upload protections (GeoNode 5.1.1, retained)

- `FileValidationUploadHandler` / `SizeRestrictedFileUploadHandler`: extension
  allow-list, libmagic content checks, per-type size limits
  (`/api/v2/upload-size-limits`, initialised from `DEFAULT_MAX_UPLOAD_SIZE`,
  1 GB in `.env.example`), parallel upload limit per user.
- `geonode.upload.zip_validation`: rejects traversal, absolute paths, symlinks,
  >10 000 entries, >2 GiB expanded, >100× compression ratio.
- A client-supplied file name containing `../` segments did not escape the
  upload directory in our smoke test (`scripts/security_smoke.py`).

The demo importer adds its own, stricter extraction checks
(`avdp/demo_package.safe_extract`) before anything is handed to GeoNode.
