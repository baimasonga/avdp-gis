"""Cartographic SLD 1.0 styles for the AVDP thematic layers.

Design rules (see docs/ARCHITECTURE.md, "Cartography"):

* Each theme has its own symbol: points use badge icons with a white
  pictogram (parametric SVGs published to GeoServer by
  ``avdp.map_icons``), roads are cased lines, farm plots are filled
  polygons and demonstration plots are hatched polygons.
* Colour carries one meaning per layer: either a *status* (semantic
  traffic-light colours, consistent across layers) or a *category*
  (an earthy qualitative palette; known crops have fixed colours).
* Three scale bands keep the map readable: national overview (small
  symbols, small polygons drawn as dots at their centroid), regional, and
  local (full-size symbols plus labels with a halo).
"""

from xml.sax.saxutils import escape

# Scale bands (scale denominators)
OVERVIEW = 1_500_000  # coarser than this: national overview
LOCAL = 150_000  # finer than this: labels

# Semantic status colours (shared by all layers)
STATUS_GOOD = "#2f7d4a"
STATUS_WARN = "#d08c17"
STATUS_BAD = "#b03a2e"
STATUS_NEUTRAL = "#7d8790"
STATUS_WORDS = {
    STATUS_GOOD: ("functional", "good", "operational", "active", "complete", "completed", "working", "yes"),
    STATUS_WARN: ("repair", "fair", "partial", "construction", "planned", "maintenance", "pending"),
    STATUS_BAD: (
        "not functional",
        "non-functional",
        "nonfunctional",
        "broken",
        "poor",
        "inactive",
        "closed",
        "abandoned",
        "no",
    ),
}

# Fixed colours for common crops (earthy, agricultural)
# Qualitative palette for categories. It deliberately avoids the status hues
# (green / amber / red) so colour never suggests a condition it doesn't mean.
CATEGORY_PALETTE = ["#2a6f97", "#7b6aa6", "#3e9c8f", "#8a5a2b", "#a0527e", "#4b6b80", "#9a7b4f", "#5e8c9c"]
CROP_COLOURS = {
    "rice": "#7fb069",
    "cassava": "#c49b4a",
    "maize": "#e2c85c",
    "corn": "#e2c85c",
    "groundnut": "#b07a55",
    "groundnuts": "#b07a55",
    "cocoa": "#8b5e3c",
    "coffee": "#6f4e37",
    "vegetables": "#5aa36b",
    "sweet potato": "#d68a59",
    "oil palm": "#c97b2a",
}

FONT = """<Font><CssParameter name="font-family">Noto Sans</CssParameter>
<CssParameter name="font-family">DejaVu Sans</CssParameter><CssParameter name="font-family">SansSerif</CssParameter>
<CssParameter name="font-size">{size}</CssParameter><CssParameter name="font-weight">{weight}</CssParameter></Font>"""

# key -> symbol definition
SYMBOLS = {
    "farm_plots": {"kind": "polygon", "colour": "#7fb069", "mode": "crop"},
    "demonstration_plots": {"kind": "hatch", "colour": "#1b7f79", "icon": "sprout", "mode": "category"},
    "feeder_roads": {"kind": "road", "colour": "#5b6770", "mode": "status"},
    "farmer_groups": {"kind": "icon", "icon": "group", "colour": "#2f6b3c", "mode": "category"},
    "water_points": {"kind": "icon", "icon": "water", "colour": "#1d6fa5", "mode": "status", "good_colour": "#1d6fa5"},
    "grain_stores": {"kind": "icon", "icon": "store", "colour": "#8a5a2b", "mode": "status", "good_colour": "#8a5a2b"},
    "distribution_sites": {"kind": "icon", "icon": "sack", "colour": "#b0731c", "mode": "category"},
}
ICONS = ("water", "store", "group", "sack", "sprout")

LABEL_FIELDS = ("name", "site_name", "group_name", "store_name", "label", "title")

HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>{name}</Name>
    <UserStyle>
      <Name>{name}</Name>
      <Title>{title}</Title>
{fts}
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""


def status_colour(value, good_colour=STATUS_GOOD):
    """Map a status-like value to a semantic colour (most specific match wins)."""
    v = str(value).strip().lower()
    for colour in (STATUS_BAD, STATUS_WARN, STATUS_GOOD):  # "not functional" before "functional"
        if any(word == v or word in v for word in STATUS_WORDS[colour] if len(word) > 2 or word == v):
            return good_colour if colour == STATUS_GOOD else colour
    return None


def colours_for(key, values):
    """Return [(value, colour)] for the categorised field of a layer."""
    sym = SYMBOLS[key]
    result, palette = [], iter(CATEGORY_PALETTE * 3)
    for value in values:
        colour = None
        if sym["mode"] == "status":
            colour = status_colour(value, sym.get("good_colour", STATUS_GOOD))
        elif sym["mode"] == "crop":
            colour = CROP_COLOURS.get(str(value).strip().lower())
        result.append((value, colour or next(palette)))
    return result


