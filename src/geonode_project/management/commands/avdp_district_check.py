"""Check district labels in the data against the official district boundaries.

    python manage.py avdp_district_check                    # every dataset with a district field
    python manage.py avdp_district_check water --field dist_label
    python manage.py avdp_district_check --csv - > district_check.csv   # one row per feature

Read-only: nothing in the portal is changed. Requires avdp_load_boundaries.
"""

import csv
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from geonode_project.avdp import districts

SUMMARY_MARKER = "avdp-district-summary"


class Command(BaseCommand):
    help = "Compare district labels stored in datasets with the district each feature lies in."

    def add_arguments(self, parser):
        parser.add_argument("datasets", nargs="*", help="Dataset names or ids (default: all with a district field)")
        parser.add_argument("--field", help="Attribute holding the district label (default: detected)")
        parser.add_argument("--csv", help="Write one row per feature to this file ('-' for standard output)")
        parser.add_argument("--examples", type=int, default=5, help="Mismatches to list per dataset")

    def handle(self, *args, **opts):
        try:
            districts.boundary_dataset()
        except districts.DistrictError as exc:
            raise CommandError(str(exc))
        candidates = districts.candidate_datasets(exclude=(SUMMARY_MARKER,))
        if opts["datasets"]:
            wanted = Q()
            for item in opts["datasets"]:
                wanted |= Q(pk=int(item)) if item.isdigit() else Q(name__icontains=item)
            ids = set(type(candidates[0]).objects.filter(wanted).values_list("pk", flat=True)) if candidates else set()
            candidates = [d for d in candidates if d.pk in ids]
        out = self.stderr if opts["csv"] == "-" else self.stdout  # keep CSV on stdout clean
        writer = None
        if opts["csv"]:
            handle = sys.stdout if opts["csv"] == "-" else open(opts["csv"], "w", newline="")
            writer = csv.writer(handle)
            writer.writerow(["dataset", "feature_id", "name", "district_label", "district_by_location", "result"])
        checked_any = False
        for dataset in candidates:
            field = districts.label_field_of(dataset, opts["field"])
            if not field:
                continue
            checked_any = True
            report = districts.check_labels(dataset, field)
            share = f"{100 * report.match / report.checked:.0f}%" if report.checked else "n/a"
            out.write(
                f"{dataset.title} [{field}]: {report.total} features — {report.match} match, "
                f"{report.mismatch} mismatch ({share} agree), {report.no_label} without label, "
                f"{report.unknown_label} not a district name, {report.outside} outside the boundaries\n"
            )
            for fid, name, label, actual, result in [r for r in report.rows if r[4] == "mismatch"][: opts["examples"]]:
                out.write(f"    {name or fid}: labelled '{label}', lies in {actual}\n")
            if writer:
                for row in report.rows:
                    writer.writerow([dataset.alternate, *row])
        if not checked_any:
            out.write("No dataset with a district field found (looked for: " + ", ".join(districts.LABEL_FIELDS) + ").\n")
