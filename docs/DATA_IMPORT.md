# Data import

## Everyday uploads (editors)

Editors (members of `avdp-editors`) upload through **Upload Data**
(`/catalogue/#/upload/dataset`). Accepted: shapefile (with `.shx`, `.dbf`,
`.prj`, or zipped), GeoPackage, GeoJSON, KML/KMZ, CSV with coordinates,
GeoTIFF. Uploads are processed by GeoNode's importer in the background and are
**private** to the uploader and administrators until shared. The public data
guide is at `/upload-guide/`.

**Spreadsheet templates.** `/static/avdp/templates/` holds one CSV template
per AVDP theme (linked from the data guide, section *Spreadsheet templates*)
with `latitude`/`longitude` columns (roads use a `wkt_geom` line), plus a
practice file of eight invented water points. Column names match the
portal's pop-up labels and style rules (status, crop, condition…).

**Automatic data check.** After the automatic style, every upload is checked
(`avdp/quality.py`): features without location or outside Sierra Leone's
districts (with a hint when latitude/longitude look swapped), invalid shapes,
exact duplicate locations, empty or mostly empty columns (optional columns
such as `photo_url` and `remarks` only as notes) and district labels that
disagree with the location. The report is stored (`QualityReport`, shown on
the dataset's map page as "Data check: …", visible to whoever may view the
dataset via `/avdp/quality/<id>/`). Re-run with `manage.py avdp_quality_check`.

**Photos.** A `photo_url`/`photo` column is shown as a picture in the pop-up.

**Automatic styling ("smart mapping").** When a vector upload finishes, the
portal replaces GeoServer's generic style (e.g. red squares) with an AVDP
style chosen from the data (see docs/ARCHITECTURE.md → *Smart mapping*), sets
a formatted pop-up and re-renders the thumbnail. Alternative styles (single
symbol, heat map, clusters, sized or shaded by a number field) are offered in
the map viewer under *layer settings → Style*. To style datasets that existed
before this feature, or to colour by another field:

```bash
docker compose exec django python manage.py avdp_style_datasets            # all still on a generic style
docker compose exec django python manage.py avdp_style_datasets farm_plots --field crop --force
```

`--force` replaces an existing AVDP style; styles edited by hand in the style
editor are only replaced with `--force`. Set `AVDP_AUTO_STYLE=False` in `.env`
to turn automatic styling off.

Then complete metadata (*Edit → Edit metadata*). Recommended minimum:

| Item | GeoNode field |
|---|---|
| Title, description | Title, Abstract |
| AVDP category | *AVDP dataset category* thesaurus |
| Synthetic / provisional / verified | *AVDP data status* thesaurus |
| Data source and owner | Attribution; Point of contact / Owner / Custodian contacts |
| Geographic coverage | Regions (e.g. Sierra Leone), bounding box (automatic) |
| Collection or reference date | Date + date type |
| Coordinate reference system | Detected automatically (`srid`) |
| Update frequency | Maintenance frequency |
| Licence and access restrictions | License; Restrictions + "Other constraints" |

**District labels vs. spatial assignment.** A district name stored in an
attribute is a label supplied with the data. Do not use GeoNode *Regions* to
claim district coverage unless the features were checked against official
district boundaries; record the verification in the data quality statement.

## Field surveys: KoboToolbox and ODK Central

`avdp_sync_form` publishes a form's submissions as a point dataset and, on
later runs, replaces its records in place (same dataset, maps and
dashboards keep working):

```bash
# KoboToolbox (KOBO_TOKEN in .env: Account settings → API key)
docker compose exec django python manage.py avdp_sync_form kobo --server https://kf.kobotoolbox.org --form <asset uid> --name water_point_survey --share
# ODK Central (ODK_TOKEN, or ODK_USER + ODK_PASSWORD in .env)
docker compose exec django python manage.py avdp_sync_form odk --server https://central.example.org --project 3 --form water_points --name water_point_survey --share
```

