# Data import

## Everyday uploads (editors)

Editors (members of `avdp-editors`) upload through **Upload Data**
(`/catalogue/#/upload/dataset`). Accepted: shapefile (with `.shx`, `.dbf`,
`.prj`, or zipped), GeoPackage, GeoJSON, KML/KMZ, CSV with coordinates,
GeoTIFF. Uploads are processed by GeoNode's importer in the background and are
**private** to the uploader and administrators until shared. The public data
guide is at `/upload-guide/`.

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
