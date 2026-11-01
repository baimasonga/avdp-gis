"""Create or update the "AVDP at district level" map story.

    python manage.py avdp_story            # after avdp_district_summary
    python manage.py avdp_story --public

Re-running updates the same story (same link).
"""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from geonode.base.models import TopicCategory
from geonode.geoapps.models import GeoApp
from geonode.layers.models import Dataset
from geonode_project.avdp import boundaries as bnd
from geonode_project.avdp import portal_ops, story

SUMMARY_MARKER = "avdp-district-summary"
WATER_MARKER = "avdp-demo-water_points"


class Command(BaseCommand):
    help = "Create or update the AVDP district map story."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default=os.getenv("ADMIN_USERNAME", "admin"))
        parser.add_argument("--water-points", help="Name of a water points dataset for the second chapter")
        parser.add_argument("--public", action="store_true", help="Let visitors view the story")

    def handle(self, *args, **opts):
        try:
            owner = get_user_model().objects.get(username=opts["owner"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Owner '{opts['owner']}' does not exist.")
        summary = portal_ops.find_marked(Dataset, SUMMARY_MARKER)
        boundaries = portal_ops.find_marked(Dataset, bnd.MARKER)
        if not summary or not boundaries:
            raise CommandError("Run avdp_load_boundaries and avdp_district_summary first.")
        if opts["water_points"]:
            water = Dataset.objects.filter(name=opts["water_points"]).first()
            if water is None:
                raise CommandError(f"No dataset named {opts['water_points']}.")
        else:
            water = portal_ops.find_marked(Dataset, WATER_MARKER)
        synthetic = summary.keywords.filter(name=settings.AVDP_DEMO_KEYWORD).exists() or bool(
            water and water.keywords.filter(name=settings.AVDP_DEMO_KEYWORD).exists()
        )
        data = story.build(summary, boundaries, water, synthetic)

        client = portal_ops.api_client(owner)
        existing = portal_ops.find_marked(GeoApp, story.MARKER)
        if existing:
            response = client.patch(f"/api/v2/geoapps/{existing.pk}", {"data": data}, format="json")
            action = "updated"
        else:
            payload = {"name": "avdp_district_story", "title": story.TITLE, "resource_type": "geostory", "data": data}
            response = client.post("/api/v2/geoapps", payload, format="json")
            action = "created"
        if response.status_code not in (200, 201):
            raise CommandError(f"Story {action} failed ({response.status_code}): {str(response.data)[:400]}")
        app = GeoApp.objects.get(pk=response.data["geoapp"]["pk"])
        portal_ops.manager(app).update(
            app.uuid,
            instance=app,
            vals={
                "title": story.TITLE,
                "abstract": (f"{settings.AVDP_SYNTHETIC_NOTICE} " if synthetic else "")
                + "A scrolling map story of AVDP features per district.",
                "category": TopicCategory.objects.filter(identifier="farming").first(),
            },
            notify=False,
        )
        keywords = [story.MARKER, "map story"] + ([settings.AVDP_DEMO_KEYWORD] if synthetic else [])
        app.keywords.clear()
        app.keywords.add(*keywords)  # GeoApp manager ignores keywords passed with vals
        portal_ops.apply_permissions(app, public=opts["public"])
        self.stdout.write(self.style.SUCCESS(f"Story {action}: {app.detail_url}"))
