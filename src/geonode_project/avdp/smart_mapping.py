"""Automatic ("smart") cartography for vector datasets.

Comparable to ArcGIS Online's smart mapping: when a vector dataset is
uploaded, the portal looks at its geometry and attributes and replaces
GeoServer's generic default style with an AVDP style:

* the default style colours features by a suitable *type/status* field
  (2–8 distinct values) or shows them with one symbol, with labels at local
  scale and centroid markers for small polygons at national scale;
* alternative styles are registered on the layer, so the map viewer's style
  list (layer settings → Style) offers them:

  - "Location (single symbol)"      every geometry type
  - "Heat map (density)"            points
  - "Clusters"                      points
  - "Sized by <number field>"       points with a numeric field
  - "Shaded by <number field>"      polygons with a numeric field

* a formatted pop-up (identify) template is set unless one was customised.

Styles that already carry ``styles.STYLE_MARKER`` (including those written by
``avdp_import_demo``) are left alone unless ``force=True``.
"""

import logging
import re
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.db import connections

from geonode_project.avdp import feature_info, styles

logger = logging.getLogger(__name__)

WORKSPACE = "geonode"
ALT_PREFIX = "__avdp_"
NUMERIC_TYPES = {"xsd:int", "xsd:integer", "xsd:long", "xsd:short", "xsd:double", "xsd:float", "xsd:decimal"}
STRING_TYPES = {"xsd:string"}

# Dataset name/title words -> AVDP theme symbol (only used when the geometry fits)
THEME_HINTS = (
    (("water", "borehole", "well", "pump", "spring"), "water_points"),
    (("store", "warehouse", "storage", "silo", "granary"), "grain_stores"),
    (("group", "cooperative", "fbo", "association"), "farmer_groups"),
    (("distribution", "input", "seed", "fertili"), "distribution_sites"),
    (("demonstration", "extension", "field school", "ffs"), "demonstration_plots"),
    (("road", "track", "feeder"), "feeder_roads"),
    (("farm", "plot", "field", "parcel"), "farm_plots"),
)
THEME_GEOMETRY = {"icon": "point", "road": "line", "polygon": "polygon", "hatch": "polygon"}

TYPE_FIELD_HINTS = (
    "status",
    "condition",
    "functional",
    "state",
    "crop",
    "crop_type",
    "main_crop",
    "type",
    "category",
    "class",
    "group_type",
    "input_type",
    "practice",
    "technology",
    "surface",
    "landuse",
    "use",
)
STATUS_FIELDS = ("status", "condition", "functional", "state")
AMOUNT_FIELD_HINTS = (
    "beneficiaries",
    "benefic",
    "members",
    "households",
    "area_ha",
    "hectares",
    "area",
    "capacity_t",
    "capacity",
    "quantity",
    "qty",
    "volume",
    "yield",
    "production",
    "length_km",
    "length",
    "population",
    "amount",
    "value",
    "count",
)
NOT_DATA = re.compile(r"(^|_)(id|fid|gid|ogc_fid|code|year|lat|lon|lng|latitude|longitude|x|y|objectid)$", re.I)
NAME_FIELDS = ("name", "site_name", "group_name", "store_name", "label", "title")

GENERIC_SYMBOLS = {
    "point": {"kind": "dot", "colour": "#2a6f97", "mode": "category"},
    "line": {"kind": "road", "colour": "#5b6770", "mode": "category"},
    "polygon": {"kind": "polygon", "colour": "#7fb069", "mode": "category"},
}


@dataclass
class Profile:
    name: str
    title: str
    kind: str  # point | line | polygon
    geometry: str
    count: int = 0
    median_area_km2: float = 0.0  # polygons only
    strings: dict = field(default_factory=dict)  # field -> distinct values (capped)
    numbers: dict = field(default_factory=dict)  # field -> (min, max, [quantile breaks])

    @property
    def fields(self):
        return list(self.strings) + list(self.numbers)


# ---------------------------------------------------------------------------
# Profiling
# ---------------------------------------------------------------------------
def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _geometry_kind(attribute_type):
    t = (attribute_type or "").lower()
    if "point" in t:
        return "point"
    if "line" in t or "curve" in t:
        return "line"
    if "polygon" in t or "surface" in t:
        return "polygon"
    return None


