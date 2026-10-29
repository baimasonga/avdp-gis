"""Discovery, safe extraction and validation of the AVDP synthetic demo package.

This module has no Django dependencies so it can be unit-tested and reused by
``avdp_validate_demo`` and ``avdp_import_demo``. Validation uses GDAL/OGR,
which is part of the GeoNode base image.
"""

import csv
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass, field

from osgeo import gdal, ogr, osr

gdal.UseExceptions()

PACKAGE_NAME = "AVDP_Synthetic_GIS_Sample_Package.zip"
SYNTHETIC_NOTICE = "SYNTHETIC DEMONSTRATION DATA — NOT OFFICIAL AVDP RECORDS."

# Generous envelope around Sierra Leone (lon/lat, EPSG:4326) used as a sanity
# check that coordinates were not swapped or projected. It is NOT a boundary.
SIERRA_LEONE_ENVELOPE = (-13.6, 6.7, -10.0, 10.2)

# Archive safety limits for the demo package (much stricter than GeoNode's
# generic upload limits because the expected package is small).
MAX_ARCHIVE_ENTRIES = 500
MAX_ARCHIVE_UNCOMPRESSED = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
ALLOWED_EXTENSIONS = {
    ".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx", ".xml",
    ".geojson", ".json", ".csv", ".txt", ".md", ".pdf", ".qml", ".sld",
}


@dataclass(frozen=True)
class LayerSpec:
    key: str
    title: str
    expected_count: int
    geometry: tuple  # accepted geometry families: "point", "line", "polygon"
    category: str  # concept id in the avdp-categories thesaurus
    topic_category: str  # ISO 19115 topic category identifier
    pattern: str  # regex matched against the lower-case file stem
    style_fields: tuple = ()  # attribute candidates for categorised styling
    initially_visible: bool = True

    @property
    def dataset_name(self):
        return f"avdp_demo_{self.key}"

    @property
    def marker_keyword(self):
        return f"avdp-demo-{self.key.replace('_', '-')}"


LAYERS = (
    LayerSpec(
        "farm_plots", "Farm plots", 50, ("polygon",), "crop-production", "farming",
        r"farm[\s_-]*plots?", ("crop", "crop_type", "main_crop", "cropname", "crop_name"),
    ),
    LayerSpec(
        "farmer_groups", "Farmer groups", 20, ("point",), "farmer-organizations", "farming",
        r"farmer[\s_-]*(groups?|org)", ("group_type", "type", "status"),
    ),
    LayerSpec(
        "feeder_roads", "Feeder roads", 15, ("line",), "rural-infrastructure", "transportation",
        r"(feeder[\s_-]*)?roads?", ("condition", "status", "surface", "road_cond"),
    ),
    LayerSpec(
        "water_points", "Water points", 15, ("point",), "water-infrastructure", "inlandWaters",
        r"water[\s_-]*points?", ("status", "functional", "condition", "func_stat", "type"),
    ),
    LayerSpec(
        "grain_stores", "Grain stores", 10, ("point", "polygon"), "storage-facilities", "structure",
        r"(grain[\s_-]*)?stor(e|es|age)", ("status", "condition", "type"),
    ),
    LayerSpec(
        "distribution_sites", "Distribution sites", 15, ("point",), "input-distribution", "farming",
        r"(input[\s_-]*)?distribution([\s_-]*sites?)?", ("input_type", "inputs", "status", "type"),
        initially_visible=False,
    ),
    LayerSpec(
        "demonstration_plots", "Demonstration plots", 15, ("point", "polygon"), "demonstration-extension", "farming",
        r"demo(nstration)?[\s_-]*plots?", ("crop", "technology", "status", "practice"),
        initially_visible=False,
    ),
)
EXPECTED_TOTAL = sum(spec.expected_count for spec in LAYERS)

GEOMETRY_FAMILIES = {
    ogr.wkbPoint: "point",
    ogr.wkbMultiPoint: "point",
    ogr.wkbLineString: "line",
    ogr.wkbMultiLineString: "line",
    ogr.wkbPolygon: "polygon",
    ogr.wkbMultiPolygon: "polygon",
}


class PackageError(Exception):
    """Raised when the package cannot be used at all."""


# ---------------------------------------------------------------------------
# Safe extraction
# ---------------------------------------------------------------------------
def _safe_member_name(name):
    if not name or "\x00" in name:
        raise PackageError(f"Invalid archive entry name: {name!r}")
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or (len(normalised) > 1 and normalised[1] == ":"):
        raise PackageError(f"Absolute path in archive: {name!r}")
    parts = [p for p in normalised.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PackageError(f"Path traversal in archive: {name!r}")
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9 _.()&+,-]+", part):
            raise PackageError(f"Unsafe characters in archive entry: {name!r}")
    return "/".join(parts)


