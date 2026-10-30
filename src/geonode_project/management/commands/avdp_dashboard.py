"""Create or update the "AVDP district overview" dashboard.

    python manage.py avdp_district_summary      # first: build/refresh the data
    python manage.py avdp_dashboard             # then: create/update the dashboard
    python manage.py avdp_dashboard --public    # visitors may view it (summary must be public too)

Re-running updates the same dashboard (same link). Requires the boundaries
(avdp_load_boundaries) and the district summary (avdp_district_summary).
"""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from geonode.base.models import TopicCategory
from geonode.geoapps.models import GeoApp
from geonode.layers.models import Dataset
from geonode_project.avdp import boundaries as bnd
from geonode_project.avdp import dashboard, portal_ops

SUMMARY_MARKER = "avdp-district-summary"


class Command(BaseCommand):
    help = "Create or update the AVDP district overview dashboard."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default=os.getenv("ADMIN_USERNAME", "admin"))
        parser.add_argument("--public", action="store_true", help="Let visitors view the dashboard")

    def handle(self, *args, **opts):
        try:
            owner = get_user_model().objects.get(username=opts["owner"])
        except get_user_model().DoesNotExist:
            raise CommandError(f"Owner '{opts['owner']}' does not exist.")
        summary = portal_ops.find_marked(Dataset, SUMMARY_MARKER)
        boundaries = portal_ops.find_marked(Dataset, bnd.MARKER)
        if not summary or not boundaries:
            raise CommandError("Run avdp_load_boundaries and avdp_district_summary first.")
        if opts["public"]:
            from guardian.shortcuts import get_groups_with_perms

            perms = get_groups_with_perms(summary.get_self_resource(), attach_perms=True)
            if not any(g.name == "anonymous" and "download_resourcebase" in p for g, p in perms.items()):
                raise CommandError(
                    "The district summary is not public, so visitors would see empty widgets. Run "
                    "`avdp_district_summary --audience public --public` first."
                )
        synthetic = summary.keywords.filter(name=settings.AVDP_DEMO_KEYWORD).exists()
        data = dashboard.build(summary, boundaries, synthetic)

        client = portal_ops.api_client(owner)
        existing = portal_ops.find_marked(GeoApp, dashboard.MARKER)
        if existing:
            response = client.patch(f"/api/v2/geoapps/{existing.pk}", {"data": data}, format="json")
            action = "updated"
        else:
            payload = {"name": "avdp_district_overview", "title": dashboard.TITLE, "resource_type": "dashboard", "data": data}
            response = client.post("/api/v2/geoapps", payload, format="json")
            action = "created"
        if response.status_code not in (200, 201):
            raise CommandError(f"Dashboard {action} failed ({response.status_code}): {str(response.data)[:400]}")
        app = GeoApp.objects.get(pk=response.data["geoapp"]["pk"])

        keywords = [dashboard.MARKER, "dashboard", "district summary"]
        if synthetic:
            keywords.append(settings.AVDP_DEMO_KEYWORD)
        portal_ops.manager(app).update(
            app.uuid,
            instance=app,
            vals={
                "title": dashboard.TITLE,
                "abstract": (
                    (f"{settings.AVDP_SYNTHETIC_NOTICE} " if synthetic else "")
                    + "Features per AVDP category and district, from the District summary layer. Figures are "
                    "counts of mapped features in datasets shared with AVDP Viewers or the public."
                ),
                "category": TopicCategory.objects.filter(identifier="farming").first(),
            },
            notify=False,
        )
        # GeoNode 5.1's GeoApp manager ignores keywords passed together with vals; set them directly.
        app.keywords.clear()
        app.keywords.add(*keywords)
        portal_ops.apply_permissions(app, public=opts["public"])
        self.stdout.write(self.style.SUCCESS(f"Dashboard {action}: {app.detail_url}"))