def profile(dataset, max_values=12):
    """Describe a vector dataset from GeoNode's attribute list and its PostGIS table."""
    kind, geometry, strings, numbers = None, None, [], []
    for attr in dataset.attribute_set.all():
        gkind = _geometry_kind(attr.attribute_type)
        if gkind:
            kind, geometry = gkind, attr.attribute
        elif attr.attribute_type in STRING_TYPES:
            strings.append(attr.attribute)
        elif attr.attribute_type in NUMERIC_TYPES and attr.attribute.lower() != "fid":
            numbers.append(attr.attribute)
    if not kind:
        return None
    result = Profile(dataset.name, dataset.title or dataset.name, kind, geometry)
    db = settings.OGC_SERVER["default"].get("DATASTORE") or "datastore"
    table = _quote(dataset.name)
    with connections[db].cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        result.count = cursor.fetchone()[0]
        if kind == "polygon":
            geom = _quote(geometry)
            cursor.execute(
                f"SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ST_Area(ST_Transform({geom}, 4326)::geography)) "
                f"FROM {table} WHERE {geom} IS NOT NULL"
            )
            result.median_area_km2 = float(cursor.fetchone()[0] or 0) / 1e6
        for name in strings:
            col = _quote(name)
            cursor.execute(
                f"SELECT DISTINCT {col}::text FROM {table} WHERE {col} IS NOT NULL AND {col}::text <> '' "
                f"ORDER BY 1 LIMIT {max_values + 1}"
            )
            result.strings[name] = [row[0] for row in cursor.fetchall()]
        for name in numbers:
            col = _quote(name)
            cursor.execute(
                f"SELECT min({col}), max({col}), "
                f"percentile_cont(ARRAY[0, 0.2, 0.4, 0.6, 0.8, 1]) WITHIN GROUP (ORDER BY {col}) "
                f"FROM {table} WHERE {col} IS NOT NULL"
            )
            vmin, vmax, breaks = cursor.fetchone()
            if vmin is not None:
                result.numbers[name] = (float(vmin), float(vmax), [float(b) for b in breaks or []])
    return result


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
def guess_theme(prof):
    text = f"{prof.name} {prof.title}".lower().replace("_", " ")
    for words, key in THEME_HINTS:
        if any(w in text for w in words) and THEME_GEOMETRY[styles.SYMBOLS[key]["kind"]] == prof.kind:
            return key
    return None


def _usable_type_field(name, values, count):
    if NOT_DATA.search(name) or name.lower() in NAME_FIELDS or name.lower() == "synthetic":
        return False
    return 2 <= len(values) <= 8 and (count == 0 or len(values) < count)


def choose_type_field(prof, preferred=None):
    if preferred:
        return preferred if preferred in prof.strings else None
    lower = {f.lower(): f for f in prof.strings}
    for hint in TYPE_FIELD_HINTS:
        name = lower.get(hint)
        if name and _usable_type_field(name, prof.strings[name], prof.count):
            return name
    for name, values in prof.strings.items():
        if _usable_type_field(name, values, prof.count):
            return name
    return None


def choose_amount_field(prof):
    usable = {f: v for f, v in prof.numbers.items() if not NOT_DATA.search(f) and v[1] > v[0]}
    lower = {f.lower(): f for f in usable}
    # Polygons are usually best shaded by their size when a size field exists.
    hints = (("area_ha", "hectares", "area") if prof.kind == "polygon" else ()) + AMOUNT_FIELD_HINTS
    for hint in hints:
        if hint in lower:
            return lower[hint]
    return next(iter(usable), None)


# Polygons smaller than this (median) are drawn as centroid markers at
# national scale, where they would otherwise be sub-pixel specks.
SMALL_POLYGON_KM2 = 25


