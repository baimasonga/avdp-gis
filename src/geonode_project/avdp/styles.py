"""SLD 1.0 styles for the AVDP demonstration layers.

Each layer gets a distinct symbol so point, line and polygon layers can be
told apart on one map. When a suitable attribute exists (crop, status, ...)
the layer is categorised by it, using a colour-blind-safe palette.
"""

from xml.sax.saxutils import escape

# Okabe-Ito palette (colour-blind safe), reordered to start with blue/green.
PALETTE = ["#0072B2", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#7F7F7F"]

# key -> base symbol definition
SYMBOLS = {
    "farm_plots": {"kind": "polygon", "fill": "#7fbf7b", "stroke": "#1b5e20", "opacity": 0.55},
    "demonstration_plots": {
        "kind": "polygon",
        "fill": "#9ecae1",
        "stroke": "#08519c",
        "opacity": 0.5,
        "point_mark": "star",
        "point_fill": "#08519c",
    },
    "feeder_roads": {"kind": "line", "stroke": "#8c510a", "width": 3},
    "farmer_groups": {"kind": "point", "mark": "circle", "fill": "#2e6b34", "size": 10},
    "water_points": {"kind": "point", "mark": "triangle", "fill": "#1d5a8e", "size": 12},
    "grain_stores": {"kind": "point", "mark": "square", "fill": "#b26a00", "size": 11, "polygon_fill": "#f6c26b"},
    "distribution_sites": {"kind": "point", "mark": "cross", "fill": "#6a3d9a", "size": 12},
}

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
      <FeatureTypeStyle>
{rules}
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
"""


def _point(mark, fill, size):
    return f"""<PointSymbolizer><Graphic><Mark><WellKnownName>{mark}</WellKnownName>
<Fill><CssParameter name="fill">{fill}</CssParameter></Fill>
<Stroke><CssParameter name="stroke">#ffffff</CssParameter><CssParameter name="stroke-width">1.2</CssParameter></Stroke>
</Mark><Size>{size}</Size></Graphic></PointSymbolizer>"""


def _line(stroke, width):
    return f"""<LineSymbolizer><Stroke><CssParameter name="stroke">#ffffff</CssParameter>
<CssParameter name="stroke-width">{width + 2}</CssParameter><CssParameter name="stroke-linecap">round</CssParameter></Stroke></LineSymbolizer>
<LineSymbolizer><Stroke><CssParameter name="stroke">{stroke}</CssParameter>
<CssParameter name="stroke-width">{width}</CssParameter><CssParameter name="stroke-linecap">round</CssParameter></Stroke></LineSymbolizer>"""


def _polygon(fill, stroke, opacity):
    return f"""<PolygonSymbolizer><Fill><CssParameter name="fill">{fill}</CssParameter>
<CssParameter name="fill-opacity">{opacity}</CssParameter></Fill>
<Stroke><CssParameter name="stroke">{stroke}</CssParameter><CssParameter name="stroke-width">1.2</CssParameter></Stroke>
</PolygonSymbolizer>"""


def _symbolizers(key, families, colour=None):
    sym = SYMBOLS[key]
    out = []
    if "polygon" in families:
        fill = colour or sym.get("polygon_fill") or sym.get("fill")
        out.append(_polygon(fill, sym.get("stroke", "#333333"), sym.get("opacity", 0.6)))
    if "line" in families:
        out.append(_line(colour or sym["stroke"], sym.get("width", 2)))
    if "point" in families:
        out.append(
            _point(
                sym.get("mark") or sym.get("point_mark", "circle"),
                colour or sym.get("fill") or sym.get("point_fill"),
                sym.get("size", 10),
            )
        )
    return "\n".join(out)


def _rule(title, body, filter_xml=""):
    return f"""        <Rule>
          <Name>{escape(title)}</Name>
          <Title>{escape(title)}</Title>
          {filter_xml}
          {body}
        </Rule>"""


def build_sld(key, name, title, families, field=None, values=()):
    """Return an SLD string for a layer.

    families: geometry families present in the data ("point", "line", "polygon").
    field/values: optional attribute to categorise by.
    """
    families = set(families) or {SYMBOLS[key]["kind"]}
    rules = []
    if field and values:
        for i, value in enumerate(values):
            colour = PALETTE[i % len(PALETTE)]
            flt = (
                "<ogc:Filter><ogc:PropertyIsEqualTo>"
                f"<ogc:PropertyName>{escape(field)}</ogc:PropertyName><ogc:Literal>{escape(value)}</ogc:Literal>"
                "</ogc:PropertyIsEqualTo></ogc:Filter>"
            )
            rules.append(_rule(f"{value}", _symbolizers(key, families, colour), flt))
        rules.append(_rule("Other / not recorded", _symbolizers(key, families, "#bdbdbd"), "<ElseFilter/>"))
    else:
        rules.append(_rule(title, _symbolizers(key, families)))
    return HEADER.format(name=escape(name), title=escape(title), rules="\n".join(rules))
