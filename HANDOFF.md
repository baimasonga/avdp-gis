# Handoff — AVDP GIS Portal foundation

Date: 2026-10-29. Work branch: `feat/avdp-gis-foundation`, pushed to
`claude/serene-hypatia-e6uuxv` (the branch this session was asked to push to).

## Summary

The repository (a geonode-project checkout tracking unreleased GeoNode
master) now runs a pinned **GeoNode 5.1.1** stack with AVDP branding, catalogue
categories, role groups, private-by-default permissions, a repeatable
demonstration-data importer and a demonstration map. Everything was verified
in a local Docker deployment. The real demonstration package was **not
supplied**, so the demo import into the portal is **pending**; the import
pipeline was verified with a generated test fixture of the same shape.

## Implemented

- **Deployment** — compose stack aligned with geonode-project 5.1.x:
  GeoNode 5.1.1, GeoServer 2.28.6, PostgreSQL 15 / PostGIS 3.5, nginx, Celery +
  Redis, memcached; images pinned by digest; health checks on every service;
  only nginx published, on 127.0.0.1 by default; persistent named volumes;
  `.env.example` with documented placeholders; `.env` generated with mode 0600
  and git-ignored; database passwords no longer echoed in logs; optional
  BuildKit CA secret for TLS-intercepting proxies.
- **Branding** — text brand "AVDP GIS Portal", blue/green/white theme with AA
  contrast, homepage (purpose, Explore Datasets / Explore Maps / Upload Data,
  visitor empty-state guidance, synthetic-data notice), navigation (Datasets,
  Maps, Documents, Upload Data for users allowed to upload, Data Guide),
  `/upload-guide/` page, footer. No logos, statistics or endorsements.
- **Catalogue** — thesauri *AVDP dataset category* (7 categories) and *AVDP data
  status* (verified / provisional / synthetic demonstration), shown as search
  facets and metadata-editor fields; Sierra Leone default map view;
  OSM + empty backgrounds only.
- **Roles** — `avdp-viewers`, `avdp-editors` (upload right via
  `base.add_resourcebase`); closed sign-up; new resources private
  (`DEFAULT_ANONYMOUS_PERMISSIONS=none`, `DEFAULT_REGISTERED_MEMBERS_PERMISSIONS=none`).
- **Demo tooling** — `avdp_setup`, `avdp_validate_demo`, `avdp_import_demo`
  (see docs/DATA_IMPORT.md), SLD styles, map *AVDP Agriculture — Synthetic
  Demonstration*, viewer banner for synthetic resources.
- **Tests/scripts** — 15 unit tests; `scripts/security_smoke.py` (61 checks);
  screenshot script; test-fixture generator.
- **Docs** — README, docs/ARCHITECTURE.md, DEVELOPMENT.md, DATA_IMPORT.md,
  DEPLOYMENT.md, this file.

## Iteration 2 — visual design and cartography

Feedback: the first version still looked like default GeoNode, including the
map symbology. Changes:

- **Design system** (docs/ARCHITECTURE.md → *Design system*): self-hosted IBM
  Plex Sans, forest/navy/paper/ochre tokens applied to every MapStore variable
  (buttons, tools, panels, loaders), new header with a generic map-pin mark,
  compact navy footer, restyled catalogue cards, page titles, data guide and
  viewer chrome.
- **Homepage** rebuilt: hero with featured-map preview, live per-visitor
  counts, seven theme tiles with live counts and working deep links into the
  filtered catalogue, three-step contribution guide, synthetic-data notice.
- **Cartography** (docs/ARCHITECTURE.md → *Cartography*): parametric SVG badge
  icons per point theme, semantic status colours shared across layers, a
  category palette that avoids status hues, crop colours, cased roads with
  dashed "poor" sections, hatched demonstration plots, three scale bands with
  centroid markers at national scale and labels at local scale, one legend
  entry per class, formatted feature popups with readable labels and an
  "unverified" marker on district labels.
- **Basemap**: OSM default; licensed muted basemap configurable through
  `AVDP_BASEMAP_URL`. CARTO's keyless URLs were tried and rejected because
  they render an "API KEY REQUIRED" watermark.
- Fixed while verifying: catalogue deep links (`/all#/?…`) and the data
  guide's "your datasets" link used a route that renders a blank page.

## Iteration 3 — GitHub Codespaces demos

- `.devcontainer/demo/` + `scripts/codespace-demo.sh` start a temporary demo in
  a 4-core / 16 GB codespace (see docs/CODESPACES.md).
- Found while rehearsing: behind any HTTPS-terminating proxy (Codespaces, a
  load balancer, Cloudflare) Django built `http://` API links and the map
  client failed with mixed-content errors; sign-in also needed the public
  origin trusted. Fixed with `PublicSchemeMiddleware` and CSRF settings
  derived from `SITEURL`; no effect when `SITEURL` is plain HTTP.
- Verified by local rehearsal (fresh volumes, HTTPS proxy, 61/61 security
  checks over HTTPS); **not yet run in a real codespace**.

## Verification performed (local Docker, this session)