# ---------------------------------------------------------------------------
# Symbolizers
# ---------------------------------------------------------------------------
def _centroid(geometry):
    return (
        f'<Geometry><ogc:Function name="centroid"><ogc:PropertyName>{geometry}</ogc:PropertyName>'
        "</ogc:Function></Geometry>"
    )


def _icon(icon, colour, size, geometry=None):
    href = f"avdp_icons/{icon}.svg?fill={colour.replace('#', '%23')}"
    geom = _centroid(geometry) if geometry else ""
    return f"""<PointSymbolizer>{geom}<Graphic><ExternalGraphic>
<OnlineResource xlink:type="simple" xlink:href="{href}"/><Format>image/svg+xml</Format>
</ExternalGraphic><Size>{size}</Size></Graphic></PointSymbolizer>"""


def _dot(colour, size, geometry=None):
    geom = _centroid(geometry) if geometry else ""
    return f"""<PointSymbolizer>{geom}<Graphic><Mark><WellKnownName>circle</WellKnownName>
<Fill><CssParameter name="fill">{colour}</CssParameter></Fill>
<Stroke><CssParameter name="stroke">#ffffff</CssParameter><CssParameter name="stroke-width">0.8</CssParameter></Stroke>
</Mark><Size>{size}</Size></Graphic></PointSymbolizer>"""


def _polygon(colour, opacity=0.72):
    return f"""<PolygonSymbolizer><Fill><CssParameter name="fill">{colour}</CssParameter>
<CssParameter name="fill-opacity">{opacity}</CssParameter></Fill>
<Stroke><CssParameter name="stroke">{_darken(colour)}</CssParameter><CssParameter name="stroke-width">1</CssParameter>
</Stroke></PolygonSymbolizer>"""


def _hatch(colour):
    return f"""<PolygonSymbolizer><Fill><CssParameter name="fill">#ffffff</CssParameter>
<CssParameter name="fill-opacity">0.55</CssParameter></Fill></PolygonSymbolizer>
<PolygonSymbolizer><Fill><GraphicFill><Graphic><Mark><WellKnownName>shape://slash</WellKnownName>
<Stroke><CssParameter name="stroke">{colour}</CssParameter><CssParameter name="stroke-width">1.2</CssParameter></Stroke>
</Mark><Size>7</Size></Graphic></GraphicFill></Fill>
<Stroke><CssParameter name="stroke">{colour}</CssParameter><CssParameter name="stroke-width">1.6</CssParameter>
</Stroke></PolygonSymbolizer>"""


def _road(colour, width, dashed, casing):
    dash = '<CssParameter name="stroke-dasharray">7 4</CssParameter>' if dashed else ""
    return f"""<LineSymbolizer><Stroke><CssParameter name="stroke">#ffffff</CssParameter>
<CssParameter name="stroke-width">{casing}</CssParameter><CssParameter name="stroke-linecap">round</CssParameter>
<CssParameter name="stroke-linejoin">round</CssParameter></Stroke></LineSymbolizer>
<LineSymbolizer><Stroke><CssParameter name="stroke">{colour}</CssParameter>
<CssParameter name="stroke-width">{width}</CssParameter><CssParameter name="stroke-linecap">round</CssParameter>
<CssParameter name="stroke-linejoin">round</CssParameter>{dash}</Stroke></LineSymbolizer>"""


def _darken(hex_colour, factor=0.7):
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(int(r * factor), int(g * factor), int(b * factor))


def _scale(min_scale=None, max_scale=None):
    out = ""
    if min_scale:
        out += f"<MinScaleDenominator>{min_scale}</MinScaleDenominator>"
    if max_scale:
        out += f"<MaxScaleDenominator>{max_scale}</MaxScaleDenominator>"
    return out


def _filter(field, value):
    if field is None:
        return ""
    if value is None:
        return "<ElseFilter/>"
    return (
        "<ogc:Filter><ogc:PropertyIsEqualTo>"
        f"<ogc:PropertyName>{escape(field)}</ogc:PropertyName><ogc:Literal>{escape(str(value))}</ogc:Literal>"
        "</ogc:PropertyIsEqualTo></ogc:Filter>"
    )


def _rule(title, body, flt="", scale="", inclusion=None):
    """inclusion: None (map and legend), "mapOnly" or "legendOnly" (GeoServer vendor option)."""
    vendor = f'<VendorOption name="inclusion">{inclusion}</VendorOption>' if inclusion else ""
    return f"""        <Rule><Name>{escape(title)}</Name><Title>{escape(title)}</Title>{flt}{scale}
{body}
{vendor}
        </Rule>"""


