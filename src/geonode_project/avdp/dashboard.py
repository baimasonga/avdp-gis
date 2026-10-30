"""The AVDP district overview dashboard (a GeoNode/MapStore dashboard).

Widgets read the district summary layer (``avdp_district_summary``) through
GeoServer WFS/WPS in the viewer's own session, so they show exactly what the
viewer may see. Layout: 6-column MapStore grid.

Chart widgets use MapStore's multi-trace format (``charts[].traces[]``).
"""

import uuid

from django.conf import settings

from geonode_project.avdp import districts

TITLE = "AVDP district overview"
MARKER = "avdp-district-dashboard"
FOREST, NAVY, OCHRE = "#1f5d3a", "#0d2b45", "#c98a1b"


def _id():
    return str(uuid.uuid4())


def wms_layer(dataset, visibility=True, style=None):
    ows = settings.GEOSERVER_PUBLIC_LOCATION.rstrip("/") + "/ows"
    x0, y0, x1, y1 = dataset.ll_bbox_polygon.extent
    layer = {
        "id": f"{dataset.alternate}__{_id()[:8]}",
        "type": "wms",
        "name": dataset.alternate,
        "title": dataset.title,
        "url": ows,
        "format": "image/png",
        "visibility": visibility,
        "opacity": 1,
        "tiled": True,
        "style": style or (dataset.default_style.name if dataset.default_style else ""),
        "search": {"type": "wfs", "url": ows},
        "bbox": {"crs": "EPSG:4326", "bounds": {"minx": x0, "miny": y0, "maxx": x1, "maxy": y1}},
        "extendedParams": {"pk": str(dataset.pk)},
    }
    if dataset.use_featureinfo_custom_template and dataset.featureinfo_custom_template:
        layer["featureInfo"] = {"format": "TEMPLATE", "template": dataset.featureinfo_custom_template}
    return layer


def _grid(widget, x, y, w, h):
    widget["dataGrid"] = {"x": x, "y": y, "w": w, "h": h}
    return widget


def text_widget(html, title=""):
    return {"id": _id(), "widgetType": "text", "title": title, "text": html, "dependenciesMap": {}}


def counter_widget(layer, column, title, description=""):
    return {
        "id": _id(),
        "widgetType": "counter",
        "title": title,
        "description": description,
        "layer": layer,
        "options": {"aggregateFunction": "Sum", "aggregationAttribute": column},
        "mapSync": False,
        "dependenciesMap": {},
    }


def chart_widget(layer, title, group_by, value, colour=FOREST, chart_type="bar", description="", angle=-45):
    chart_id, trace_id = _id(), _id()
    trace = {
        "id": trace_id,
        "type": chart_type,
        "name": title,
        "layer": layer,
        "geomProp": "geom",
        "options": {"groupByAttributes": group_by, "aggregationAttribute": value, "aggregateFunction": "Sum"},
    }
    if chart_type == "bar":
        trace["style"] = {"msMode": "simple", "line": {"color": "rgb(0, 0, 0)", "width": 0}, "marker": {"color": colour}}
    else:
        trace["style"] = {"msClassification": {"method": "uniqueInterval", "intervals": 5, "reverse": False, "ramp": "greens"}}
    return {
        "id": _id(),
        "widgetType": "chart",
        "title": title,
        "description": description,
        "selectedChartId": chart_id,
        "selectedTraceId": trace_id,
        "mapSync": False,
        "dependenciesMap": {},
        "charts": [
            {
                "chartId": chart_id,
                "name": title,
                "legend": chart_type != "bar",
                "cartesian": True,
                "xAxisOpts": [{"id": 0, "angle": angle}],
                "yAxisOpts": [{"id": 0}],
                "traces": [trace],
            }
        ],
    }


