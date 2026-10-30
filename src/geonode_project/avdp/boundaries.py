"""Official Sierra Leone district boundaries (admin level 2).

Source: the Common Operational Dataset of administrative boundaries (COD-AB)
published by OCHA on the Humanitarian Data Exchange, dataset source
"Government of Sierra Leone", licence CC BY-IGO 3.0 (attribution required).
It reflects the 2017 reorganisation (16 districts incl. Falaba and Karene;
the source spells Falaba "Fabala").

The file is downloaded (or read from a local copy) by
``manage.py avdp_load_boundaries``; nothing is bundled in the repository.
"""

import json
import os
import re
import tempfile
import unicodedata

import requests
from osgeo import ogr, osr

from geonode_project.avdp import demo_package as dp
from geonode_project.avdp.styles import FONT, STYLE_MARKER

HDX_DATASET = "https://data.humdata.org/dataset/cod-ab-sle"
HDX_SHP_ZIP = (
    "https://data.humdata.org/dataset/a4816317-a913-4619-b1e9-d89e21c056b4/resource/"
    "deacde79-fe3e-4113-9b26-87c4b6c17d35/download/sle_admin_boundaries.shp.zip"
)
LICENCE = "Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO 3.0)"
ATTRIBUTION = "Government of Sierra Leone; OCHA (Humanitarian Data Exchange, COD-AB)"
EXPECTED_DISTRICTS = 16
SLE_ENVELOPE = (-13.6, 6.7, -10.0, 10.2)

DATASET_NAME = "avdp_sle_districts"
MARKER = "avdp-boundaries-adm2"

# Alternative spellings in circulation -> one key per district
ALIASES = {
    "fabala": "falaba",
    "westernurban": "westernareaurban",
    "freetown": "westernareaurban",
    "westernrural": "westernarearural",
}


class BoundaryError(Exception):
    pass


def district_key(name):
    """Normalise a district name for matching ("Western Area Urban" == "western urban")."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\bdistrict\b", "", text)
    text = re.sub(r"[^a-z]", "", text)
    return ALIASES.get(text, text)


def fetch(source, work_dir):
    """Return a local path for ``source`` (URL or path). Downloads to work_dir."""
    if re.match(r"^https?://", source):
        target = os.path.join(work_dir, "boundaries_download.zip")
        with requests.get(source, stream=True, timeout=120) as response:
            response.raise_for_status()
            size = 0
            with open(target, "wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > 200 * 1024 * 1024:
                        raise BoundaryError("Download larger than 200 MB; refusing.")
                    handle.write(chunk)
        return target
    if not os.path.exists(source):
        raise BoundaryError(f"Boundary source not found: {source}")
    return source


def find_adm2(path, work_dir):
    """Locate the admin-2 polygon layer in a zip, folder or single file."""
    if path.lower().endswith(".zip"):
        folder = os.path.join(work_dir, "extracted")
        # Only the admin-2 files are extracted (and checked); the archive also
        # holds other levels and padded line tables we do not need.
        dp.safe_extract(path, folder, include=lambda n: _is_adm2(os.path.basename(n)))
        path = folder
    if os.path.isdir(path):
        candidates = [
            os.path.join(root, name)
            for root, _dirs, files in os.walk(path)
            for name in files
            if _is_adm2(name) and name.lower().endswith((".shp", ".geojson", ".json"))
        ]
        if len(candidates) != 1:
            raise BoundaryError(f"Expected one admin-2 layer, found: {candidates or 'none'}")
        return candidates[0]
    return path


def _is_adm2(filename):
    """sle_admin2.shp, ..._adm2.geojson etc.; not the '_em' (extended) or line variants."""
    stem = os.path.splitext(filename.lower())[0]
    return bool(re.search(r"adm(in)?2$", stem))


def _field(defn, *names):
    lower = {defn.GetFieldDefn(i).GetName().lower(): defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}
    return next((lower[n] for n in names if n in lower), None)


def prepare(source, work_dir=None):
    """Validate the admin-2 layer and write a clean GeoJSON named after DATASET_NAME.

    Returns (geojson_path, summary dict). Raises BoundaryError on any problem.
    """
    work_dir = work_dir or tempfile.mkdtemp(prefix="avdp_bnd_")
    layer_path = find_adm2(fetch(source, work_dir), work_dir)
    ds = ogr.Open(layer_path)
    if ds is None or ds.GetLayerCount() != 1:
        raise BoundaryError(f"Cannot read {layer_path} as a single vector layer.")
    layer = ds.GetLayer(0)
    defn = layer.GetLayerDefn()
    f_name = _field(defn, "adm2_name", "adm2_en", "shapename", "district")
    f_code = _field(defn, "adm2_pcode", "shapeid", "pcode")
    f_prov = _field(defn, "adm1_name", "adm1_en", "province")
    f_pcode = _field(defn, "adm1_pcode")
    f_valid = _field(defn, "valid_on", "date")
    if not f_name or not f_code:
        raise BoundaryError("Admin-2 layer lacks a district name or code field.")
    srs = layer.GetSpatialRef()
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = None
    if srs is not None:
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        if not srs.IsSame(wgs84):
            transform = osr.CoordinateTransformation(srs, wgs84)

    features, names = [], []
    for feature in layer:
        geom = feature.GetGeometryRef()
        if geom is None or geom.IsEmpty():
            raise BoundaryError(f"District {feature.GetField(f_name)} has no geometry.")
        geom = geom.Clone()
        if transform:
            geom.Transform(transform)
        if not geom.IsValid():
            geom = geom.MakeValid()
        minx, maxx, miny, maxy = geom.GetEnvelope()
        e = SLE_ENVELOPE
        if minx < e[0] or maxx > e[2] or miny < e[1] or maxy > e[3]:
            raise BoundaryError(f"District {feature.GetField(f_name)} lies outside Sierra Leone.")
        name = feature.GetField(f_name)
        display = "Falaba" if district_key(name) == "falaba" else name
        names.append(display)
        area = geom.Clone()
        area.Transform(osr.CoordinateTransformation(wgs84, _equal_area()))
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(geom.ExportToJson()),
                "properties": {
                    "district": display,
                    "district_source_name": name,
                    "district_pcode": feature.GetField(f_code),
                    "province": feature.GetField(f_prov) if f_prov else None,
                    "province_pcode": feature.GetField(f_pcode) if f_pcode else None,
                    "area_sqkm": round(area.GetArea() / 1e6, 1),
                    "valid_on": str(feature.GetField(f_valid)) if f_valid else None,
                },
            }
        )
    if len(features) != EXPECTED_DISTRICTS:
        raise BoundaryError(f"Expected {EXPECTED_DISTRICTS} districts, found {len(features)}: {names}")
    if len({district_key(n) for n in names}) != len(names):
        raise BoundaryError(f"Duplicate district names after normalisation: {names}")
    out = os.path.join(work_dir, f"{DATASET_NAME}.geojson")
    with open(out, "w") as handle:
        json.dump({"type": "FeatureCollection", "name": DATASET_NAME, "features": features}, handle)
    return out, {"districts": sorted(names), "source_layer": os.path.basename(layer_path)}


def _equal_area():
    srs = osr.SpatialReference()
    srs.ImportFromProj4("+proj=laea +lat_0=8.5 +lon_0=-11.8 +datum=WGS84 +units=m +no_defs")
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def build_boundary_sld(name, title="District boundaries", geometry="geom"):
    """Outline-only districts with a white casing and labels (no fill: sits over any layer)."""
    # Labels hang on one interior point per district and may cross tile edges
    # ("partials"), so each district is labelled once in a tiled map.
    label = f"""<TextSymbolizer><Geometry><ogc:Function name="interiorPoint"><ogc:PropertyName>{geometry}</ogc:PropertyName>
