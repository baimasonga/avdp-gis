"""Build or refresh the district summary layer (features per AVDP category per district).

    python manage.py avdp_district_summary                 # counts datasets shared with AVDP viewers
    python manage.py avdp_district_summary --audience public --public

Each district polygon gets one count per AVDP dataset category plus a total.
A dataset counts only if it has an AVDP dataset category and the audience
may view it, so the summary never reveals private data. Re-running updates
the same dataset in place (its id, links and dashboards stay valid).
"""

import json
import os
import shutil
import tempfile
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from geonode.base.models import TopicCategory
from geonode.layers.models import Dataset
from geonode_project.avdp import districts, feature_info, portal_ops, smart_mapping, styles
from geonode_project.avdp.portal_ops import quote

MARKER = "avdp-district-summary"
DATASET_NAME = "avdp_district_summary"
COLUMNS = [c for _concept, c, _label in districts.CATEGORY_COLUMNS]
LABELS = {c: label for _concept, c, label in districts.CATEGORY_COLUMNS}
LABELS["total_features"] = "All AVDP features"


class Command(BaseCommand):
    help = "Build or refresh the district summary layer used by maps and the dashboard."

    def add_arguments(self, parser):
        parser.add_argument(
            "--audience",
            choices=("viewers", "public", "all"),
            default="viewers",
            help="Count only datasets this audience may view (default: AVDP viewers). 'all' ignores sharing.",
        )
        parser.add_argument("--public", action="store_true", help="Let visitors view the summary (needs --audience public)")
        parser.add_argument("--owner", default=os.getenv("ADMIN_USERNAME", "admin"))
        parser.add_argument("--timeout", type=int, default=600)

    def handle(self, *args, **opts):
        if opts["public"] and opts["audience"] != "public":
            raise CommandError("--public requires --audience public, so private datasets are never counted publicly.")
        try:
            owner = get_user_model().objects.get(username=opts["owner"])
            bds = districts.boundary_dataset()
        except get_user_model().DoesNotExist:
            raise CommandError(f"Owner '{opts['owner']}' does not exist.")
        except districts.DistrictError as exc:
            raise CommandError(str(exc))

        counts, used, skipped = districts.category_counts(opts["audience"], exclude=(MARKER,))
        rows = self._rows(bds, counts)
        synthetic = any(districts.is_synthetic(d) for d, _c in used)

        dataset = portal_ops.find_marked(Dataset, MARKER)
        if dataset is None:
            dataset = self._create(owner, rows, opts["timeout"])
        else:
            self._update(dataset, rows)
            self.stdout.write(f"Updated {dataset.alternate} in place.")

        self._metadata(dataset, used, skipped, synthetic, opts["audience"])
        self._styles(dataset, rows)
        fields = ["district", "province", *COLUMNS, "total_features", "updated", "synthetic_included"]
        Dataset.objects.filter(pk=dataset.pk).update(
            featureinfo_custom_template=feature_info.build_template("District summary", fields, synthetic),
            use_featureinfo_custom_template=True,
        )
        portal_ops.refresh_thumbnail(dataset)
        # Public dashboards read the counts through WPS/WFS, which GeoNode treats as "download".
        portal_ops.apply_permissions(dataset, public="download" if opts["public"] else False)

        total = sum(r["total_features"] for r in rows)
        self.stdout.write(f"Datasets counted: {len(used)}; not counted: {len(skipped)}")
        for d, column in used:
            self.stdout.write(f"  + {d.title} -> {LABELS[column]}")
        for d, reason in skipped:
            self.stdout.write(f"  - {d.title}: {reason}")
        self.stdout.write(self.style.SUCCESS(f"District summary ready: {total} features in 16 districts ({dataset.detail_url})"))

    # ------------------------------------------------------------------
    def _rows(self, bds, counts):
        geom = districts.geometry_column(bds)
        with connections[portal_ops.datastore()].cursor() as cursor:
            cursor.execute(
                f"SELECT district, district_pcode, province, area_sqkm, ST_AsGeoJSON(ST_Transform({quote(geom)}, 4326)) "
                f"FROM {quote(bds.name)} ORDER BY district"
            )
            records = cursor.fetchall()
        today = date.today().isoformat()
        rows = []
        for district, pcode, province, area, geometry in records:
            c = counts.get(pcode, {})
            row = {
                "district": district,
                "district_pcode": pcode,
                "province": province,
                "area_sqkm": area,
                **{col: int(c.get(col, 0)) for col in COLUMNS},
                "updated": today,
                "synthetic_included": "no",
                "_geometry": json.loads(geometry),
            }
            row["total_features"] = sum(row[col] for col in COLUMNS)
            rows.append(row)
        return rows

    def _create(self, owner, rows, timeout):
        work = tempfile.mkdtemp(prefix="avdp_sum_")
        try:
            path = os.path.join(work, f"{DATASET_NAME}.geojson")
            features = [
                {
                    "type": "Feature",
                    "geometry": r["_geometry"],
                    "properties": {k: v for k, v in r.items() if not k.startswith("_")},
                }
                for r in rows
            ]
            with open(path, "w") as handle:
                json.dump({"type": "FeatureCollection", "name": DATASET_NAME, "features": features}, handle)
            dataset = portal_ops.upload_vector(owner, path, timeout)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        portal_ops.manager(dataset).update(dataset.uuid, instance=dataset, keywords=[MARKER], notify=False)
        self.stdout.write(self.style.SUCCESS(f"Created {dataset.alternate}"))
        return Dataset.objects.get(pk=dataset.pk)

    def _update(self, dataset, rows):
        names = {a.attribute for a in dataset.attribute_set.all()}
        missing = set(COLUMNS + ["total_features", "district_pcode"]) - names
        if missing:
            raise CommandError(f"{dataset.alternate} lacks columns {sorted(missing)}; delete it and run again.")
        sets = ", ".join(f"{quote(c)} = %s" for c in COLUMNS + ["total_features", "updated"])
        with connections[portal_ops.datastore()].cursor() as cursor:
            for r in rows:
                cursor.execute(
                    f"UPDATE {quote(dataset.name)} SET {sets} WHERE district_pcode = %s",
                    [r[c] for c in COLUMNS] + [r["total_features"], r["updated"], r["district_pcode"]],
                )

    def _metadata(self, dataset, used, skipped, synthetic, audience):
        flag = "yes" if synthetic else "no"
        with connections[portal_ops.datastore()].cursor() as cursor:
            cursor.execute(f"UPDATE {quote(dataset.name)} SET synthetic_included = %s", [flag])
        sources = "\n".join(f"- {d.title} ({LABELS[c]})" for d, c in used) or "- none"
        notice = f"{settings.AVDP_SYNTHETIC_NOTICE} " if synthetic else ""
        audience_text = {
            "viewers": "datasets shared with AVDP Viewers (or public)",
            "public": "public datasets only",
            "all": "all datasets regardless of sharing",
        }[audience]
        vals = {
            "title": "District summary — AVDP features per category" + (" (includes SYNTHETIC DEMO data)" if synthetic else ""),
            "abstract": (
                f"{notice}Number of features per AVDP dataset category in each of the 16 districts, counted by "
                f"location against the official district boundaries (a point on each feature's surface).\n\n"
                f"Counted: {audience_text} that have an AVDP dataset category. Updated {date.today().isoformat()} "
                f"from:\n{sources}\n\n{len(skipped)} other vector dataset(s) were not counted (no category, or not "
                f"shared with this audience). Counts are features, not people or hectares; refresh with "
                f"`manage.py avdp_district_summary`."
            ),
            "purpose": "District overview for programme monitoring and the AVDP dashboard.",
            "attribution": "AVDP GIS Portal (derived); boundaries: Government of Sierra Leone / OCHA (CC BY-IGO).",
            "category": TopicCategory.objects.filter(identifier="farming").first(),
            "maintenance_frequency": "asNeeded",
        }
        keywords = [MARKER, "district summary", "statistics"]
        if synthetic:
            keywords.append(settings.AVDP_DEMO_KEYWORD)
        portal_ops.manager(dataset).update(
            dataset.uuid, instance=dataset, vals=vals, keywords=keywords, regions=["SLE"], notify=False
        )
        dataset.refresh_from_db()

    def _styles(self, dataset, rows):
        gs = smart_mapping.GeoServer()
        geom = districts.geometry_column(dataset) or "geom"

        def choropleth(name, column):
            # Quartile breaks of the districts that have any features; zero is its own class.
            values = sorted(r[column] for r in rows if r[column] > 0) or [0]
            n = len(values)
            breaks = [values[min(n - 1, round(q * (n - 1)))] for q in (0, 0.25, 0.5, 0.75, 1)]
            title = f"{LABELS[column]} per district"
            return styles.build_choropleth_sld(name, title, column, "features", breaks, geom, small=False, counts=True)

        smart_mapping.write_default_style(dataset, choropleth(dataset.default_style.name, "total_features"))
        extra = []
        for column in COLUMNS:
            if any(r[column] for r in rows):
                name = f"{dataset.name}{smart_mapping.ALT_PREFIX}{column}"
                gs.put_style(name, choropleth(name, column))
                extra.append(name)
        gs.set_layer_styles(dataset.alternate, dataset.default_style.name, extra)
        from geonode.geoserver.helpers import _invalidate_geowebcache_dataset

        _invalidate_geowebcache_dataset(dataset.alternate)
