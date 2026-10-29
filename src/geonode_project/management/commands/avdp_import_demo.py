"""Import the AVDP synthetic demonstration package through GeoNode's importer.

Explicit, repeatable and safe to re-run:

* the package is validated first (see ``avdp_validate_demo``); nothing is
  imported if validation fails;
* each layer is uploaded through GeoNode's own importer API view
  (``importer_upload``), so file validation, upload limits, GeoServer
  publishing, resource registration and default permissions all apply;
* datasets created by this command carry a per-layer marker keyword. On a
  re-run, marked datasets are reused (metadata, style and sharing are
  re-applied) instead of being uploaded again, so no duplicates are created;
* a dataset that has the target name but no marker is treated as unrelated
  data and left untouched (the command stops for that layer);
* the demo map is created once and updated in place on later runs.

Nothing here runs automatically. Usage::

    python manage.py avdp_import_demo /usr/src/project/data/demo/AVDP_Synthetic_GIS_Sample_Package.zip \\
        --owner admin [--public] [--prefer shapefile] [--skip-map]
"""

import json
import os
import shutil
import tempfile
import time

from django.conf import settings
from osgeo import gdal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from rest_framework.test import APIClient

from geonode.base.models import License, RestrictionCodeType, TopicCategory
from geonode.groups.models import GroupProfile
from geonode.layers.models import Dataset
from geonode.maps.models import Map
from geonode.resource.registry import resource_manager_registry
from geonode.resource.models import ExecutionRequest
from geonode.security.permissions import PermSpecCompact
from geonode.upload.models import ResourceHandlerInfo

from geonode_project.avdp import demo_package as dp
from geonode_project.avdp import styles
from geonode_project.avdp.demo_map import MAP_MARKER, MAP_TITLE, build_map_payload

CATEGORY_THESAURUS_TITLE = "AVDP dataset category"
STATUS_THESAURUS_TITLE = "AVDP data status"

LIMITATIONS = (
    "Invented demonstration locations and figures. "
    "District labels are illustrative and have not been checked against official boundaries. "
    "Farm polygons are schematic and roads do not represent actual routes. "
    "Beneficiary counts must not be summed as unique people across layers. "
    "The package contains no official district boundaries."
)


def _manager(resource):
    """GeoNode 5.1 resolves the resource manager per resource type."""
    return resource_manager_registry.get_for_instance(resource)


def _thesaurus_keyword(title, concept):
    return {"type": "theme", "thesaurus": {"title": title, "date": "", "datetype": ""}, "keywords": [concept]}