def map_widget(layers, title):
    map_id = _id()
    background = [
        dict(b, id=b.get("id") or f"{b['source']}__{i}", group="background")
        for i, b in enumerate(settings.MAPSTORE_BASELAYERS)
    ]
    return {
        "id": _id(),
        "widgetType": "map",
        "title": title,
        "selectedMapId": map_id,
        "mapSync": False,
        "dependenciesMap": {},
        "maps": [
            {
                "mapId": map_id,
                "projection": "EPSG:3857",
                "units": "m",
                "center": {"x": -11.8, "y": 8.5, "crs": "EPSG:4326"},
                "zoom": 7,
                "maxExtent": [-20037508.34, -20037508.34, 20037508.34, 20037508.34],
                "layers": background + layers,
                "groups": [{"id": "Default", "title": "Default", "expanded": True}],
            }
        ],
    }


def table_widget(layer, columns, title):
    return {
        "id": _id(),
        "widgetType": "table",
        "title": title,
        "layer": layer,
        "options": {"propertyName": columns},
        "mapSync": False,
        "dependenciesMap": {},
    }


def build(summary, boundaries, synthetic):
    """Return the dashboard data (widgets + layouts) for the summary dataset."""
    layer = wms_layer(summary)
    # Readable column titles in the table widget
    layer["fields"] = [
        {"name": "district", "alias": "District", "type": "string"},
        {"name": "province", "alias": "Province", "type": "string"},
        *[{"name": c, "alias": label, "type": "number"} for _k, c, label in districts.CATEGORY_COLUMNS],
        {"name": "total_features", "alias": "All features", "type": "number"},
    ]
    cols = districts.CATEGORY_COLUMNS
    notice = (
        f'<p style="margin:0"><strong>{settings.AVDP_SYNTHETIC_NOTICE}</strong> '
        "Figures include invented demonstration records and must not be reported.</p>"
        if synthetic
        else ""
    )
    intro = text_widget(
        "<p style=\"margin:0 0 6px 0\">Features recorded in the AVDP GIS Portal per district, counted by location "
        "against the official district boundaries (Government of Sierra Leone / OCHA, CC BY-IGO). Counts are "
        "features, not people or hectares. Only datasets shared with AVDP Viewers or the public are counted, so "
        "the figures reveal no private data. Source layer: <em>District summary</em> (refreshed by an "
        "administrator with <code>avdp_district_summary</code>).</p>" + notice,
        "About these figures",
    )
    widgets = [_grid(intro, 0, 0, 6, 1)]
    counters = [
        ("total_features", "All AVDP features"),
        ("water_infrastructure", "Water infrastructure"),
        ("farmer_organizations", "Farmer organizations"),
    ]
    for i, (column, title) in enumerate(counters):
        widgets.append(_grid(counter_widget(layer, column, title, "Sum over all districts"), i * 2, 1, 2, 1))
    map_layers = [wms_layer(summary), wms_layer(boundaries)]
    widgets.append(_grid(map_widget(map_layers, "Features per district (map)"), 0, 2, 3, 3))
    widgets.append(
        _grid(
            chart_widget(layer, "Features per district", "district", "total_features", FOREST,
                         description="All AVDP categories, by district"),
            3, 2, 3, 3,
        )
    )
    widgets.append(
        _grid(
            chart_widget(layer, "Features per province", "province", "total_features", NAVY,
                         description="Sum of the district counts in each province", angle=0),
            0, 5, 2, 2,
        )
    )
    widgets.append(
        _grid(
            table_widget(
                layer,
                ["district", "province", *[c for _k, c, _l in cols], "total_features"],
                "District table",
            ),
            2, 5, 4, 2,
        )
    )
    layouts = {
        "md": [
            {"i": w["id"], **w["dataGrid"], "moved": False, "static": False} for w in widgets
        ],
        "xxs": [
            {"i": w["id"], "x": 0, "y": i * 2, "w": 1, "h": w["dataGrid"]["h"], "moved": False, "static": False}
            for i, w in enumerate(widgets)
        ],
    }
    return {"widgets": widgets, "layouts": layouts, "version": 1}