| # | Check | Result |
|---|---|---|
| 1 | Services start and become healthy | **Passed** — all 8 healthy, also after `down`/`up` and after image rebuilds |
| 2 | Migrations complete | **Passed** — 420 applied, 0 pending |
| 3 | Administrator can sign in | **Passed** — login form (script and browser); wrong password rejected; admin pages reachable |
| 4 | Valid dataset upload | **Passed** via the importer API used by the web client (editor account; private by default). The drag-and-drop browser upload UI itself was not automated. |
| 5 | Imported feature counts | **Passed with the test fixture** — 50/20/15/15/10/15/15 = 140 in PostGIS and via GeoServer WFS. **Pending** for the real package. |
| 6 | Layers in catalogue and map | **Passed** — catalogue cards, facets, map with 7 layers (screenshots) |
| 7 | Feature inspection | **Passed** — attribute table in the browser; GetFeatureInfo per role over HTTP |
| 8 | Styling, legends, visibility | **Passed** — categorised SLDs in GeoServer, legend in the layer list; an initially hidden layer issues no WMS requests until its checkbox is ticked in the browser, then loads (24 tile requests observed) |
| 9 | Private data inaccessible | **Passed** — 61/61 checks: anonymous and unshared users denied on dataset/map API, catalogue, WMS GetMap, GetFeatureInfo, WFS, asset + SHAPE-ZIP download, metadata page; viewers/editors allowed as shared; outsider with a valid OAuth token still denied by GeoServer; with `--public` visitors can view but not download (WFS counts as download) |
| 10 | Upload protections | **Passed** — anonymous/outsider/viewer uploads refused; traversal zip, zip bomb, disguised executable, `.exe`, malformed GeoJSON, lone `.shp` rejected; `../` filename did not escape; size limits configured (1 GB) |
| 11 | Persistence across restart | **Passed** — data, map, accounts and permissions intact after `docker compose down` / `up` |
| 12 | Re-run without duplication | **Passed** — repeated imports reuse marked datasets; 7 datasets / 1 map remain |
| 13 | Desktop and mobile layouts | **Passed (visual)** — redesigned home (visitor and signed-in), datasets, guide, upload page, map viewer with legend and popup, at 1366 px and 390 px; no horizontal overflow; theme tiles open the correctly filtered catalogue; banner and footer keep map controls and attribution visible |
| 14 | Logs | **Passed** — no errors in container logs except those caused by the deliberate hostile uploads |
| 15 | Backup | **Partly** — `pg_dump` of both DBs succeeded; vector DB restored to a scratch DB with correct counts. Volume archives and full restore into a fresh stack **not tested**. |

The local instance used for these checks contains only test-fixture layers
(attribution names `avdp_test_fixture.zip`); it is a disposable development
environment, not a deliverable data set.

## Blockers and pending items

1. **Demonstration package missing** — supply
   `AVDP_Synthetic_GIS_Sample_Package.zip`, then run the steps in
   docs/DATA_IMPORT.md. If its file names or geometry types differ from the
   described layout, the validator will say so; adjust `LAYERS` in
   `src/geonode_project/avdp/demo_package.py`.
2. **Production deployment not attempted** — HTTPS/Let's Encrypt, SMTP,
   public DNS, firewall and off-site backups need a staging server.
3. **Basemap licensing** — public OSM tiles are for light use only. Obtain a
   licensed (ideally muted) basemap and set `AVDP_BASEMAP_URL`.
4. **Official logos/branding** — text branding only until approved assets are
   supplied (upload via *Admin → Themes* without code changes).

## Known limitations / observations

- Re-running `avdp_import_demo` re-applies its sharing settings to demo
  resources, overwriting manual sharing changes on them.
- Upstream GeoNode 5.1.1 behaviours observed: a malformed GeoJSON upload is
  rejected with HTTP 500 instead of 400; private resources answer anonymous
  API requests with 401 (revealing that the ID exists) rather than 404;
  django-allauth deprecation warnings for `ACCOUNT_*` settings; AngularJS
  console errors on the legacy sign-in page. None were patched (no vendored
  changes).
- The GeoServer and Django admin UIs are reachable through nginx (credentials
  required); restrict by network in production.
- The synthetic-data banner sits above the map at the bottom centre with a
  very high z-index; it could cover a bottom-centre dialog.
- The VS Code dev-container configuration is unchanged and untested.
- `LETSENCRYPT_BASE_IMAGE_VERSION` is tag-pinned only (profile not used locally).

## Recommended next milestone

**"Real data, staging server"**:

1. Import and review the supplied demonstration package; agree with data
   owners on the metadata template and categories.
2. Deploy to a staging server with HTTPS, SMTP and nightly off-site backups;
   perform and document a full restore test.
3. Load *verified* administrative boundaries from an authoritative source and
   add a check that reports district labels inconsistent with feature
   locations (kept separate from verified assignments).
4. Onboard real users into `avdp-viewers` / `avdp-editors`; write a short
   editor guide for metadata and sharing.
5. Decide the production basemap source and update `MAPSTORE_BASELAYERS`.
