"""Run the automatic data checks on existing datasets.

    python manage.py avdp_quality_check               # every vector dataset
    python manage.py avdp_quality_check water farm    # by name or id

New uploads are checked automatically; the latest result is shown on each
dataset's map page ("Data check"). See geonode_project/avdp/quality.py.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from geonode.layers.models import Dataset
from geonode_project.avdp import quality

MARK = {"problem": "!!", "warning": " !", "info": " i"}


class Command(BaseCommand):
    help = "Check vector datasets for location, geometry, duplicate, empty-field and district-label issues."

    def add_arguments(self, parser):
        parser.add_argument("datasets", nargs="*", help="Dataset names or ids (default: all vector datasets)")

    def handle(self, *args, **opts):
        qs = Dataset.objects.filter(subtype__in=("vector", "vector_time"))
        if opts["datasets"]:
            match = Q()
            for item in opts["datasets"]:
                match |= Q(pk=int(item)) if item.isdigit() else Q(name__icontains=item)
            qs = qs.filter(match)
        for dataset in qs.order_by("title"):
            try:
                result = quality.run_and_save(dataset)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"{dataset.title}: check failed: {exc}"))
                continue
            style = {"ok": self.style.SUCCESS, "warnings": self.style.WARNING, "problems": self.style.ERROR}[result["status"]]
            self.stdout.write(style(f"{dataset.title}: {result['summary']}"))
            for issue in result["issues"]:
                examples = f" e.g. {', '.join(issue['examples'][:3])}" if issue["examples"] else ""
                self.stdout.write(f"  {MARK[issue['level']]} {issue['message']}{examples}")