def symbol_for(prof, theme, type_field):
    sym = dict(styles.SYMBOLS[theme] if theme else GENERIC_SYMBOLS[prof.kind])
    if prof.kind == "polygon" and prof.median_area_km2 >= SMALL_POLYGON_KM2:
        sym["small"] = False
    if type_field:
        lower = type_field.lower()
        if lower in STATUS_FIELDS:
            sym["mode"] = "status"
        elif "crop" in lower:
            sym["mode"] = "crop"
        elif sym["mode"] != "status" or not theme:
            sym["mode"] = "category"
    return sym


def plan(prof, type_field=None):
    """Return (default (title, sld), [(suffix, title, sld)]) for a profile."""
    theme = guess_theme(prof)
    tfield = choose_type_field(prof, type_field)
    sym = symbol_for(prof, theme, tfield)
    label = styles.label_field_for(prof.fields)
    default_title = f"Types by {feature_info.label_for(tfield)}" if tfield else "Location (single symbol)"
    default = styles.build_sld(
        theme,
        prof.name,
        default_title,
        field=tfield,
        values=prof.strings.get(tfield, ()) if tfield else (),
        label_field=label,
        geometry=prof.geometry,
        symbol=sym,
        description=(
            f"One colour per {feature_info.label_for(tfield)} value; labels when zoomed in."
            if tfield
            else "Every feature drawn with the same symbol."
        ),
    )
    alternates = []
    if tfield:
        alternates.append(
            ("location", "Location (single symbol)",
             styles.build_location_sld(
                 f"{prof.name}{ALT_PREFIX}location", "Location (single symbol)", sym, label, prof.geometry)
             )
        )
    if prof.kind == "point":
        alternates.append(
            ("heatmap", "Heat map (density)",
             styles.build_heatmap_sld(f"{prof.name}{ALT_PREFIX}heatmap", "Heat map (density)", prof.geometry))
        )
        alternates.append(
            ("clusters", "Clusters",
             styles.build_cluster_sld(f"{prof.name}{ALT_PREFIX}clusters", "Clusters", sym["colour"], prof.geometry))
        )
    amount = choose_amount_field(prof)
    if amount:
        vmin, vmax, breaks = prof.numbers[amount]
        label_text = feature_info.label_for(amount)
        if prof.kind == "point":
            alt_title = f"Sized by {label_text}"
            alternates.append(
                ("size", alt_title,
                 styles.build_size_sld(f"{prof.name}{ALT_PREFIX}size", alt_title, amount, label_text, vmin, vmax,
                                       sym["colour"]))
            )
        elif prof.kind == "polygon":
            alt_title = f"Shaded by {label_text}"
            alternates.append(
                ("choropleth", alt_title,
                 styles.build_choropleth_sld(f"{prof.name}{ALT_PREFIX}choropleth", alt_title, amount, label_text,
                                             breaks, prof.geometry, small=sym.get("small", True)))
            )
    return (default_title, default), alternates, {"theme": theme, "type_field": tfield, "amount_field": amount}


# ---------------------------------------------------------------------------
# GeoServer
# ---------------------------------------------------------------------------
class GeoServer:
    def __init__(self):
        ogc = settings.OGC_SERVER["default"]
        self.base = ogc["LOCATION"].rstrip("/")
        self.auth = (ogc["USER"], ogc["PASSWORD"])

    def _call(self, method, path, **kwargs):
        response = requests.request(method, f"{self.base}/rest/{path}", auth=self.auth, timeout=60, **kwargs)
        return response

    def style_body(self, name, workspace=WORKSPACE):
        path = f"workspaces/{workspace}/styles/{name}.sld" if workspace else f"styles/{name}.sld"
        response = self._call("GET", path)
        return response.text if response.ok else None

    def put_style(self, name, sld, workspace=WORKSPACE):
        headers = {"Content-Type": "application/vnd.ogc.sld+xml"}
        body = sld.encode("utf-8")
        exists = self._call("GET", f"workspaces/{workspace}/styles/{name}.json").ok
        if exists:
            response = self._call("PUT", f"workspaces/{workspace}/styles/{name}?raw=true", data=body, headers=headers)
        else:
            response = self._call(
                "POST", f"workspaces/{workspace}/styles?name={name}&raw=true", data=body, headers=headers
            )
        response.raise_for_status()

    def layer(self, alternate):
        response = self._call("GET", f"layers/{alternate}.json")
        response.raise_for_status()
        return response.json()["layer"]

    def set_layer_styles(self, alternate, default, extra):
        """Set the default style and the list of alternative styles of a layer."""
        current = (self.layer(alternate).get("styles") or {}).get("style") or []
        if isinstance(current, dict):  # GeoServer returns a lone style as an object
            current = [current]
        kept = [
            s for s in current
            if ALT_PREFIX not in s.get("name", "") and s.get("name", "").split(":")[-1] != default
        ]
        payload = {
            "layer": {
                "defaultStyle": {"name": f"{WORKSPACE}:{default}", "workspace": WORKSPACE},
                "styles": {
                    "@class": "linked-hash-set",
                    "style": kept + [{"name": f"{WORKSPACE}:{n}", "workspace": WORKSPACE} for n in extra],
                },
            }
        }
        self._call("PUT", f"layers/{alternate}", json=payload).raise_for_status()


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def is_avdp_styled(gs, dataset):
    style = dataset.default_style
    if not style:
        return False
    body = gs.style_body(style.name, style.workspace or None) or style.sld_body or ""
    return styles.STYLE_MARKER in body