def safe_extract(zip_path, dest_dir):
    """Extract a zip after checking every entry; returns the list of files written.

    Rejects traversal, absolute paths, symlinks, unexpected file types,
    oversized content and zip bombs. Nothing is written if a check fails.
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise PackageError(f"Not a valid zip archive: {exc}") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise PackageError(f"Archive has {len(infos)} entries (limit {MAX_ARCHIVE_ENTRIES}).")
        total = 0
        plan = []
        for info in infos:
            name = _safe_member_name(info.filename)
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise PackageError(f"Symbolic link in archive: {info.filename!r}")
            if info.is_dir():
                continue
            if "__MACOSX" in name.split("/") or os.path.basename(name).startswith("._"):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise PackageError(f"Unexpected file type in archive: {info.filename!r}")
            total += info.file_size
            if total > MAX_ARCHIVE_UNCOMPRESSED:
                raise PackageError("Archive content exceeds the size limit.")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO and info.file_size > 1024 * 1024:
                raise PackageError(f"Suspicious compression ratio for {info.filename!r}.")
            plan.append((info, name))

        dest_root = os.path.realpath(dest_dir)
        written = []
        for info, name in plan:
            target = os.path.realpath(os.path.join(dest_root, name))
            if os.path.commonpath([dest_root, target]) != dest_root:
                raise PackageError(f"Entry escapes destination: {info.filename!r}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            written.append(target)
        return written


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
@dataclass
class LayerFiles:
    spec: LayerSpec
    geojson: str = None
    shapefile: str = None
    csv: str = None

    def preferred(self, prefer="geojson"):
        order = (self.geojson, self.shapefile) if prefer == "geojson" else (self.shapefile, self.geojson)
        return next((p for p in order if p), None)


def discover(root):
    """Map every LayerSpec to the files found under ``root``."""
    found = {spec.key: LayerFiles(spec) for spec in LAYERS}
    candidates = []
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames):
            stem, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext in (".geojson", ".json", ".shp", ".csv"):
                candidates.append((os.path.join(dirpath, filename), stem.lower(), ext))

    for path, stem, ext in candidates:
        matches = [spec for spec in LAYERS if re.search(spec.pattern, stem)]
        # "demonstration plots" must not also be treated as "farm plots" etc.:
        # keep the most specific (longest) match.
        if not matches:
            continue
        spec = max(matches, key=lambda s: len(re.search(s.pattern, stem).group(0)))
        entry = found[spec.key]
        attr = {".geojson": "geojson", ".json": "geojson", ".shp": "shapefile", ".csv": "csv"}[ext]
        if getattr(entry, attr) and getattr(entry, attr) != path:
            raise PackageError(f"Ambiguous files for layer '{spec.key}': {getattr(entry, attr)} and {path}")
        setattr(entry, attr, path)
    return found


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@dataclass
class SourceReport:
    path: str
    feature_count: int = 0
    geometry_families: list = field(default_factory=list)
    epsg: str = None
    extent: tuple = None
    fields: list = field(default_factory=list)
    null_geometries: int = 0
    invalid_geometries: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class LayerReport:
    key: str
    title: str
    expected_count: int
    sources: dict = field(default_factory=dict)
    csv_rows: int = None
    csv_columns: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors and not any(s.errors for s in self.sources.values())

    @property
    def feature_count(self):
        counts = [s.feature_count for s in self.sources.values()]
        return counts[0] if counts else 0


def _epsg_of(srs):
    if srs is None:
        return None
    srs = srs.Clone()
    srs.AutoIdentifyEPSG()
    code = srs.GetAuthorityCode(None)
    if code:
        return f"EPSG:{code}"
    # Shapefile .prj files written as plain WKT GEOGCS["GCS_WGS_1984"...] are
    # frequently not auto-identified; compare with WGS 84 explicitly.
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    if srs.IsSame(wgs84, ["IGNORE_DATA_AXIS_TO_SRS_AXIS_MAPPING=YES", "CRITERION=EQUIVALENT"]):
        return "EPSG:4326"
    return srs.GetName() or "unknown"


def inspect_vector(path, spec):
    report = SourceReport(path=path)
    try:
        ds = ogr.Open(path)
    except RuntimeError as exc:
        report.errors.append(f"Cannot open: {exc}")
        return report
    if ds is None or ds.GetLayerCount() != 1:
        report.errors.append("Expected exactly one vector layer.")
        return report
    layer = ds.GetLayer(0)
    defn = layer.GetLayerDefn()
    report.fields = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    report.epsg = _epsg_of(layer.GetSpatialRef())
    if path.lower().endswith((".geojson", ".json")) and report.epsg is None:
        report.epsg = "EPSG:4326"  # RFC 7946 default
    families = set()
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    count = 0
    for feature in layer:
        count += 1
        geom = feature.GetGeometryRef()
        if geom is None or geom.IsEmpty():
            report.null_geometries += 1
            continue
        families.add(GEOMETRY_FAMILIES.get(ogr.GT_Flatten(geom.GetGeometryType()), "other"))
        if not geom.IsValid():
            report.invalid_geometries += 1
        x0, x1, y0, y1 = geom.GetEnvelope()
        minx, maxx, miny, maxy = min(minx, x0), max(maxx, x1), min(miny, y0), max(maxy, y1)
    report.feature_count = count
    report.geometry_families = sorted(families)
    if count and minx != float("inf"):
        report.extent = (round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6))

    if count != spec.expected_count:
        report.errors.append(f"{count} features, expected {spec.expected_count}.")
    if report.null_geometries:
        report.errors.append(f"{report.null_geometries} features have no geometry.")
    if report.invalid_geometries:
        report.errors.append(f"{report.invalid_geometries} geometries are invalid (OGC validity).")
    unexpected = set(report.geometry_families) - set(spec.geometry)
    if unexpected:
        report.errors.append(f"Geometry type {sorted(unexpected)} not in expected {list(spec.geometry)}.")
    if report.epsg != "EPSG:4326":
        report.errors.append(f"Coordinate reference system is {report.epsg}, expected EPSG:4326.")
    if report.extent:
        x0, y0, x1, y1 = SIERRA_LEONE_ENVELOPE
        if not (x0 <= report.extent[0] and report.extent[2] <= x1 and y0 <= report.extent[1] and report.extent[3] <= y1):
            report.errors.append(f"Extent {report.extent} falls outside the Sierra Leone sanity envelope.")
    if path.lower().endswith(".shp") and not os.path.exists(os.path.splitext(path)[0] + ".prj"):
        report.errors.append("Shapefile has no .prj (coordinate system definition).")
    ds = None
    return report


def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        rows = sum(1 for row in reader if any(cell.strip() for cell in row))
    return header, rows


def validate(found):
    """Validate every layer independently; returns a list of LayerReport."""
    reports = []
    for spec in LAYERS:
        files = found[spec.key]
        report = LayerReport(spec.key, spec.title, spec.expected_count)
        if not (files.geojson or files.shapefile):
            report.errors.append("No GeoJSON or shapefile found for this layer.")
        for label, path in (("geojson", files.geojson), ("shapefile", files.shapefile)):
            if path:
                report.sources[label] = inspect_vector(path, spec)
        if len(report.sources) == 2:
            gj, shp = report.sources["geojson"], report.sources["shapefile"]
            if gj.feature_count != shp.feature_count:
                report.errors.append("GeoJSON and shapefile feature counts differ.")
            gj_fields = {f.lower()[:10] for f in gj.fields}
            shp_fields = {f.lower()[:10] for f in shp.fields}
            if gj_fields != shp_fields:
                report.warnings.append(
                    f"Attribute names differ between GeoJSON and shapefile: {sorted(gj_fields ^ shp_fields)}"
                )
        if files.csv:
            header, rows = _read_csv(files.csv)
            report.csv_rows, report.csv_columns = rows, header
            if rows != spec.expected_count:
                report.errors.append(f"Attribute CSV has {rows} rows, expected {spec.expected_count}.")
            vector_fields = set()
            for source in report.sources.values():
                vector_fields |= {f.lower()[:10] for f in source.fields}
            missing = [c for c in header if c.lower()[:10] not in vector_fields and c.lower() not in ("wkt", "geometry", "lon", "lat", "longitude", "latitude", "x", "y")]
            if missing and vector_fields:
                report.warnings.append(f"CSV columns not present in the vector attributes: {missing}")
        else:
            report.warnings.append("No attribute CSV found for this layer.")
        reports.append(report)
    return reports


def summary(reports):
    total = sum(r.feature_count for r in reports)
    return {
        "ok": all(r.ok for r in reports) and total == EXPECTED_TOTAL,
        "total_features": total,
        "expected_total": EXPECTED_TOTAL,
        "layers": [
            {
                "key": r.key,
                "title": r.title,
                "expected": r.expected_count,
                "features": r.feature_count,
                "csv_rows": r.csv_rows,
                "ok": r.ok,
                "errors": r.errors + [f"{k}: {e}" for k, s in r.sources.items() for e in s.errors],
                "warnings": r.warnings + [f"{k}: {w}" for k, s in r.sources.items() for w in s.warnings],
                "sources": {
                    k: {
                        "path": os.path.basename(s.path),
                        "features": s.feature_count,
                        "geometry": s.geometry_families,
                        "crs": s.epsg,
                        "extent": s.extent,
                        "fields": s.fields,
                    }
                    for k, s in r.sources.items()
                },
            }
            for r in reports
        ],
    }


def style_field(spec, fields, values_by_field):
    """Choose the attribute to categorise by: first candidate with 2..8 distinct values."""
    lower = {f.lower(): f for f in fields}
    for candidate in spec.style_fields:
        actual = lower.get(candidate)
        if actual and 2 <= len(values_by_field.get(actual, ())) <= 8:
            return actual
    return None


def distinct_values(path, max_values=20):
    """Return {field: sorted distinct string values} for string fields (capped)."""
    ds = ogr.Open(path)
    layer = ds.GetLayer(0)
    defn = layer.GetLayerDefn()
    string_fields = [
        defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())
        if defn.GetFieldDefn(i).GetType() == ogr.OFTString
    ]
    values = {f: set() for f in string_fields}
    for feature in layer:
        for f in string_fields:
            v = feature.GetField(f)
            if v not in (None, "") and len(values[f]) <= max_values:
                values[f].add(str(v))
    ds = None
    return {f: sorted(v) for f, v in values.items()}
