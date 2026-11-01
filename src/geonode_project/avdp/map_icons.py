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



PRINT_HEADER = os.path.join(os.path.dirname(ICON_DIR), "img", "print_header.png")
PRINTING_DIR = "/geoserver_data/data/printing"  # GeoServer data directory, mounted in the django container


def install_print_header(printing_dir=PRINTING_DIR):
    """Replace the GeoNode-branded header of GeoServer's print layouts with the AVDP text header.

    Copies the file straight into GeoServer's data directory (read at print
    time), so it works while GeoServer is still starting. The original is
    kept once as print_header.geonode.png. Returns False if the directory is
    not mounted here.
    """
    import shutil

    target = os.path.join(printing_dir, "print_header.png")
    if not os.path.isdir(printing_dir):
        return False
    backup = os.path.join(printing_dir, "print_header.geonode.png")
    if os.path.exists(target) and not os.path.exists(backup):
        shutil.copyfile(target, backup)
    shutil.copyfile(PRINT_HEADER, target)
    config = os.path.join(printing_dir, "config.yaml")
    if os.path.exists(config):
        with open(config) as handle:
            text = handle.read()
        renamed = text.replace("outputFilename: 'GeoNode-Map-${date}.pdf'", "outputFilename: 'AVDP-Map-${date}.pdf'")
        if renamed != text:
            with open(config, "w") as handle:
                handle.write(renamed)
    return True