</ogc:Function></Geometry><Label><ogc:PropertyName>district</ogc:PropertyName></Label>
{FONT.format(size=12, weight="bold")}
<LabelPlacement><PointPlacement><AnchorPoint><AnchorPointX>0.5</AnchorPointX><AnchorPointY>0.5</AnchorPointY>
</AnchorPoint></PointPlacement></LabelPlacement>
<Halo><Radius>2.5</Radius><Fill><CssParameter name="fill">#ffffff</CssParameter>
<CssParameter name="fill-opacity">0.85</CssParameter></Fill></Halo>
<Fill><CssParameter name="fill">#4a3d6b</CssParameter></Fill>
<VendorOption name="autoWrap">90</VendorOption><VendorOption name="maxDisplacement">60</VendorOption>
<VendorOption name="goodnessOfFit">0.3</VendorOption><VendorOption name="partials">true</VendorOption>
</TextSymbolizer>"""
    outline = """<PolygonSymbolizer><Stroke><CssParameter name="stroke">#ffffff</CssParameter>
<CssParameter name="stroke-width">3.2</CssParameter><CssParameter name="stroke-opacity">0.8</CssParameter>
<CssParameter name="stroke-linejoin">round</CssParameter></Stroke></PolygonSymbolizer>
<PolygonSymbolizer><Stroke><CssParameter name="stroke">#5d4e86</CssParameter>
<CssParameter name="stroke-width">1.4</CssParameter><CssParameter name="stroke-dasharray">6 3</CssParameter>
<CssParameter name="stroke-linejoin">round</CssParameter></Stroke></PolygonSymbolizer>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer><Name>{name}</Name><UserStyle><Name>{name}</Name><Title>{title}</Title>
    <Abstract>Outlines with district names. {STYLE_MARKER}.</Abstract>
    <FeatureTypeStyle>
      <Rule><Name>District boundary</Name><Title>District boundary</Title>{outline}</Rule>
      <Rule><Name>Labels</Name><MaxScaleDenominator>6000000</MaxScaleDenominator>{label}
        <VendorOption name="inclusion">mapOnly</VendorOption></Rule>
    </FeatureTypeStyle>
  </UserStyle></NamedLayer>
</StyledLayerDescriptor>
"""
