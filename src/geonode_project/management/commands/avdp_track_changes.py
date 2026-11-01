"""Turn on (or off) change history for datasets, and show recent changes.

    python manage.py avdp_track_changes --all          # every vector dataset
    python manage.py avdp_track_changes water_points   # by name or id
    python manage.py avdp_track_changes water --show   # print recent changes
    python manage.py avdp_track_changes water --off

New uploads are tracked automatically. See geonode_project/avdp/history.py.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from geonode.layers.models import Dataset
from geonode_project.avdp import history


class Command(BaseCommand):
    help = "Record every change to dataset records (old and new values, time, source)."

    def add_arguments(self, parser):
        parser.add_argument("datasets", nargs="*")
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--off", action="store_true", help="Stop recording (keeps the existing log)")
        parser.add_argument("--show", action="store_true", help="List recent changes instead")
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **opts):
        qs = Dataset.objects.filter(subtype__in=("vector", "vector_time"))
        if opts["datasets"]:
            match = Q()
            for item in opts["datasets"]:
                match |= Q(pk=int(item)) if item.isdigit() else Q(name__icontains=item)
            qs = qs.filter(match)
        elif not opts["all"]:
            raise CommandError("Name datasets or use --all.")
        for dataset in qs.order_by("title"):
            if opts["show"]:
                self.stdout.write(self.style.MIGRATE_HEADING(dataset.title))
                for e in history.entries(dataset, opts["limit"]):
                    detail = "; ".join(f"{k}: {o!r} -> {n!r}" for k, o, n in e["changes"])
                    self.stdout.write(f"  {e['when']:%Y-%m-%d %H:%M} {e['operation']:<6} {e['source']:<16} {e['feature']} {detail}")
            elif opts["off"]:
                history.disable(dataset)
                self.stdout.write(f"{dataset.title}: history off")
            else:
                history.enable(dataset)
                self.stdout.write(f"{dataset.title}: history on")