class Command(BaseCommand):
    help = "Validate and import the AVDP synthetic demonstration package (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("package", help="Path to AVDP_Synthetic_GIS_Sample_Package.zip or an extracted directory")
        parser.add_argument("--owner", default=os.getenv("ADMIN_USERNAME", "admin"), help="Owner of the resources")
        parser.add_argument("--prefer", choices=("geojson", "shapefile"), default="geojson",
                            help="Source format to upload when both are present (default: geojson)")
        parser.add_argument("--viewers-group", default="avdp-viewers", help="Group granted view+download")
        parser.add_argument("--editors-group", default="avdp-editors", help="Group granted edit")
        parser.add_argument("--public", action="store_true",
                            help="Also let anonymous visitors view the demo datasets and map (default: private)")
        parser.add_argument("--adopt", action="store_true",
                            help="Treat an unmarked dataset with the exact target name as a previous partial run")
        parser.add_argument("--import-alongside", action="store_true",
                            help="If an unrelated dataset already uses the target name, import anyway "
                                 "(GeoNode assigns a new unique name; the existing dataset is not touched)")
        parser.add_argument("--skip-map", action="store_true", help="Do not create/update the demo map")
        parser.add_argument("--timeout", type=int, default=600, help="Seconds to wait for each import")
        parser.add_argument("--validate-only", action="store_true", help="Validate the package and stop")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        package = opts["package"]
        if not os.path.exists(package):
            raise CommandError(
                f"Package not found: {package}. The demonstration import remains pending until "
                f"{dp.PACKAGE_NAME} is supplied (see docs/DATA_IMPORT.md)."
            )
        try:
            self.owner = get_user_model().objects.get(username=opts["owner"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Owner '{opts['owner']}' does not exist.")
        self.opts = opts
        work = tempfile.mkdtemp(prefix="avdp_demo_")
        try:
            root = package
            if not os.path.isdir(package):
                try:
                    dp.safe_extract(package, os.path.join(work, "pkg"))
                except dp.PackageError as exc:
                    raise CommandError(f"Unsafe or invalid package: {exc}")
                root = os.path.join(work, "pkg")
            found = dp.discover(root)
            reports = dp.validate(found)
            result = dp.summary(reports)
            from geonode_project.management.commands.avdp_validate_demo import print_report

            print_report(self.stdout, self.style, result)
            if not result["ok"]:
                raise CommandError("Package validation failed; nothing was imported.")
            if opts["validate_only"]:
                self.stdout.write(self.style.SUCCESS("Validation passed (--validate-only)."))
                return

            datasets = {}
            for spec in dp.LAYERS:
                datasets[spec.key] = self._import_layer(spec, found[spec.key], work)

            for spec in dp.LAYERS:
                self._finalise_dataset(spec, datasets[spec.key], found[spec.key])

            counts = {k: self._feature_count(d) for k, d in datasets.items()}
            total = sum(counts.values())
            for spec in dp.LAYERS:
                flag = "OK" if counts[spec.key] == spec.expected_count else "MISMATCH"
                self.stdout.write(f"  {spec.title:<22} {counts[spec.key]:>4}/{spec.expected_count:<4} {flag}"
                                  f"  -> {datasets[spec.key].alternate}")
            msg = f"Imported feature total: {total} (expected {dp.EXPECTED_TOTAL})"
            if total != dp.EXPECTED_TOTAL:
                raise CommandError(msg)
            self.stdout.write(self.style.SUCCESS(msg))

            if not opts["skip_map"]:
                self._ensure_map(datasets)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ------------------------------------------------------------------
    def _existing(self, spec):
        marked = Dataset.objects.filter(keywords__name=spec.marker_keyword).distinct()
        if marked.count() > 1:
            raise CommandError(f"More than one dataset carries marker '{spec.marker_keyword}': {list(marked)}")
        if marked.exists():
            return marked.first()
        unmarked = Dataset.objects.filter(name=spec.dataset_name).first()
        if unmarked:
            if self.opts["adopt"]:
                self.stdout.write(self.style.WARNING(f"Adopting existing dataset {unmarked.alternate} (--adopt)"))
                return unmarked
            if self.opts["import_alongside"]:
                return None
            raise CommandError(
                f"A dataset named '{spec.dataset_name}' exists but was not created by this command. "
                "It has been left untouched. Re-run with --adopt if it is a partial earlier import, "
                "or with --import-alongside to import the demo layer under a different name."
            )
        return None

    def _import_layer(self, spec, files, work):
        existing = self._existing(spec)
        if existing:
            self.stdout.write(f"{spec.title}: already imported as {existing.alternate}; reusing.")
            return existing

        source = files.preferred(self.opts["prefer"])
        stage = os.path.join(work, "upload", spec.key)
        os.makedirs(stage, exist_ok=True)
        payload = {"action": "upload", "non_interactive": "true", "overwrite_existing_layer": "false"}
        handles = []
        try:
            if source.lower().endswith(".shp"):
                stem = os.path.splitext(source)[0]
                for ext, key in (("shp", "base_file"), ("dbf", "dbf_file"), ("shx", "shx_file"),
                                 ("prj", "prj_file"), ("cpg", "cpg_file")):
                    src = f"{stem}.{ext}"
                    if os.path.exists(src):
                        dst = os.path.join(stage, f"{spec.dataset_name}.{ext}")
                        shutil.copyfile(src, dst)
                        handles.append(open(dst, "rb"))
                        payload[key] = handles[-1]
            else:
                # The importer names a GeoJSON dataset after its internal layer name, so
                # stage a copy whose layer is called avdp_demo_<layer> (data unchanged).
                dst = os.path.join(stage, f"{spec.dataset_name}.geojson")
                gdal.VectorTranslate(dst, source, format="GeoJSON", layerName=spec.dataset_name)
                handles.append(open(dst, "rb"))
                payload["base_file"] = handles[-1]

            client = APIClient(SERVER_NAME=self._server_name())
            client.force_authenticate(user=self.owner)
            self.stdout.write(f"{spec.title}: uploading {os.path.basename(source)} via GeoNode importer ...")
            response = client.post(reverse("importer_upload"), payload, format="multipart")
        finally:
            for handle in handles:
                handle.close()
        if response.status_code != 201:
            raise CommandError(f"{spec.title}: importer rejected the upload ({response.status_code}): "
                               f"{getattr(response, 'data', response.content)}")
        exec_id = response.data["execution_id"]
        dataset = self._wait_for(spec, exec_id)
        # Mark immediately so a re-run recognises this dataset even if a later step fails.
        _manager(dataset).update(dataset.uuid, instance=dataset, keywords=[settings.AVDP_DEMO_KEYWORD, spec.marker_keyword],
                                notify=False)
        return Dataset.objects.get(pk=dataset.pk)

    def _wait_for(self, spec, exec_id):
        deadline = time.time() + self.opts["timeout"]
        while time.time() < deadline:
            req = ExecutionRequest.objects.get(exec_id=exec_id)
            if req.status == ExecutionRequest.STATUS_FINISHED:
                infos = ResourceHandlerInfo.objects.filter(execution_request__exec_id=exec_id)
                resources = [i.resource.get_real_instance() for i in infos]
                datasets = [r for r in resources if isinstance(r, Dataset)]
                if len(datasets) != 1:
                    raise CommandError(f"{spec.title}: expected one dataset from import, got {resources}")
                self.stdout.write(self.style.SUCCESS(f"{spec.title}: imported as {datasets[0].alternate}"))
                return datasets[0]
            if req.status == ExecutionRequest.STATUS_FAILED:
                raise CommandError(f"{spec.title}: import failed: {req.log}")
            time.sleep(2)
        raise CommandError(f"{spec.title}: import did not finish within {self.opts['timeout']}s (exec {exec_id}).")

    # ------------------------------------------------------------------
    def _finalise_dataset(self, spec, dataset, files):
        title = f"{spec.title} — SYNTHETIC DEMO"
        abstract = (
            f"{dp.SYNTHETIC_NOTICE}\n\n"
            f"{spec.title} layer from the AVDP synthetic GIS sample package, imported for portal "
            f"demonstration and testing. Expected features: {spec.expected_count}.\n\n"
            f"Limitations: {LIMITATIONS}"
        )
        vals = {
            "title": title,
            "abstract": abstract,
            "purpose": "Demonstration and testing of the AVDP GIS Portal only.",
            "attribution": f"Synthetic sample package ({dp.PACKAGE_NAME}); not an official AVDP source.",
            "data_quality_statement": LIMITATIONS,
            "supplemental_information": (
                f"{dp.SYNTHETIC_NOTICE} District names in the attribute table are illustrative labels, "
                "not verified spatial assignments. Coordinate reference system of the source: WGS 84 (EPSG:4326)."
            ),
            "constraints_other": (
                f"{dp.SYNTHETIC_NOTICE} For demonstration and training only. Do not use for planning, "
                "reporting or decision-making."
            ),
            "category": TopicCategory.objects.filter(identifier=spec.topic_category).first(),
            "license": License.objects.filter(identifier="not_specified").first(),
            "restriction_code_type": RestrictionCodeType.objects.filter(identifier="otherRestrictions").first(),
            "maintenance_frequency": "notPlanned",
        }
        vals = {k: v for k, v in vals.items() if v is not None}
        keywords = [
            settings.AVDP_DEMO_KEYWORD,
            spec.marker_keyword,
            "synthetic data",
            "demonstration",
            _thesaurus_keyword(CATEGORY_THESAURUS_TITLE, spec.category),
            _thesaurus_keyword(STATUS_THESAURUS_TITLE, "synthetic-demonstration"),
        ]
        dataset = _manager(dataset).update(dataset.uuid, instance=dataset, vals=vals, keywords=keywords, regions=["SLE"], notify=False
        )
        self._apply_style(spec, dataset, files)
        self._refresh_thumbnail(dataset)
        self._apply_permissions(dataset)
        self.stdout.write(f"{spec.title}: metadata, style and sharing applied.")

    def _apply_style(self, spec, dataset, files):
        source = files.preferred(self.opts["prefer"])
        report = dp.inspect_vector(source, spec)
        values = dp.distinct_values(source)
        field = dp.style_field(spec, report.fields, values)
        sld = styles.build_sld(spec.key, dataset.name, spec.title, report.geometry_families,
                               field, values.get(field, ()) if field else ())
        sld_path = os.path.join(tempfile.mkdtemp(prefix="avdp_sld_"), f"{dataset.name}.sld")
        with open(sld_path, "w") as handle:
            handle.write(sld)
        client = APIClient(SERVER_NAME=self._server_name())
        client.force_authenticate(user=self.owner)
        try:
            # The vector handlers read the style from "sld_file"; the SLD handler is
            # selected by "base_file". The map viewer's "Upload style" sends both.
            with open(sld_path, "rb") as base, open(sld_path, "rb") as sld:
                response = client.post(
                    reverse("importer_upload"),
                    {"base_file": base, "sld_file": sld, "action": "resource_style_upload",
                     "resource_pk": dataset.pk},
                    format="multipart",
                )
        finally:
            shutil.rmtree(os.path.dirname(sld_path), ignore_errors=True)
        if response.status_code != 201:
            raise CommandError(f"{spec.title}: style upload rejected ({response.status_code}): "
                               f"{getattr(response, 'data', response.content)}")
        exec_id = response.data["execution_id"]
        deadline = time.time() + self.opts["timeout"]
        while time.time() < deadline:
            req = ExecutionRequest.objects.get(exec_id=exec_id)
            if req.status == ExecutionRequest.STATUS_FINISHED:
                break
            if req.status == ExecutionRequest.STATUS_FAILED:
                raise CommandError(f"{spec.title}: style upload failed: {req.log}")
            time.sleep(1)
        styled_by = f" by '{field}'" if field else ""
        self.stdout.write(f"{spec.title}: style applied{styled_by}.")

    def _refresh_thumbnail(self, resource):
        """Re-render the thumbnail so it shows the AVDP style rather than the default one."""
        try:
            _manager(resource).set_thumbnail(resource.uuid, instance=resource, overwrite=True, check_bbox=False)
        except Exception as exc:  # thumbnails are cosmetic; never fail the import for them
            self.stdout.write(self.style.WARNING(f"Thumbnail not refreshed for {resource}: {exc}"))

    def _perm_spec(self, resource):
        def group(name):
            g = Group.objects.filter(name=name).first()
            if not g:
                raise CommandError(f"Group '{name}' not found. Run `python manage.py avdp_setup` first.")
            return g

        viewers = GroupProfile.objects.get(group=group(self.opts["viewers_group"]))
        editors = GroupProfile.objects.get(group=group(self.opts["editors_group"]))
        anonymous = group("anonymous")
        registered = Group.objects.filter(name="registered-members").first()
        owner = resource.owner
        spec = {
            "users": [{
                "id": owner.id, "username": owner.username, "first_name": owner.first_name or "",
                "last_name": owner.last_name or "", "avatar": "", "permissions": "owner",
                "is_staff": owner.is_staff, "is_superuser": owner.is_superuser,
            }],
            "organizations": [
                {"id": viewers.group.id, "name": viewers.group.name, "title": viewers.title, "permissions": "download"},
                {"id": editors.group.id, "name": editors.group.name, "title": editors.title, "permissions": "edit"},
            ],
            "groups": [{"id": anonymous.id, "name": "anonymous", "title": "anonymous",
                        "permissions": "view" if self.opts["public"] else "none"}],
        }
        if registered:
            spec["groups"].append(
                {"id": registered.id, "name": registered.name, "title": registered.name, "permissions": "none"}
            )
        if not PermSpecCompact.validate(spec):
            raise CommandError("Internal error: generated permission spec is invalid.")
        return spec

    def _apply_permissions(self, resource):
        ok = _manager(resource).set_permissions(resource.uuid, instance=resource, permissions=self._perm_spec(resource))
        if not ok:
            raise CommandError(f"Could not set permissions on {resource}")

    @staticmethod
    def _feature_count(dataset):
        from django.db import connections

        db = settings.OGC_SERVER["default"]["DATASTORE"] or "datastore"
        with connections[db].cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{dataset.name}"')  # name comes from GeoNode, not user input
            return cursor.fetchone()[0]

    @staticmethod
    def _server_name():
        hosts = [h for h in settings.ALLOWED_HOSTS if h and h != "*"]
        return "django" if "django" in hosts else (hosts[0] if hosts else "localhost")

    # ------------------------------------------------------------------
    def _ensure_map(self, datasets):
        existing = Map.objects.filter(keywords__name=MAP_MARKER).distinct()
        if existing.count() > 1:
            raise CommandError(f"More than one map carries marker '{MAP_MARKER}'.")
        payload = build_map_payload([(spec, datasets[spec.key]) for spec in dp.LAYERS])
        client = APIClient(SERVER_NAME=self._server_name())
        client.force_authenticate(user=self.owner)
        if existing.exists():
            map_obj = existing.first()
            response = client.patch(f"/api/v2/maps/{map_obj.pk}", payload, format="json")
            action = "updated"
        else:
            response = client.post("/api/v2/maps", payload, format="json")
            action = "created"
        if response.status_code not in (200, 201):
            raise CommandError(f"Map {action} failed ({response.status_code}): {json.dumps(response.data)[:500]}")
        map_obj = Map.objects.get(pk=response.data["map"]["pk"])
        _manager(map_obj).update(map_obj.uuid,
            instance=map_obj,
            vals={
                "abstract": (
                    f"{dp.SYNTHETIC_NOTICE}\n\nDemonstration map combining the seven synthetic AVDP sample layers. "
                    f"Limitations: {LIMITATIONS}"
                ),
                "constraints_other": f"{dp.SYNTHETIC_NOTICE} For demonstration and training only.",
                "category": TopicCategory.objects.filter(identifier="farming").first(),
            },
            keywords=[settings.AVDP_DEMO_KEYWORD, MAP_MARKER, "synthetic data", "demonstration",
                      _thesaurus_keyword(STATUS_THESAURUS_TITLE, "synthetic-demonstration")],
            regions=["SLE"],
            notify=False,
        )
        self._refresh_thumbnail(map_obj)
        self._apply_permissions(map_obj)
        self.stdout.write(self.style.SUCCESS(f"Map '{MAP_TITLE}' {action}: {map_obj.detail_url}"))
