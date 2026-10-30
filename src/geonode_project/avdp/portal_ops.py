"""Shared steps for AVDP management commands: upload, sharing, thumbnails.

Everything goes through GeoNode's own APIs (importer, resource managers,
permission specs), as a signed-in user would.
"""

import time

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework.test import APIClient

from geonode.groups.models import GroupProfile
from geonode.layers.models import Dataset
from geonode.resource.models import ExecutionRequest
from geonode.resource.registry import resource_manager_registry
from geonode.security.permissions import PermSpecCompact
from geonode.upload.models import ResourceHandlerInfo

VIEWERS_GROUP = "avdp-viewers"
EDITORS_GROUP = "avdp-editors"


def manager(resource):
    """GeoNode 5.1 resolves the resource manager per resource type."""
    return resource_manager_registry.get_for_instance(resource)


def server_name():
    hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*"]
    return "django" if "django" in hosts else (hosts[0] if hosts else "localhost")


def api_client(user):
    client = APIClient(SERVER_NAME=server_name())
    client.force_authenticate(user=user)
    return client


def upload_vector(owner, path, timeout=600, auto_style=False):
    """Upload one vector file through the GeoNode importer and return the new Dataset.

    auto_style=False skips the automatic smart style (the caller styles it).
    """
    from geonode_project.avdp import signals

    with open(path, "rb") as handle:
        response = api_client(owner).post(
            reverse("importer_upload"),
            {"base_file": handle, "action": "upload", "non_interactive": "true"},
            format="multipart",
        )
    if response.status_code != 201:
        raise CommandError(f"Importer rejected {path} ({response.status_code}): {getattr(response, 'data', '')}")
    exec_id = response.data["execution_id"]
    if not auto_style:
        signals.suppress(exec_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = ExecutionRequest.objects.get(exec_id=exec_id)
        if req.status == ExecutionRequest.STATUS_FINISHED:
            infos = ResourceHandlerInfo.objects.filter(execution_request__exec_id=exec_id)
            datasets = [i.resource.get_real_instance() for i in infos]
            datasets = [d for d in datasets if isinstance(d, Dataset)]
            if len(datasets) != 1:
                raise CommandError(f"Expected one dataset from {path}, got {datasets}")
            return datasets[0]
        if req.status == ExecutionRequest.STATUS_FAILED:
            raise CommandError(f"Import of {path} failed: {req.log}")
        time.sleep(2)
    raise CommandError(f"Import of {path} did not finish within {timeout}s (exec {exec_id}).")


def perm_spec(resource, public=False, viewers_group=VIEWERS_GROUP, editors_group=EDITORS_GROUP):
    """Owner manages; AVDP viewers view+download; AVDP editors edit; visitors only if public.

    public: False, True/"view", or "download" (visitors may also read features, e.g. for
    dashboard statistics on a layer that only aggregates public data).
    """

    def group(name):
        g = Group.objects.filter(name=name).first()
        if not g:
            raise CommandError(f"Group '{name}' not found. Run `python manage.py avdp_setup` first.")
        return g

    viewers = GroupProfile.objects.get(group=group(viewers_group))
    editors = GroupProfile.objects.get(group=group(editors_group))
    anonymous = group("anonymous")
    registered = Group.objects.filter(name="registered-members").first()
    owner = resource.owner
    spec = {
        "users": [
            {
                "id": owner.id,
                "username": owner.username,
                "first_name": owner.first_name or "",
                "last_name": owner.last_name or "",
                "avatar": "",
                "permissions": "owner",
                "is_staff": owner.is_staff,
                "is_superuser": owner.is_superuser,
            }
        ],
        "organizations": [
            {"id": viewers.group.id, "name": viewers.group.name, "title": viewers.title, "permissions": "download"},
            {"id": editors.group.id, "name": editors.group.name, "title": editors.title, "permissions": "edit"},
        ],
        "groups": [
            {
                "id": anonymous.id,
                "name": "anonymous",
                "title": "anonymous",
                "permissions": "download" if public == "download" else ("view" if public else "none"),
            }
        ],
    }
    if registered:
        spec["groups"].append(
            {"id": registered.id, "name": registered.name, "title": registered.name, "permissions": "none"}
        )
    if not PermSpecCompact.validate(spec):
        raise CommandError("Internal error: generated permission spec is invalid.")
    return spec


def apply_permissions(resource, public=False):
    if not manager(resource).set_permissions(resource.uuid, instance=resource, permissions=perm_spec(resource, public)):
        raise CommandError(f"Could not set permissions on {resource}")


def refresh_thumbnail(resource):
    """Re-render a thumbnail; never fails the caller (thumbnails are cosmetic)."""
    try:
        resource.refresh_from_db()
        manager(resource).set_thumbnail(resource.uuid, instance=resource, overwrite=True, check_bbox=False)
        return True
    except Exception:
        return False


def find_marked(model, keyword):
    """The single resource carrying a marker keyword (None if none; error if several)."""
    found = model.objects.filter(keywords__name=keyword).distinct()
    if found.count() > 1:
        raise CommandError(f"More than one {model.__name__} carries marker '{keyword}'.")
    return found.first()


def thesaurus_keyword(title, concept):
    return {"type": "theme", "thesaurus": {"title": title, "date": "", "datetype": ""}, "keywords": [concept]}


def datastore():
    return settings.OGC_SERVER["default"].get("DATASTORE") or "datastore"


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'
