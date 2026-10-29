# -*- coding: utf-8 -*-
#########################################################################
#
# Copyright (C) 2017 OSGeo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

# Django settings for the GeoNode project.
import ast
import os
from urllib.parse import urlparse

# Load more settings from a file called local_settings.py if it exists
try:
    from geonode_project.local_settings import *
#    from geonode.local_settings import *
except ImportError:
    from geonode.settings import *

#
# General Django development settings
#
PROJECT_NAME = "geonode_project"

# add trailing slash to site url. geoserver url will be relative to this
if not SITEURL.endswith("/"):
    SITEURL = "{}/".format(SITEURL)

SITENAME = os.getenv("SITENAME", "geonode_project")

# Defines the directory that contains the settings file as the LOCAL_ROOT
# It is used for relative settings elsewhere.
LOCAL_ROOT = os.path.abspath(os.path.dirname(__file__))

WSGI_APPLICATION = "{}.wsgi.application".format(PROJECT_NAME)

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "en")

if PROJECT_NAME not in INSTALLED_APPS:
    INSTALLED_APPS += (PROJECT_NAME,)

# Location of url mappings
ROOT_URLCONF = os.getenv("ROOT_URLCONF", "{}.urls".format(PROJECT_NAME))

# Additional directories which hold static files
# - Give priority to local geonode-project ones
STATICFILES_DIRS = [
    os.path.join(LOCAL_ROOT, "static"),
] + STATICFILES_DIRS

# Location of locale files
LOCALE_PATHS = (os.path.join(LOCAL_ROOT, "locale"),) + LOCALE_PATHS

TEMPLATES[0]["DIRS"].insert(0, os.path.join(LOCAL_ROOT, "templates"))
loaders = TEMPLATES[0]["OPTIONS"].get("loaders") or [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]
# loaders.insert(0, 'apptemplates.Loader')
TEMPLATES[0]["OPTIONS"]["loaders"] = loaders
TEMPLATES[0].pop("APP_DIRS", None)


PROJECT_FIXTURES = [
    # List project-related fixture files here, in the order they should be loaded.
]


# ---------------------------------------------------------------------------
# AVDP GIS Portal customisations
# Keep project-specific settings below this line so upstream geonode-project
# changes above remain easy to merge.
# ---------------------------------------------------------------------------
SITENAME = os.getenv("SITENAME", "AVDP GIS Portal")

# Default view for new maps: Sierra Leone (EPSG:4326 centre, web-map zoom).
DEFAULT_MAP_CENTER_X = ast.literal_eval(os.getenv("DEFAULT_MAP_CENTER_X", "-11.78"))
DEFAULT_MAP_CENTER_Y = ast.literal_eval(os.getenv("DEFAULT_MAP_CENTER_Y", "8.56"))
DEFAULT_MAP_CENTER = (DEFAULT_MAP_CENTER_X, DEFAULT_MAP_CENTER_Y)
DEFAULT_MAP_ZOOM = int(os.getenv("DEFAULT_MAP_ZOOM", "7"))

# Background layers offered in the map viewer.
# Default: OpenStreetMap (no key; attribution shown; light use only under the
# OSM tile usage policy). For a muted cartographic basemap, set
# AVDP_BASEMAP_URL to an XYZ template from a provider you are licensed to use
# (e.g. a CARTO or MapTiler URL including your key, or your own tile server)
# and AVDP_BASEMAP_ATTRIBUTION to its required attribution; it then becomes
# the default background and the thumbnail background. See docs/DEPLOYMENT.md.
AVDP_BASEMAP_URL = os.getenv("AVDP_BASEMAP_URL", "").strip()
AVDP_BASEMAP_TITLE = os.getenv("AVDP_BASEMAP_TITLE", "Light basemap")
AVDP_BASEMAP_ATTRIBUTION = os.getenv("AVDP_BASEMAP_ATTRIBUTION", "")
if GEONODE_CLIENT_LAYER_PREVIEW_LIBRARY == "mapstore":
    MAPSTORE_BASELAYERS = []
    if AVDP_BASEMAP_URL:
        MAPSTORE_BASELAYERS.append(
            {
                "type": "tileprovider",
                "provider": "custom",
                "title": AVDP_BASEMAP_TITLE,
                "name": "avdp-basemap",
                "id": "avdp-basemap",
                "url": AVDP_BASEMAP_URL,
                "options": {"attribution": AVDP_BASEMAP_ATTRIBUTION, "maxZoom": 19},
                "group": "background",
                "visibility": True,
            }
        )
    MAPSTORE_BASELAYERS += [
        {
            "type": "osm",
            "title": "OpenStreetMap",
            "name": "mapnik",
            "source": "osm",
            "group": "background",
            "visibility": not AVDP_BASEMAP_URL,
        },
        {
            "source": "ol",
            "group": "background",
            "id": "none",
            "name": "empty",
            "title": "Empty Background",
            "type": "empty",
            "visibility": False,
            "args": ["Empty Background", {"visibility": False}],
        },
    ]

# Thumbnails use the same background as the viewer for a consistent catalogue.
if AVDP_BASEMAP_URL:
    THUMBNAIL_BACKGROUND = {
        "class": "geonode.thumbs.background.GenericXYZBackground",
        "options": {"url": AVDP_BASEMAP_URL.replace("{s}", "a"), "tile_size": 256},
    }

# When HTTPS is terminated by a proxy in front of nginx (GitHub Codespaces,
# a load balancer, Cloudflare), Django sees plain HTTP while browsers send an
# https:// Origin. Trust the portal's own public HTTPS origin so sign-in and
# other POSTs pass Django's CSRF origin check. Extra origins can be added with
# AVDP_CSRF_TRUSTED_ORIGINS (comma-separated, scheme included).
_public = urlparse(SITEURL)
CSRF_TRUSTED_ORIGINS = list(globals().get("CSRF_TRUSTED_ORIGINS", []))
if _public.scheme == "https" and _public.netloc:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_public.netloc}")
CSRF_TRUSTED_ORIGINS += [o.strip() for o in os.getenv("AVDP_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
CSRF_TRUSTED_ORIGINS = sorted(set(CSRF_TRUSTED_ORIGINS))

# Must run first so every later component sees the public scheme.
MIDDLEWARE = ("geonode_project.middleware.PublicSchemeMiddleware",) + tuple(
    m for m in MIDDLEWARE if m != "geonode_project.middleware.PublicSchemeMiddleware"
)

# Marker used to identify demonstration content created by `avdp_import_demo`.
AVDP_DEMO_KEYWORD = "avdp-synthetic-demo"
AVDP_SYNTHETIC_NOTICE = "SYNTHETIC DEMONSTRATION DATA — NOT OFFICIAL AVDP RECORDS."
