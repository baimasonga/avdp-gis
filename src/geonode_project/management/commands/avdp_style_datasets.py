"""Apply AVDP smart styles to vector datasets.

    python manage.py avdp_style_datasets                 # every vector dataset still on a generic style
    python manage.py avdp_style_datasets water_points    # by name (or id); also matches partial names
    python manage.py avdp_style_datasets --force         # replace existing AVDP styles too
    python manage.py avdp_style_datasets farm_plots --field crop --force

New uploads are styled automatically (AVDP_AUTO_STYLE=True); this command is
for datasets that existed before, or to re-style with a different field.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from geonode.layers.models import Dataset
from geonode_project.avdp import smart_mapping


class Command(BaseCommand):
    help = "Apply AVDP smart styles (default + alternative styles, pop-ups) to vector datasets."

    def add_arguments(self, parser):
        parser.add_argument("datasets", nargs="*", help="Dataset names or ids (default: all vector datasets).")
        parser.add_argument("--force", action="store_true", help="Replace styles that are already AVDP styles.")
        parser.add_argument("--field", help="Attribute to colour by (default: chosen automatically).")
        parser.add_argument("--no-thumbnail", action="store_true", help="Do not re-render thumbnails.")

    def handle(self, *args, **opts):
        qs = Dataset.objects.filter(subtype__in=("vector", "vector_time"))
        if opts["datasets"]:
            match = Q()
            for item in opts["datasets"]:
                match |= Q(pk=int(item)) if item.isdigit() else Q(name__icontains=item) | Q(alternate=item)
            qs = qs.filter(match)
        if not qs.exists():
            self.stdout.write(self.style.WARNING("No matching vector datasets."))
            return
        failures = 0
        for dataset in qs.order_by("title"):
            try:
                result = smart_mapping.apply(
                    dataset, force=opts["force"], type_field=opts["field"], thumbnail=not opts["no_thumbnail"]
                )
                self.stdout.write(f"{dataset.title}: {result}")
            except Exception as exc:
                failures += 1
                self.stdout.write(self.style.ERROR(f"{dataset.title}: failed: {exc}"))
        if failures:
            self.stdout.write(self.style.WARNING(f"{failures} dataset(s) failed; see messages above."))