def _bands(key, colour, dashed=False, geometry="geom"):
    """Map-only rules for one class: [(min_scale, max_scale, symbolizers)].

    Small polygons (farm/demonstration plots) would vanish at national scale,
    so at overview scales they are drawn as a marker at their centroid.
    """
    sym = SYMBOLS[key]
    kind = sym["kind"]
    if kind == "icon":
        return [
            (OVERVIEW, None, _icon(sym["icon"], colour, 13)),
            (LOCAL, OVERVIEW, _icon(sym["icon"], colour, 19)),
            (None, LOCAL, _icon(sym["icon"], colour, 26)),
        ]
    if kind == "road":
        return [
            (OVERVIEW, None, _road(colour, 1.8, dashed, 3.6)),
            (LOCAL, OVERVIEW, _road(colour, 2.8, dashed, 5)),
            (None, LOCAL, _road(colour, 4, dashed, 6.5)),
        ]
    if kind == "polygon":
        return [(OVERVIEW, None, _dot(colour, 6, geometry)), (None, OVERVIEW, _polygon(colour))]
    return [
        (OVERVIEW, None, _icon(sym.get("icon", "sprout"), colour, 14, geometry)),
        (None, OVERVIEW, _hatch(colour)),
    ]


def _legend_symbol(key, colour, dashed=False):
    sym = SYMBOLS[key]
    kind = sym["kind"]
    if kind == "icon":
        return _icon(sym["icon"], colour, 20)
    if kind == "road":
        return _road(colour, 3, dashed, 5.5)
    return _polygon(colour) if kind == "polygon" else _hatch(colour)


def _labels(kind, label_field, colour):
    if not label_field:
        return ""
    placement = (
        "<LabelPlacement><PointPlacement><AnchorPoint><AnchorPointX>0.5</AnchorPointX>"
        "<AnchorPointY>0</AnchorPointY></AnchorPoint><Displacement><DisplacementX>0</DisplacementX>"
        "<DisplacementY>15</DisplacementY></Displacement></PointPlacement></LabelPlacement>"
        if kind == "icon"
        else (
            "<LabelPlacement><LinePlacement><PerpendicularOffset>0</PerpendicularOffset></LinePlacement>"
            "</LabelPlacement>"
            if kind == "road"
            else ""
        )
    )
    vendor = (
        '<VendorOption name="followLine">true</VendorOption><VendorOption name="maxAngleDelta">30</VendorOption>'
        '<VendorOption name="repeat">300</VendorOption>'
        if kind == "road"
        else '<VendorOption name="autoWrap">110</VendorOption><VendorOption name="goodnessOfFit">0</VendorOption>'
    )
    return f"""<TextSymbolizer><Label><ogc:PropertyName>{escape(label_field)}</ogc:PropertyName></Label>
{FONT.format(size=11, weight="bold" if kind != "polygon" else "normal")}{placement}
<Halo><Radius>2</Radius><Fill><CssParameter name="fill">#ffffff</CssParameter>
<CssParameter name="fill-opacity">0.9</CssParameter></Fill></Halo>
<Fill><CssParameter name="fill">{_darken(colour, 0.55)}</CssParameter></Fill>
<VendorOption name="spaceAround">4</VendorOption>{vendor}</TextSymbolizer>"""


def build_sld(key, name, title, families=None, field=None, values=(), label_field=None, geometry="geom"):
    """Return the SLD for one AVDP layer.

    field/values: attribute used for colour classes (optional).
    label_field: attribute used for labels at local scale (optional).
    geometry: geometry column name (used for centroid markers).
    """
    sym = SYMBOLS[key]
    classes = colours_for(key, values) if field and values else [(None, sym["colour"])]
    rules = []
    for value, colour in classes:
        dashed = sym["kind"] == "road" and colour == STATUS_BAD
        title_text = str(value) if value is not None else title
        flt = _filter(field, value) if field else ""
        rules.append(_rule(title_text, _legend_symbol(key, colour, dashed), flt, inclusion="legendOnly"))
        for min_s, max_s, body in _bands(key, colour, dashed, geometry):
            rules.append(_rule(title_text, body, flt, _scale(min_s, max_s), inclusion="mapOnly"))
    if field and values:
        # Anything not covered by the classes above
        other = "Other / not recorded"
        rules.append(_rule(other, _legend_symbol(key, STATUS_NEUTRAL), "<ElseFilter/>", inclusion="legendOnly"))
        for min_s, max_s, body in _bands(key, STATUS_NEUTRAL, False, geometry):
            rules.append(_rule(other, body, "<ElseFilter/>", _scale(min_s, max_s), inclusion="mapOnly"))

    fts = ["      <FeatureTypeStyle>\n" + "\n".join(rules) + "\n      </FeatureTypeStyle>"]
    label_colour = sym["colour"]
    if label_field:
        fts.append(
            "      <FeatureTypeStyle>\n"
            + _rule(
                "Labels",
                _labels(sym["kind"] if sym["kind"] != "hatch" else "polygon", label_field, label_colour),
                "",
                _scale(None, LOCAL),
                inclusion="mapOnly",
            )
            + "\n      </FeatureTypeStyle>"
        )
    return HEADER.format(name=escape(name), title=escape(title), fts="\n".join(fts))


def label_field_for(fields):
    lower = {f.lower(): f for f in fields}
    return next((lower[f] for f in LABEL_FIELDS if f in lower), None)
