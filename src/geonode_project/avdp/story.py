"""The "AVDP at district level" map story (a GeoNode/MapStore GeoStory).

A cover, an introduction, two immersive chapters whose text scrolls over a
live map (district summary, then water points by status) and a sources and
caveats section. Built in MapStore's GeoStory format: maps are story
resources referenced by id from section backgrounds.
"""

import uuid

from django.conf import settings

from geonode_project.avdp.dashboard import wms_layer

TITLE = "AVDP at district level"
MARKER = "avdp-district-story"


def _id():
    return str(uuid.uuid4())


def _map_resource(layers, center=(-11.8, 8.5), zoom=7):
    background = [
        dict(b, id=b.get("id") or f"{b['source']}__{i}", group="background")
        for i, b in enumerate(settings.MAPSTORE_BASELAYERS)
    ]
    return {
        "id": _id(),
        "type": "map",
        "data": {
            "projection": "EPSG:3857",
            "units": "m",
            "center": {"x": center[0], "y": center[1], "crs": "EPSG:4326"},
            "zoom": zoom,
            "maxExtent": [-20037508.34, -20037508.34, 20037508.34, 20037508.34],
            "layers": background + layers,
            "groups": [{"id": "Default", "title": "Default", "expanded": True}],
        },
    }


def _text(html):
    return {"id": _id(), "type": "text", "html": html}


def _column(html, background=None, align="left"):
    column = {
        "id": _id(),
        "type": "column",
        "align": align,
        "size": "small",
        "theme": "bright",
        "contents": [_text(html)],
    }
    if background:
        column["background"] = background
    return column


def _map_background(resource):
    return {"type": "map", "resourceId": resource["id"], "fit": "cover", "size": "full", "align": "center", "map": {}}


def build(summary, boundaries, water_points=None, synthetic=False):
    """Return the GeoStory data for the summary dataset (and optionally a water points dataset)."""
    resources = []
    summary_map = _map_resource([wms_layer(summary), wms_layer(boundaries)])
    resources.append(summary_map)
    notice = (
        f"<p><strong>{settings.AVDP_SYNTHETIC_NOTICE}</strong> The figures in this story include invented "
        "demonstration records and must not be reported.</p>"
        if synthetic
        else ""
    )
    sections = [
        {
            "id": _id(),
            "type": "title",
            "title": "Cover",
            "cover": True,
            "contents": [
                {
                    "id": _id(),
                    "type": "text",
                    "size": "large",
                    "align": "center",
                    "theme": "bright",
                    "html": f"<h1>{TITLE}</h1><p>Where the programme's mapped farms, water points, stores and "
                            "farmer groups are, district by district.</p>",
                    "background": _map_background(summary_map),
                }
            ],
        },
        {
            "id": _id(),
            "type": "paragraph",
            "title": "Introduction",
            "contents": [
                {
                    "id": _id(),
                    "type": "column",
                    "size": "full",
                    "align": "center",
                    "contents": [
                        _text(
                            "<p>This story walks through the AVDP GIS Portal's district summary: every mapped "
                            "feature counted in the official district it lies in. Scroll to move through it; the "
                            "maps are live and show only data you are allowed to see.</p>" + notice
                        )
                    ],
                }
            ],
        },
        {
            "id": _id(),
            "type": "immersive",
            "title": "Districts",
            "contents": [
                _column(
                    "<h2>Features per district</h2><p>Darker districts hold more AVDP features across all seven "
                    "categories. Pale districts have none recorded yet, which may mean no activity or simply "
                    "no data uploaded.</p>",
                    _map_background(summary_map),
                ),
            ],
        },
    ]
    if water_points is not None:
        water_map = _map_resource([wms_layer(boundaries), wms_layer(water_points)])
        resources.append(water_map)
        sections[-1]["contents"].append(
            _column(
                "<h2>Water points by status</h2><p>Each symbol is a water point: blue working, amber needing "
                "repair, red not working. Open the dataset to see each point's details.</p>",
                _map_background(water_map),
            )
        )
    sections.append(
        {
            "id": _id(),
            "type": "paragraph",
            "title": "Sources",
            "contents": [
                {
                    "id": _id(),
                    "type": "column",
                    "size": "full",
                    "align": "center",
                    "contents": [
                        _text(
                            "<h2>Sources and caveats</h2><ul><li>District boundaries: Government of Sierra Leone, "
                            "published by OCHA on the Humanitarian Data Exchange (CC BY-IGO).</li><li>Counts are "
                            "numbers of mapped features, not people, households or hectares.</li><li>Only datasets "
                            "shared with AVDP Viewers or the public are counted.</li></ul>" + notice
                        )
                    ],
                }
            ],
        }
    )
    return {
        "type": "cascade",
        "resources": resources,
        "settings": {"theme": {"fontFamilies": []}, "storyTitle": TITLE},
        "sections": sections,
    }
