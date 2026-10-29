"""Builds the saved-map payload for "AVDP Agriculture — Synthetic Demonstration".

The payload is posted to GeoNode's maps API (``/api/v2/maps``), the same
endpoint the map viewer uses when a user saves a map, so the map is a normal
GeoNode resource with MapLayer records, permissions and a catalogue entry.
"""

import uuid

from django.conf import settings

MAP_TITLE = "AVDP Agriculture — Synthetic Demonstration"
MAP_MARKER = "avdp-demo-map"


def _layer(spec, dataset, ows_url):
    x0, y0, x1, y1 = dataset.ll_bbox_polygon.extent
    return {
        "id": str(uuid.uuid4()),
        "type": "wms",
        "name": dataset.alternate,
        "title": dataset.title,
        "url": ows_url,
        "format": "image/png",
        "visibility": spec.initially_visible,
        "opacity": 1,
        "singleTile": False,
        "tiled": True,
        "style": dataset.default_style.name if dataset.default_style else "",
        "search": {"type": "wfs", "url": ows_url},
        "bbox": {"crs": "EPSG:4326", "bounds": {"minx": x0, "miny": y0, "maxx": x1, "maxy": y1}},
        # Show identify results as an attribute table rather than plain text.
        "featureInfo": {"format": "PROPERTIES"},
        "extendedParams": {"pk": str(dataset.pk)},
        "group": "Default",
    }


def build_map_payload(spec_datasets):
    """spec_datasets: ordered list of (LayerSpec, Dataset), bottom-most first."""
    ows_url = settings.GEOSERVER_PUBLIC_LOCATION.rstrip("/") + "/ows"
    datasets = [d for _, d in spec_datasets]
    minx, miny, maxx, maxy = (
        min(d.ll_bbox_polygon.extent[0] for d in datasets),
        min(d.ll_bbox_polygon.extent[1] for d in datasets),
        max(d.ll_bbox_polygon.extent[2] for d in datasets),
        max(d.ll_bbox_polygon.extent[3] for d in datasets),
    )
    background = [dict(b, id=b.get("id") or f"{b['source']}__{i}") for i, b in enumerate(settings.MAPSTORE_BASELAYERS)]
    # Polygons first (bottom), then lines, then points on top.
    order = {"polygon": 0, "line": 1, "point": 2}
    ordered = sorted(
        spec_datasets,
        key=lambda sd: order[sd[0].geometry[-1] if sd[0].key == "demonstration_plots" else sd[0].geometry[0]],
    )
    layers = [_layer(spec, ds, ows_url) for spec, ds in ordered]
    blob = {
        "version": 2,
        "map": {
            "projection": "EPSG:900913",
            "units": "m",
            "center": {"x": (minx + maxx) / 2, "y": (miny + maxy) / 2, "crs": "EPSG:4326"},
            "zoom": 8,
            "maxExtent": [-20037508.34, -20037508.34, 20037508.34, 20037508.34],
            "mapOptions": {},
            "bbox": {"bounds": {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}, "crs": "EPSG:4326"},
            "groups": [{"id": "Default", "title": "Default", "expanded": True}],
            "layers": background + layers,
        },
        "catalogServices": {},
        "widgetsConfig": {"layouts": {"md": [], "xxs": []}},
        "mapInfoConfiguration": {"trigger": "click", "infoFormat": "application/json"},
    }
    maplayers = [
        {
            "extra_params": {"msId": layer["id"]},
            "current_style": layer["style"],
            "name": layer["name"],
            "order": index,
            "visibility": layer["visibility"],
            "opacity": 1,
        }
        for index, layer in enumerate(layers)
    ]
    return {"title": MAP_TITLE, "data": blob, "maplayers": maplayers}
