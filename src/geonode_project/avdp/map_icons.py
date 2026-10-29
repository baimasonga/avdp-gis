"""Publish the AVDP map icons to GeoServer.

The SVGs in ``static/avdp/map-icons`` are parametric (``param(fill)``), so a
single icon can be drawn in any class colour from an SLD, e.g.
``avdp_icons/water.svg?fill=%231d6fa5``. They are uploaded into the GeoNode
workspace style directory through GeoServer's REST resource API, where
workspace styles resolve the relative ``avdp_icons/...`` path. Re-uploading is
harmless (PUT overwrites the same files).
"""

import os

import requests
from django.conf import settings

from geonode_project.avdp.styles import ICONS

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "avdp", "map-icons")
REMOTE_DIR = "workspaces/{workspace}/styles/avdp_icons"


def publish_icons(workspace="geonode"):
    ogc = settings.OGC_SERVER["default"]
    base = ogc["LOCATION"].rstrip("/")
    auth = (ogc["USER"], ogc["PASSWORD"])
    published = []
    for icon in ICONS:
        with open(os.path.join(ICON_DIR, f"{icon}.svg"), "rb") as handle:
            response = requests.put(
                f"{base}/rest/resource/{REMOTE_DIR.format(workspace=workspace)}/{icon}.svg",
                data=handle.read(),
                headers={"Content-Type": "image/svg+xml"},
                auth=auth,
                timeout=30,
            )
        response.raise_for_status()
        published.append(icon)
    return published
