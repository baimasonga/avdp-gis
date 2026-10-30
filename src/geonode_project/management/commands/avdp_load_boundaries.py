"""Load the official Sierra Leone district boundaries as a reference dataset.

    python manage.py avdp_load_boundaries                     # download from HDX (needs internet)
    python manage.py avdp_load_boundaries --source /path/sle_admin_boundaries.shp.zip
    python manage.py avdp_load_boundaries --public            # visitors may view them too

Source and licence: see geonode_project/avdp/boundaries.py. Re-running keeps
the existing dataset (its metadata, style and sharing are re-applied); use
--replace to import a newer boundary release.
"""

import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from geonode.base.models import TopicCategory
from geonode.layers.models import Dataset
from geonode_project.avdp import boundaries as bnd
from geonode_project.avdp import feature_info, portal_ops, smart_mapping


class Command(BaseCommand):
    help = "Load official district boundaries (Sierra Leone, admin level 2) as a GeoNode dataset."

    def add_arguments(self, parser):
        parser.add_argument("--source", default=bnd.HDX_SHP_ZIP, help="URL or local path (zip, folder, .shp, .geojson)")
        parser.add_argument("--owner", default=os.getenv("ADMIN_USERNAME", "admin"))
        parser.add_argument("--public", action="store_true", help="Let anonymous visitors view the boundaries")
        parser.add_argument("--replace", action="store_true", help="Delete the loaded boundaries and import again")
        parser.add_argument("--timeout", type=int, default=600)

    def handle(self, *args, **opts):
        try:
            owner = get_user_model().objects.get(username=opts["owner"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Owner '{opts['owner']}' does not exist.")

        dataset = portal_ops.find_marked(Dataset, bnd.MARKER)
        if dataset and opts["replace"]:
            name = dataset.alternate
            portal_ops.manager(dataset).delete(dataset.uuid, instance=dataset)
            self.stdout.write(f"Removed previous boundaries {name}.")
            dataset = None

        work = tempfile.mkdtemp(prefix="avdp_bnd_")
        try:
            if dataset:
                self.stdout.write(f"Boundaries already loaded as {dataset.alternate}; refreshing metadata, style, sharing.")
                summary = {"districts": None}
            else:
                self.stdout.write(f"Reading boundaries from {opts['source']} ...")
                try:
                    path, summary = bnd.prepare(opts["source"], work)
                except (bnd.BoundaryError, Exception) as exc:
                    raise CommandError(f"Boundaries not loaded: {exc}")
                self.stdout.write(f"Validated {len(summary['districts'])} districts: {', '.join(summary['districts'])}")
                dataset = portal_ops.upload_vector(owner, path, opts["timeout"])
                portal_ops.manager(dataset).update(dataset.uuid, instance=dataset, keywords=[bnd.MARKER], notify=False)
                dataset = Dataset.objects.get(pk=dataset.pk)
                self.stdout.write(self.style.SUCCESS(f"Imported as {dataset.alternate}"))
        finally:
            shutil.rmtree(work, ignore_errors=True)

        self._finalise(dataset, opts["source"])
        geometry = next((a.attribute for a in dataset.attribute_set.all() if (a.attribute_type or "").startswith("gml:")), "geom")
        smart_mapping.write_default_style(dataset, bnd.build_boundary_sld(dataset.default_style.name, geometry=geometry))
        fields = ["district", "district_pcode", "province", "province_pcode", "area_sqkm", "valid_on"]
        Dataset.objects.filter(pk=dataset.pk).update(
            featureinfo_custom_template=feature_info.build_template("District", fields),
            use_featureinfo_custom_template=True,
        )
        portal_ops.refresh_thumbnail(dataset)
        portal_ops.apply_permissions(dataset, public=opts["public"])
        audience = "AVDP viewers/editors and visitors" if opts["public"] else "AVDP viewers and editors"
        self.stdout.write(self.style.SUCCESS(f"District boundaries ready ({dataset.detail_url}); shared with {audience}."))

    def _finalise(self, dataset, source):
        vals = {
            "title": "Sierra Leone districts (official boundaries)",
            "abstract": (
                "Administrative level 2 (district) boundaries of Sierra Leone after the 2017 reorganisation "
                "(16 districts, including Falaba and Karene). Common Operational Dataset (COD-AB) provided by the "
                "Government of Sierra Leone and published by OCHA on the Humanitarian Data Exchange. "
                "The source spells Falaba 'Fabala'; the original spelling is kept in district_source_name.\n\n"
                "Used as the reference for district summaries and for checking district labels in AVDP datasets."
            ),
            "purpose": "Reference boundaries for AVDP maps, district summaries and data-quality checks.",
            "attribution": bnd.ATTRIBUTION,
            "constraints_other": f"Licence: {bnd.LICENCE}. Attribution required: {bnd.ATTRIBUTION}.",
            "data_quality_statement": (
                f"Loaded unchanged from {source} (dataset page {bnd.HDX_DATASET}); geometries repaired only if "
                "invalid; areas computed in a Lambert equal-area projection."
            ),
            "supplemental_information": f"Source dataset: {bnd.HDX_DATASET}",
            "category": TopicCategory.objects.filter(identifier="boundaries").first(),
            "maintenance_frequency": "asNeeded",
        }
        keywords = [bnd.MARKER, "administrative boundaries", "districts", "reference data"]
        portal_ops.manager(dataset).update(
            dataset.uuid, instance=dataset, vals=vals, keywords=keywords, regions=["SLE"], notify=False
        )
        dataset.refresh_from_db()
