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
| Theme (design system, text brand) | `templates/geonode-mapstore-client/snippets/custom_theme.html`, `static/avdp/css/avdp.css` | MapStore CSS variables via the client's custom-theme hook |
| Navigation | `snippets/brand_navbar.html`, `brand_navbar_default_left_menu_items.html` | Template overrides (`{% extends %}` of the upstream template where possible). *Upload Data* appears only for users with `base.add_resourcebase`. |
| Homepage | `templates/index.html`, `templatetags/avdp_tags.py` | Extends the client's `index.html`; keeps the upstream resource grids |
| Footer | `snippets/footer.html` | Template override, keeps "Powered by GeoNode" |
| Data guide page | `templates/avdp/upload_guide.html`, `urls.py` (`/upload-guide/`) | `TemplateView` |
| Synthetic-data banner in viewers | `templates/geonode-mapstore-client/_geonode_config.html` | Small script: reads the open resource's keywords from `/api/v2/resources/<pk>` and shows the notice when the `avdp-synthetic-demo` keyword is present |
| Catalogue categories | `thesauri/avdp-categories.rdf`, `thesauri/avdp-data-status.rdf` | GeoNode thesaurus autoload; `avdp_setup` marks them as single-choice facets |
| Roles | `management/commands/avdp_setup.py` | `GroupProfile` groups `avdp-viewers`, `avdp-editors`; Django permission `base.add_resourcebase` on editors |
| Default map view / basemaps | end of `settings.py` | Sierra Leone centre; OpenStreetMap (or `AVDP_BASEMAP_URL`) + empty background |
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

## Design system

`static/avdp/css/avdp.css` defines tokens and components; `custom_theme.html`
maps them onto MapStore's CSS variables so the catalogue, map viewer, panels
and buttons share one look.

| Token | Value | Use |
|---|---|---|
| Type | IBM Plex Sans 400/500/600/700, self-hosted (`static/avdp/fonts`, SIL OFL) | All UI text; tabular figures for numbers |
| Ink / muted | `#14232e` / `#4f5d66` | Body / secondary text (15.5:1, 6.6:1 on white) |
| Paper / surface / line | `#f6f4ee` / `#ffffff` / `#e2ddd1` | Page background, cards and panels, dividers |
| Forest | `#1f5d3a` | Primary actions, active navigation (7.6:1 with white) |
| Navy | `#0d2b45` | Footer |
| Ochre | `#c98a1b` | Accent and focus ring only; synthetic-data notices use the ochre tint |

Homepage (`templates/index.html`): split hero with a featured map (a map
flagged *featured*, otherwise the newest map the visitor may see), live
catalogue counts, theme tiles for the seven AVDP categories with per-visitor
counts from the facet API and deep links to the filtered catalogue
(`/all#/?filter{tkeywords}=<id>`), a compact "Recently added" list (the six
newest resources as one-line rows with a small thumbnail) and a three-step
contribution guide. All numbers and lists come from GeoNode's API in the
visitor's session, so they respect permissions. Theme tiles are rendered
server-side by the `avdp_themes` template tag (`templatetags/avdp_tags.py`).

The full MapStore catalogue grid is deliberately **not** on the homepage
(its plugin list is emptied there in the `ms_scripts` block): with large
cards it pushes everything else down once there are more than a handful of
resources. This follows data portals such as ArcGIS Hub, where the front page
offers categories and a few highlights and the searchable catalogue lives on
its own page.