- The first GPS question becomes the location; submissions without one are
  skipped (and counted in the output). Group names are dropped from column
  names; system fields are left out except the submission id and time.
- Questions whose names suggest personal data (names, phone, e-mail, ID
  numbers…) are **not copied**; list any you need with `--keep-personal`,
  and exclude others with `--exclude`.
- New datasets are private to the owner; `--share` gives AVDP Viewers and
  Editors access, `--public` also visitors.
- New questions added to the form later are reported and ignored; delete the
  dataset and sync again to include them.
- Photos and other attachments stay on the survey server (they need its
  login); copy the ones you want to publish into Documents.
- Schedule it to keep data current: cron on a server
  (`0 * * * * cd /srv/avdp-gis && docker compose exec -T django python manage.py avdp_sync_form …`)
  or Windows Task Scheduler on a laptop.

Verified here against a local stand-in answering in the documented
KoboToolbox v2 and ODK Central OData formats (create, refresh 11 → 15
records, refused token, ODK nested groups); **not yet run against a real
KoboToolbox or ODK server**.

## Time slider, printing, change history, map story

- **Time slider.** A dataset with a date column (`distribution_date`,
  `date`, `submitted`, …, typed as a date by the import) gets a WMS time
  dimension automatically; the map viewer then shows a timeline to step or
  play through the dates.
- **Printing.** Print layouts carry an AVDP text header instead of the
  GeoNode image (installed by `avdp_setup`; the original is kept as
  `printing/print_header.geonode.png`) and files are named
  `AVDP-Map-<date>.pdf`.
- **Change history.** Every dataset uploaded after this release records
  added, changed and deleted records (time, old and new values, and whether
  the change came from the map editor, a form sync or an upload/script) in
  `avdp_change_log`; open it from the dataset's "Data check" note → *Change
  history* (needs download permission) or `avdp_track_changes <name> --show`.
  Browser edits all reach the database through GeoServer's account, so the
  log cannot say *which* editor made a change. Turn it on for older datasets
  with `avdp_track_changes --all`.
- **Map story.** `avdp_story` creates *AVDP at district level*: a scrolling
  story with the district summary and water points as live maps behind the
  text. Edit it in the portal like any GeoNode story.

## District boundaries, summary and dashboard

### Boundaries (once)

```bash
docker compose exec django python manage.py avdp_load_boundaries
```

Downloads the Sierra Leone administrative boundaries (COD-AB) from the
Humanitarian Data Exchange — source *Government of Sierra Leone*, published by
OCHA, licence **CC BY-IGO 3.0** (attribution required; it is in the dataset's
metadata). Only the admin-2 layer is used: **16 districts** (2017 structure,
including Falaba and Karene; the source spells Falaba "Fabala" — the dataset
shows "Falaba" and keeps the original in `district_source_name`). The command
validates the count, CRS and extent, and refuses anything else.

Without internet on the server, download `sle_admin_boundaries.shp.zip` from
<https://data.humdata.org/dataset/cod-ab-sle> elsewhere, copy it into
`data/demo/` and run
`avdp_load_boundaries --source /usr/src/project/data/demo/sle_admin_boundaries.shp.zip`.
Re-running refreshes metadata/style/sharing; `--replace` imports a new release.
Boundaries are shared with AVDP Viewers/Editors; add `--public` for visitors.

### District label check (read-only)

```bash
docker compose exec django python manage.py avdp_district_check
```

For every dataset with a district field (`district`, `dist_label`,
`district_name`, …) it reports how many labels match the district the feature
lies in, mismatches with examples, labels that are not district names and
features outside the country. Spelling variants are matched ("Western Urban",
"Freetown" = Western Area Urban; "Fabala" = Falaba). One row per feature:

```bash
docker compose exec -T django python manage.py avdp_district_check --csv - > district_check.csv
```

### District summary and dashboard

