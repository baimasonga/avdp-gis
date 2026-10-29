"""Validate the AVDP synthetic demo package without importing anything.

Usage::

    python manage.py avdp_validate_demo /usr/src/project/data/demo/AVDP_Synthetic_GIS_Sample_Package.zip
    python manage.py avdp_validate_demo <package.zip> --json report.json
"""

import json
import tempfile

from django.core.management.base import BaseCommand, CommandError

from geonode_project.avdp import demo_package as dp


def print_report(stdout, style, result):
    for layer in result["layers"]:
        mark = style.SUCCESS("OK  ") if layer["ok"] else style.ERROR("FAIL")
        crs = ", ".join(sorted({s["crs"] or "?" for s in layer["sources"].values()})) or "-"
        geom = ", ".join(sorted({g for s in layer["sources"].values() for g in s["geometry"]})) or "-"
        stdout.write(
            f"{mark} {layer['title']:<22} {layer['features']:>4}/{layer['expected']:<4} "
            f"csv={layer['csv_rows'] if layer['csv_rows'] is not None else '-':<4} {geom:<14} {crs} "
            f"[{', '.join(layer['sources'])}]"
        )
        for err in layer["errors"]:
            stdout.write(style.ERROR(f"       error: {err}"))
        for warn in layer["warnings"]:
            stdout.write(style.WARNING(f"       warning: {warn}"))
    total = f"Total features: {result['total_features']} (expected {result['expected_total']})"
    stdout.write(style.SUCCESS(total) if result["total_features"] == result["expected_total"] else style.ERROR(total))


class Command(BaseCommand):
    help = "Validate the AVDP synthetic demo package (geometry, counts, CRS, extent, attributes)."

    def add_arguments(self, parser):
        parser.add_argument("package", help="Path to the package .zip or an extracted directory")
        parser.add_argument("--json", dest="json_path", help="Write the full report to this JSON file")

    def handle(self, *args, **options):
        result = validate_package(options["package"])
        print_report(self.stdout, self.style, result)
        if options["json_path"]:
            with open(options["json_path"], "w") as handle:
                json.dump(result, handle, indent=2)
        if not result["ok"]:
            raise CommandError("Validation failed.")
        self.stdout.write(self.style.SUCCESS("Package is valid."))


def validate_package(package_path):
    import os

    try:
        if os.path.isdir(package_path):
            return dp.summary(dp.validate(dp.discover(package_path)))
        with tempfile.TemporaryDirectory(prefix="avdp_validate_") as tmp:
            dp.safe_extract(package_path, tmp)
            return dp.summary(dp.validate(dp.discover(tmp)))
    except (dp.PackageError, FileNotFoundError) as exc:
        raise CommandError(str(exc))
