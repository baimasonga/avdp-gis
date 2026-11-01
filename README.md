# AVDP GIS Portal

A standalone web portal for storing, managing, searching and displaying
agricultural and rural infrastructure GIS information in Sierra Leone.

It is a [GeoNode](https://geonode.org/) project (based on
[geonode-project](https://github.com/GeoNode/geonode-project) 5.1.x) running
**GeoNode 5.1.1** with GeoServer 2.28.6 and PostgreSQL 15 / PostGIS 3.5. AVDP
features are added through GeoNode's supported extension points (project
templates, static files, settings, thesauri and management commands); no
vendored GeoNode code is modified.

What the first version provides:

- Dataset upload (shapefile, GeoPackage, GeoJSON, KML/KMZ, CSV, GeoTIFF) through
  GeoNode's importer, with archive and file-type validation.
- A searchable catalogue with AVDP **dataset category** and **data status**
  facets, ISO metadata, regions, licences and update frequency.
- Interactive maps (MapStore) with multiple layers, legends, layer visibility,
  feature inspection and saved, shareable maps; purpose-built cartography
  (icon symbols, status colours, scale-dependent labels, formatted popups).
- A custom design system (IBM Plex Sans, forest/navy/paper palette) across the
  homepage, catalogue and map viewer.
- GeoNode's native permissions: new uploads are private until deliberately
  shared or made public. Role groups `avdp-viewers` and `avdp-editors`.
- An explicit, repeatable import command for the synthetic demonstration
  package, and a demonstration map, all clearly labelled
  **SYNTHETIC DEMONSTRATION DATA — NOT OFFICIAL AVDP RECORDS.**

> **Status:** development foundation. Not yet production-ready — see
> [HANDOFF.md](HANDOFF.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quick start (local development)

Requirements: Docker Engine with Compose v2, ~8 GB free RAM, ~15 GB disk.

1. Create your local `.env` (random secrets, mode 0600, never committed):

    ```bash
    python3 create-envfile.py --noinput --env_type=dev --hostname=localhost --email=admin@example.org
    ```

2. Build and start (the first build downloads GeoNode and takes a while):

    ```bash
    docker compose build
    ```

    ```bash
    docker compose up -d
    ```

3. Wait until every service reports `healthy` (2–5 minutes on first start):

    ```bash
    docker compose ps
    ```

4. Open <http://localhost/>. The stack listens on `127.0.0.1` only.

### Administrator account

On the first start the entrypoint creates the administrator from
`ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` in `.env`. Read the
generated password locally (do not paste it anywhere shared):

```bash
grep '^ADMIN_PASSWORD=' .env
```

Sign in at <http://localhost/account/login/> and change the password from the
user menu → *Profile*. Additional administrators can be created with:

```bash
docker compose exec django python manage.py createsuperuser
```

### Day-to-day commands

| Task | Command |
|---|---|
| Stop (keeps data) | `docker compose stop` |
| Start again | `docker compose up -d` |
| Remove containers (keeps volumes) | `docker compose down` |
| Follow logs | `docker compose logs -f django celery geoserver` |
| Application log files | `docker compose exec django tail -f /var/log/geonode.log` |
| Re-apply AVDP configuration | `docker compose exec django python manage.py avdp_setup` |

### Import the demonstration package

Copy `AVDP_Synthetic_GIS_Sample_Package.zip` into `data/demo/` (git-ignored,
mounted read-only into the containers), then:

```bash
docker compose exec django python manage.py avdp_validate_demo /usr/src/project/data/demo/AVDP_Synthetic_GIS_Sample_Package.zip
```

```bash
docker compose exec django python manage.py avdp_import_demo /usr/src/project/data/demo/AVDP_Synthetic_GIS_Sample_Package.zip
```

The import is safe to re-run. Demo resources stay private (shared with the AVDP
groups) unless you add `--public`. Details: [docs/DATA_IMPORT.md](docs/DATA_IMPORT.md).

### District boundaries, summary and dashboard

Load the official district boundaries once (downloads ~10 MB from the
Humanitarian Data Exchange), then build the district summary and the
*AVDP district overview* dashboard (menu **Dashboards**):

```bash
docker compose exec django python manage.py avdp_load_boundaries
```

```bash
docker compose exec django python manage.py avdp_district_summary
```

```bash
docker compose exec django python manage.py avdp_dashboard
```

Re-run the last two after adding or sharing data. To check district labels in
your data against the boundaries:

```bash
docker compose exec django python manage.py avdp_district_check
```

Details: [docs/DATA_IMPORT.md](docs/DATA_IMPORT.md#district-boundaries-summary-and-dashboard).

### Back up, restore, move to another computer

```bash
scripts/avdp-backup.sh
```

writes `backups/avdp-backup-<date>.tar.gz` with both databases, the GeoServer
data directory, uploaded files and `.env` (so it contains passwords; add
`--no-secrets` to leave `.env` out). On the other computer: clone the
repository, `docker compose build`, copy the archive into the folder and run

```bash
scripts/avdp-restore.sh backups/avdp-backup-<date>.tar.gz
```

which **replaces all portal data there** with the backup (it asks you to type
RESTORE first).

### Data checks

Every upload is checked automatically (location inside Sierra Leone,
duplicates, invalid shapes, empty columns, district labels); the result is
shown on the dataset's map page. Re-check existing datasets with
`docker compose exec django python manage.py avdp_quality_check`.

### Field surveys (KoboToolbox / ODK Central)

Put the API token in `.env` (`KOBO_TOKEN`, or `ODK_TOKEN` / `ODK_USER` +
`ODK_PASSWORD`), restart, then:

```bash
docker compose exec django python manage.py avdp_sync_form kobo --server https://kf.kobotoolbox.org --form <asset uid> --name water_point_survey --share
```

Run the same command again (or on a schedule) to refresh the dataset.

### More commands

| Task | Command (prefix `docker compose exec django python manage.py`) |
|---|---|
| Change history on/off, or list changes | `avdp_track_changes --all` · `avdp_track_changes <name> --show` |
| Map story (after the district summary) | `avdp_story` |
| Re-style datasets / turn on time slider | `avdp_style_datasets` |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, versions, customisations
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local workflow, tests, troubleshooting
- [docs/DATA_IMPORT.md](docs/DATA_IMPORT.md) — validation, import, metadata, demo-data limitations
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — production prerequisites, HTTPS, storage, backup/restore
- [docs/CODESPACES.md](docs/CODESPACES.md) — temporary demos in GitHub Codespaces
- [HANDOFF.md](HANDOFF.md) — what was done, what was verified, what is pending

## Upstream

This repository started as a copy of `geonode-project`. Upstream improvements
can be merged from <https://github.com/GeoNode/geonode-project> (branch `5.1.x`
for this GeoNode release). AVDP-specific code lives in
`src/geonode_project/{avdp,management,templates,static/avdp,thesauri}` and in
the clearly marked section at the end of `src/geonode_project/settings.py`.

Licence: GPL-3.0-or-later (inherited from GeoNode / geonode-project).