```bash
docker compose exec django python manage.py avdp_district_summary
docker compose exec django python manage.py avdp_dashboard
```

The summary is a dataset (*District summary — AVDP features per category*)
with one row per district: the number of features of each AVDP dataset
category located in it, and a total. A dataset is counted only if it has an
*AVDP dataset category* in its metadata and is shared with AVDP Viewers (or
the public) — so the figures never reveal private data. `--audience public`
counts public datasets only; `--audience all` ignores sharing (for
administrators' own use). In the map viewer the summary offers one choropleth
style per category (*layer settings → Style*).

The dashboard (*AVDP district overview*, menu **Dashboards**) shows totals,
a map, features per district and per province, and the district table. Both
commands update the same resources in place, so links stay valid; re-run
them after adding or sharing data. To publish the dashboard to visitors:

```bash
docker compose exec django python manage.py avdp_load_boundaries --public
docker compose exec django python manage.py avdp_district_summary --audience public --public
docker compose exec django python manage.py avdp_dashboard --public
```

Counts are numbers of mapped features, not people, households or hectares.
If any counted dataset is synthetic, the summary and dashboard carry the
synthetic-data notice and banner.

## Demonstration package

### Status

`AVDP_Synthetic_GIS_Sample_Package.zip` **was not supplied** with this
repository, so the real demonstration import has **not** been run. The tooling
was exercised end-to-end with a generated *test fixture* of the same shape (see
below). Run the steps here once the package is available.

### Expected content

Seven synthetic layers in WGS 84 (EPSG:4326), each as shapefile and/or GeoJSON,
plus an attribute CSV and upload instructions:

| Layer | Features | Category | Geometry accepted |
|---|---:|---|---|
| Farm plots | 50 | Crop production | polygon |
| Farmer groups | 20 | Farmer organizations | point |
| Feeder roads | 15 | Rural infrastructure | line |
| Water points | 15 | Water infrastructure | point |
| Grain stores | 10 | Storage facilities | point or polygon |
| Distribution sites | 15 | Agricultural input distribution | point |
| Demonstration plots | 15 | Demonstration and extension | point or polygon |
| **Total** | **140** | | |

Files are matched by name (case-insensitive), e.g. `farm_plots`, `Farm Plots`,
`water-points`, `demonstration_plots`/`demo_plots`. If a file name does not
match, the validator reports the layer as missing; rename the file inside a
copy of the package or extend the pattern in
`src/geonode_project/avdp/demo_package.py` (`LAYERS`).

### 1. Place the package

```bash
cp /path/to/AVDP_Synthetic_GIS_Sample_Package.zip data/demo/
```

`data/demo/` is git-ignored and mounted read-only at
`/usr/src/project/data/demo` in the `django` and `celery` containers.

### 2. Validate (no changes to the portal)

```bash
docker compose exec django python manage.py avdp_validate_demo /usr/src/project/data/demo/AVDP_Synthetic_GIS_Sample_Package.zip --json /tmp/avdp_validation.json
```

Checks, per layer and per format, using GDAL/OGR independently of GeoNode:

- safe extraction: no absolute paths, `..`, symlinks, unexpected file types,
  unsafe characters, oversized content or extreme compression ratios;
- feature count equals the expected count; total = 140;
- no empty geometries; all geometries OGC-valid;
- geometry type matches the layer;
- CRS is EPSG:4326 (shapefiles must have a `.prj`);
- extent falls inside a generous Sierra Leone sanity envelope
  (-13.6, 6.7, -10.0, 10.2) — catches swapped or projected coordinates, it is
  **not** a boundary check;
- GeoJSON and shapefile agree on feature count (and attribute names: warning);
- the attribute CSV has the expected number of rows and its columns exist in
  the vector attributes (warning).

The command exits non-zero on any error.

### 3. Import

```bash
docker compose exec django python manage.py avdp_import_demo /usr/src/project/data/demo/AVDP_Synthetic_GIS_Sample_Package.zip
```

Options: `--owner <username>` (default `ADMIN_USERNAME`), `--prefer shapefile`
(default GeoJSON when both exist), `--public` (let visitors *view* the demo
datasets and map; downloads stay restricted), `--skip-map`,
`--validate-only`, `--adopt`, `--import-alongside`.

What it does:

1. Validates as above; aborts before changing anything if validation fails.
2. Uploads each layer through GeoNode's importer API (`/api/v2/uploads/upload`,
   the endpoint the web client uses) as user `--owner`, so GeoNode's upload
   validation, size limits, GeoServer publishing, catalogue registration and
   permission sync all apply. Datasets are named `avdp_demo_<layer>`.
