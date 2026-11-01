"""Publish (and refresh) KoboToolbox or ODK Central survey submissions as a dataset.

    # KoboToolbox: put the API token in .env as KOBO_TOKEN, then
    python manage.py avdp_sync_form kobo --server https://kf.kobotoolbox.org --form <asset uid> --name water_point_survey

    # ODK Central: ODK_TOKEN, or ODK_USER + ODK_PASSWORD, in .env
    python manage.py avdp_sync_form odk --server https://central.example.org --project 3 --form water_points --name water_point_survey

The first run creates the dataset (styled and data-checked automatically,
private to its owner unless --share/--public). Later runs replace its records
with the current submissions, so maps and dashboards using it stay valid.
Questions whose names suggest personal data (phone, names, ID numbers…) are
left out unless listed with --keep-personal. Schedule the command (cron on a
server, Task Scheduler on Windows) to keep the dataset current.
"""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from geonode.layers.models import Dataset
from geonode_project.avdp import districts, fieldsync, history, portal_ops, quality, smart_mapping
from geonode_project.avdp.portal_ops import quote

SOURCES = {"kobo": "KoboToolbox", "odk": "ODK Central"}


class Command(BaseCommand):
    help = "Create or refresh a dataset from KoboToolbox or ODK Central submissions."

    def add_arguments(self, parser):
        parser.add_argument("source", choices=sorted(SOURCES))
        parser.add_argument("--server", required=True, help="e.g. https://kf.kobotoolbox.org or your ODK Central address")
        parser.add_argument("--form", required=True, help="Kobo asset uid, or ODK form id")
        parser.add_argument("--project", help="ODK Central project number")
        parser.add_argument("--name", required=True, help="Dataset name: letters, digits and underscores")
        parser.add_argument("--title", help="Dataset title (default: from the name)")
        parser.add_argument("--keep-personal", default="", help="Comma-separated columns to keep despite looking personal")
        parser.add_argument("--exclude", default="", help="Comma-separated columns to leave out")
        parser.add_argument("--share", action="store_true", help="Share with AVDP Viewers (view+download) and Editors")
        parser.add_argument("--public", action="store_true", help="Also let visitors view it (implies --share)")
        parser.add_argument("--owner", default=os.getenv("ADMIN_USERNAME", "admin"))
        parser.add_argument("--timeout", type=int, default=600)

    def handle(self, *args, **opts):
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,60}", opts["name"]):
            raise CommandError("--name must start with a letter and use only lowercase letters, digits and underscores.")
        try:
            owner = get_user_model().objects.get(username=opts["owner"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Owner '{opts['owner']}' does not exist.")
        source = opts["source"]
        try:
            if source == "kobo":
                token = os.getenv("KOBO_TOKEN")
                if not token:
                    raise CommandError("Set KOBO_TOKEN in .env (KoboToolbox → Account settings → API key) and restart.")
                submissions = fieldsync.fetch_kobo(opts["server"], opts["form"], token)
            else:
                if not opts["project"]:
                    raise CommandError("ODK Central needs --project.")
                submissions = fieldsync.fetch_odk(
                    opts["server"], opts["project"], opts["form"],
                    token=os.getenv("ODK_TOKEN"), user=os.getenv("ODK_USER"), password=os.getenv("ODK_PASSWORD"),
                )
        except fieldsync.SyncError as exc:
            raise CommandError(f"{SOURCES[source]}: {exc}")

        rows = fieldsync.to_rows(
            submissions, source,
            keep_personal=[c.strip() for c in opts["keep_personal"].split(",") if c.strip()],
            exclude=[c.strip() for c in opts["exclude"].split(",") if c.strip()],
        )
        self.stdout.write(
            f"{SOURCES[source]}: {len(submissions)} submissions, {len(rows.features)} with a location"
            + (f", {rows.skipped_no_location} without (skipped)" if rows.skipped_no_location else "")
        )
        if rows.excluded:
            self.stdout.write(f"Left out as possibly personal or excluded: {', '.join(sorted(rows.excluded))}")
        if not rows.features:
            raise CommandError("No submissions with a GPS location; nothing to publish.")

        marker = f"avdp-sync-{source}-{re.sub(r'[^a-z0-9]+', '-', opts['form'].lower())}"
        dataset = portal_ops.find_marked(Dataset, marker)
        if dataset is None:
            dataset = self._create(owner, rows, opts, marker)
            action = "created"
        else:
            self._replace(dataset, rows)
            action = "updated"
        self._metadata(dataset, opts, len(rows.features), marker)
        if opts["share"] or opts["public"]:
            portal_ops.apply_permissions(dataset, public=opts["public"])
        result = quality.run_and_save(dataset)
        portal_ops.refresh_thumbnail(dataset)
        self.stdout.write(self.style.SUCCESS(f"Dataset {action}: {dataset.title} ({dataset.detail_url})"))
        self.stdout.write(f"Data check: {result['summary']}")

    # ------------------------------------------------------------------
    def _create(self, owner, rows, opts, marker):
        work = tempfile.mkdtemp(prefix="avdp_sync_")
        try:
            path = os.path.join(work, f"{opts['name']}.geojson")
            with open(path, "w") as handle:
                json.dump({"type": "FeatureCollection", "name": opts["name"], "features": rows.features}, handle)
            # Styled here rather than by the upload hook, which would update the
            # same new dataset concurrently (database deadlocks).
            dataset = portal_ops.upload_vector(owner, path, opts["timeout"], auto_style=False)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        portal_ops.manager(dataset).update(dataset.uuid, instance=dataset, keywords=[marker, "field survey"], notify=False)
        dataset = Dataset.objects.get(pk=dataset.pk)
        self.stdout.write(f"Style: {smart_mapping.apply(dataset, thumbnail=False)}")
        history.enable(dataset)
        return Dataset.objects.get(pk=dataset.pk)

    def _replace(self, dataset, rows):
        geom = districts.geometry_column(dataset)
        columns = {a.attribute for a in dataset.attribute_set.all()} - {geom, "fid"}
        incoming = set(rows.features[0]["properties"])
        new = sorted(incoming - columns)
        if new:
            self.stdout.write(self.style.WARNING(
                f"New questions not in the dataset yet (ignored): {', '.join(new)}. "
                "Delete the dataset and run again to include them."
            ))
        use = sorted(incoming & columns)
        table = quote(dataset.name)
        with connections[portal_ops.datastore()].cursor() as cursor:
            cursor.execute(f"SELECT Find_SRID('public', %s, %s)", [dataset.name, geom])
            srid = cursor.fetchone()[0] or 4326
            point = f"ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), {srid})" if srid != 4326 else "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
            insert = (
                f"INSERT INTO {table} ({', '.join(quote(c) for c in use)}{', ' if use else ''}{quote(geom)}) "
                f"VALUES ({', '.join(['%s'] * len(use))}{', ' if use else ''}ST_Multi({point}))"
            )
            is_multi = self._is_multi(cursor, dataset.name, geom)
            if not is_multi:
                insert = insert.replace(f"ST_Multi({point})", point)
            with transaction.atomic(using=portal_ops.datastore()):
                cursor.execute("SET LOCAL avdp.source = 'form sync'")  # labels these rows in the change history
                cursor.execute(f"DELETE FROM {table}")
                for f in rows.features:
                    lon, lat = f["geometry"]["coordinates"][:2]
                    cursor.execute(insert, [f["properties"].get(c) for c in use] + [lon, lat])
            cursor.execute(
                f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
                f"(SELECT ST_Extent(ST_Transform({quote(geom)}, 4326)) e FROM {table}) s"
            )
            bbox = cursor.fetchone()
        self._refresh_bounds(dataset, bbox)
        self.stdout.write(f"Replaced the records of {dataset.alternate}.")

    @staticmethod
    def _is_multi(cursor, table, geom):
        cursor.execute("SELECT type FROM geometry_columns WHERE f_table_name = %s AND f_geometry_column = %s", [table, geom])
        row = cursor.fetchone()
        return bool(row and row[0].upper().startswith("MULTI"))

    @staticmethod
    def _refresh_bounds(dataset, bbox):
        from geonode.geoserver.helpers import _invalidate_geowebcache_dataset
        from geonode_project.avdp.smart_mapping import GeoServer

        gs = GeoServer()
        ws, name = dataset.alternate.split(":", 1)
        store = dataset.store or "geonode_data"
        gs._call(
            "PUT",
            f"workspaces/{ws}/datastores/{store}/featuretypes/{name}?recalculate=nativebbox,latlonbbox",
            json={"featureType": {"name": name, "enabled": True}},
        )
        if bbox and None not in bbox:
            dataset.set_bbox_polygon(list(bbox), "EPSG:4326")
        _invalidate_geowebcache_dataset(dataset.alternate)

    def _metadata(self, dataset, opts, count, marker):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        form = opts["form"] if opts["source"] == "kobo" else f"project {opts['project']}, form {opts['form']}"
        vals = {
            "abstract": (
                f"Field survey submissions from {SOURCES[opts['source']]} ({opts['server']}, {form}). "
                f"Last synchronised {now}: {count} submissions with a GPS location. Possible personal-data "
                f"questions are not copied. Refreshed with manage.py avdp_sync_form."
            ),
            "supplemental_information": f"Source: {SOURCES[opts['source']]} {opts['server']} {form}",
            "maintenance_frequency": "continual",
        }
        if opts["title"] or dataset.title == dataset.name:
            vals["title"] = opts["title"] or opts["name"].replace("_", " ").capitalize()
        portal_ops.manager(dataset).update(dataset.uuid, instance=dataset, vals=vals, notify=False)
        dataset.refresh_from_db()