def apply(dataset, force=False, type_field=None, popup=True, thumbnail=True, replace_default=True):
    """Style one vector dataset. Returns a short description of what was done.

    replace_default=False keeps the current default style and only registers
    the alternative styles (used for layers with hand-made AVDP styles).
    """
    from geonode.geoserver.helpers import _invalidate_geowebcache_dataset, gs_catalog, set_styles
    from geonode.layers.models import Dataset

    if dataset.subtype not in ("vector", "vector_time"):
        return "skipped (not a vector dataset)"
    gs = GeoServer()
    if replace_default and not force and is_avdp_styled(gs, dataset):
        return "skipped (already has an AVDP style; use --force to replace it)"
    prof = profile(dataset)
    if prof is None:
        return "skipped (no geometry column found)"

    (default_title, default_sld), alternates, choice = plan(prof, type_field)
    if choice["theme"] and styles.SYMBOLS[choice["theme"]]["kind"] in ("icon", "hatch"):
        from geonode_project.avdp.map_icons import publish_icons

        publish_icons()

    # Keep the dataset's own style name so GeoNode's links and legends stay valid.
    style_name = dataset.default_style.name if dataset.default_style else dataset.name
    if dataset.default_style and dataset.default_style.workspace not in (None, "", WORKSPACE):
        style_name = dataset.name
    if replace_default:
        gs.put_style(style_name, default_sld)
    extra = []
    for suffix, _title, sld in alternates:
        name = f"{dataset.name}{ALT_PREFIX}{suffix}"
        gs.put_style(name, sld)
        extra.append(name)
    gs.set_layer_styles(dataset.alternate, style_name, extra)

    gs_catalog.reset()
    set_styles(dataset, gs_catalog)
    _invalidate_geowebcache_dataset(dataset.alternate)

    updates = {}
    if popup and (
        not dataset.featureinfo_custom_template or "avdp-fi" in (dataset.featureinfo_custom_template or "")
    ):
        synthetic = dataset.keywords.filter(name=getattr(settings, "AVDP_DEMO_KEYWORD", "")).exists()
        updates = {
            "featureinfo_custom_template": feature_info.build_template(dataset.title, prof.fields, synthetic),
            "use_featureinfo_custom_template": True,
        }
        Dataset.objects.filter(pk=dataset.pk).update(**updates)

    if thumbnail:
        try:
            from geonode.resource.registry import resource_manager_registry

            dataset.refresh_from_db()
            resource_manager_registry.get_for_instance(dataset).set_thumbnail(
                dataset.uuid, instance=dataset, overwrite=True, check_bbox=False
            )
        except Exception as exc:  # thumbnails are cosmetic
            logger.warning("AVDP: thumbnail not refreshed for %s: %s", dataset.alternate, exc)

    parts = [f"default '{default_title}'" if replace_default else "default style kept"]
    if extra:
        parts.append("alternatives: " + ", ".join(t for _s, t, _x in alternates))
    if updates:
        parts.append("pop-up template set")
    return "; ".join(parts)