3. Marks each dataset with keywords `avdp-synthetic-demo` and
   `avdp-demo-<layer>` immediately after import.
4. Applies metadata through GeoNode's resource manager: title
   "*Layer* — SYNTHETIC DEMO", abstract beginning with
   **SYNTHETIC DEMONSTRATION DATA — NOT OFFICIAL AVDP RECORDS.**, limitations,
   ISO topic category, AVDP category and *Synthetic demonstration* status,
   region Sierra Leone, licence *Not specified*, restriction
   *otherRestrictions* with use constraints, update frequency *notPlanned*,
   attribution naming the imported file.
5. Generates an SLD per layer (distinct symbol per layer; categorised by crop
   / status / condition / type when such an attribute has 2–8 values) and
   uploads it through the importer's style upload; refreshes thumbnails.
6. Sets sharing via GeoNode's compact permission spec: owner, `avdp-viewers`
   = download, `avdp-editors` = edit, registered members = none, anonymous =
   none (or view with `--public`).
7. Checks feature counts in PostGIS (must total 140).
8. Creates or updates the map **AVDP Agriculture — Synthetic Demonstration**
   through the maps API: OpenStreetMap background, all seven layers (polygons
   at the bottom, points on top; distribution sites and demonstration plots
   initially hidden to keep the first load light), initial view fitted to the
   data, attribute-table feature info.

### Re-running

Safe to repeat. Datasets carrying their marker keyword are reused (not
uploaded again); metadata, styles and sharing are re-applied, and the map is
updated in place. Note that re-applying sharing **resets manual sharing
changes** on demo resources to the command's options.

A dataset named `avdp_demo_<layer>` *without* the marker is treated as
unrelated data and left untouched; the command stops with an explanation.
Use `--adopt` only if it is a partial earlier run, or `--import-alongside` to
let GeoNode assign a different name.

### Removing demo content

Delete the resources from the catalogue (*Delete* on each resource) or, for
all of them:

```bash
docker compose exec django python manage.py shell -c "from geonode.base.models import ResourceBase as R; from geonode.resource.registry import resource_manager_registry as m; [m.get_for_instance(r.get_real_instance()).delete(r.uuid, instance=r.get_real_instance()) for r in R.objects.filter(keywords__name='avdp-synthetic-demo').distinct()]"
```

While demo data is counted, the district summary and dashboard also carry the
`avdp-synthetic-demo` keyword, so the command above removes them too. Re-run
`avdp_district_summary` and `avdp_dashboard` afterwards (the dashboard then
gets a new link).

### Demo-data limitations (shown in metadata and in the portal)

- Locations and figures are invented.
- District labels are illustrative and have not been checked against official
  boundaries.
- Farm polygons are schematic; roads do not represent actual routes.
- Beneficiary counts must not be summed as unique people across layers.
- The package contains no official district boundaries.

## Test fixture (for development only)

`src/geonode_project/tests/make_test_package.py` builds a zip with the same
folder layout, layer names, counts and CRS as the expected package, using
random points/lines/squares inside an inland box, attributes such as
`crop`, `status`, `dist_label` ("District A"…), and a `README.txt`
stating it is a test fixture. It is used by the unit tests and was used to
verify the import pipeline. It must not be presented as AVDP data.