Catalogue pages (`/all`, `/datasets`, `/maps`, `/documents`) default to the
**list** layout on screens 768 px and wider: one row per resource with
title, description, type, created date and owner, 24 per page (the same idea
as the list/table views in ArcGIS Online's content page). Phones default to
cards with a short thumbnail. The grid/list button stays, and the browser
remembers each visitor's choice. Configured in `overrideLocalConfig`
(`_geonode_config.html`).

## Cartography

Styles are generated by `avdp/styles.py` (SLD 1.0 + GeoServer vendor options)
and uploaded through GeoNode's style upload, so they appear in GeoNode's style
list and legends.

- **Point themes** use badge icons (`static/avdp/map-icons/*.svg`): a coloured
  disc with a white pictogram (drop = water point, building = grain store,
  people = farmer group, sack = distribution site, sprout = demonstration).
  The SVGs are *parametric* (`param(fill)`), published to GeoServer by
  `avdp/map_icons.publish_icons()` via the REST resource API, and referenced
  as `avdp_icons/<icon>.svg?fill=%23RRGGBB`, so one icon serves every class.
- **Colour has one meaning per layer.** Status-like attributes (status,
  condition) use semantic colours shared by all layers — good `#2f7d4a`
  (water points keep water blue), warning `#d08c17`, bad `#b03a2e`, unknown
  grey. Category attributes use a qualitative palette that deliberately avoids
  those hues. Known crops have fixed earthy colours (rice, cassava, maize,
  groundnut, …).
- **Roads** are cased (white casing under a coloured line); poor condition is
  also dashed so it does not rely on colour alone.
- **Demonstration plots** are hatched; **farm plots** are filled polygons.
- **Scale bands:** overview (coarser than 1:1.5M) — small symbols, and small
  polygons drawn as a marker at their centroid so they do not disappear;
  regional; local (finer than 1:150k) — full-size symbols plus labels with a
  white halo. Map-only rules carry `inclusion=mapOnly` and each class has one
  `legendOnly` rule, so the legend shows each class exactly once.
- **Feature information** uses an HTML template per dataset
  (`featureinfo_custom_template`, built by `avdp/feature_info.py`): layer name,
  feature title, readable field labels (district names are marked
  "label, unverified"), and a synthetic-data badge and caveat for demo data.
- **Basemap:** OpenStreetMap by default; a licensed muted basemap can be set
  with `AVDP_BASEMAP_URL` (see DEPLOYMENT.md). Thumbnails use the same
  background.

### Smart mapping (any uploaded vector dataset)

Modelled on ArcGIS Online's smart mapping (`avdp/smart_mapping.py`):

- **Trigger.** GeoNode's importer completes an upload in the Celery task
  `geonode.upload.import_orchestrator` and marks the execution finished with
  a queryset `update()` (no model signal), so `avdp/signals.py` listens for
  that task's Celery `task_success` signal. A memcached key makes it run
  once per upload. `avdp_import_demo` suppresses it for its own uploads and
  then adds only the alternatives. Off with `AVDP_AUTO_STYLE=False`.
- **Profile.** Geometry type, attribute types, distinct values of text fields
  and min/max/quintiles of number fields are read from the PostGIS table;
  for polygons the median area decides whether they become centroid markers
  at national scale (median under 25 km²) or stay polygons.
- **Default style.** If the name/title suggests an AVDP theme with matching
  geometry (wells → water points, roads → feeder roads, …) its symbol is
  used, otherwise a generic dot/line/fill. Colour classes come from the first
  suitable text field (2–8 values; status-like names first, then type/crop/
  category; names and IDs are skipped): status fields get the semantic
  traffic-light colours, crop fields the crop colours. Labels at local scale.
- **Alternative styles** are registered on the GeoServer layer (names
  `<dataset>__avdp_<kind>`), so MapStore lists them under *layer settings →
  Style* with a title and one-line description: *Location (single symbol)*,
  *Heat map (density)* and *Clusters* (points), *Sized by <field>*
  (proportional circles, area ∝ value), *Shaded by <field>* (polygons,
  quintile classes, sequential greens; area fields preferred).
- **Tile-safe by design.** GeoServer's `vec:Heatmap` normalises each tile to
  its own maximum, which showed visible seams in the tiled viewer, so the
  heat map is drawn as stacked translucent halos instead. Clusters use
  `vec:PointStacker` with a 64 px cell (divides the 256 px tile, so adjacent
  tiles agree) and `partials` for count labels on tile edges.
- **Never overwrites** a style carrying the AVDP marker (the SLD abstract)
  unless `--force`; a pop-up template is set only if none exists or it is an
  AVDP one.

## Districts, summary and dashboard

- **Boundaries** (`avdp/boundaries.py`, `avdp_load_boundaries`): OCHA COD-AB
  admin-2 for Sierra Leone (Government of Sierra Leone, CC BY-IGO), validated
  (16 districts, inside the national envelope, valid geometry) and imported
  through the GeoNode importer as `avdp_sle_districts`; outline style with
  one label per district (`interiorPoint` + `partials`, so tiles don't repeat
  labels). Only the admin-2 members of the HDX zip are extracted — the
  archive's padded line tables would otherwise trip the zip-bomb check.
- **Spatial assignment** (`avdp/districts.py`): PostGIS join of
  `ST_PointOnSurface(feature)` with the district polygons, so lines and
  polygons count once. District names are compared with a normalised key
  (accents, case, "District", spelling aliases).
- **Summary** (`avdp_district_summary`): counts per AVDP category concept
  (thesaurus `avdp-categories`) per district; datasets are included only if
  the chosen audience may view them (guardian group permissions). Created
  once through the importer, then updated in place with SQL (fixed columns),
  so its id, links and the dashboard stay valid. Styles: quartile choropleths
  for the total and each category, with a separate "None" class for zero.
- **Dashboard** (`avdp/dashboard.py`, `avdp_dashboard`): a GeoNode GeoApp of
  type dashboard created/updated through `/api/v2/geoapps`; MapStore widgets
  (text, counters, map, bar charts in the `charts[].traces[]` format, table)
  read the summary via WFS/WPS in the viewer's session. GeoNode treats
  feature reads (WFS/WPS) as *download*, so the summary grants viewers (and,
  when public, visitors) download; the public summary only counts public
  data. `security_smoke.py` checks WPS aggregates are denied to anonymous
  users and outsiders.
- GeoNode 5.1 quirk: the GeoApp resource manager ignores `keywords` passed
  together with `vals`; the command sets them directly.

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
