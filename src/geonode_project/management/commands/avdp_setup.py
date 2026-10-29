"""Idempotent portal configuration for the AVDP GIS Portal.

Safe to run on every deployment. It only creates or updates AVDP-specific
objects and never removes users, groups or resources:

* loads the AVDP thesauri (dataset category, data status) and configures
  them as single-choice catalogue facets;
* creates the ``avdp-viewers`` and ``avdp-editors`` groups;
* grants the native ``base.add_resourcebase`` (upload) permission to
  ``avdp-editors``.

Usage::

    python manage.py avdp_setup
"""

import os

from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from geonode.base.models import Thesaurus
from geonode.groups.models import GroupProfile

THESAURI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "thesauri")

# identifier -> (order, card_min, card_max)
THESAURI = {
    "avdp-categories": (10, 0, 1),
    "avdp-data-status": (20, 0, 1),
}

GROUPS = {
    "avdp-viewers": (
        "AVDP Viewers",
        "Staff and partners who may view and download resources shared with this group.",
    ),
    "avdp-editors": (
        "AVDP Editors",
        "Staff who may upload datasets and maintain resources shared with this group.",
    ),
}


class Command(BaseCommand):
    help = "Configure AVDP thesauri, role groups and upload permissions (idempotent)."

    def handle(self, *args, **options):
        self._load_thesauri()
        with transaction.atomic():
            groups = self._ensure_groups()
            self._grant_upload(groups["avdp-editors"])
        self.stdout.write(self.style.SUCCESS("AVDP setup complete."))

    def _load_thesauri(self):
        for identifier, (order, card_min, card_max) in THESAURI.items():
            path = os.path.join(THESAURI_DIR, f"{identifier}.rdf")
            # GeoNode's own loader; "update" creates or updates without duplicates.
            call_command("thesaurus", "load", "--file", path, "--identifier", identifier, "--action", "update")
            thesaurus = Thesaurus.objects.get(identifier=identifier)
            changed = (thesaurus.order, thesaurus.card_min, thesaurus.card_max, thesaurus.facet) != (
                order,
                card_min,
                card_max,
                True,
            )
            if changed:
                thesaurus.order, thesaurus.card_min, thesaurus.card_max, thesaurus.facet = (
                    order,
                    card_min,
                    card_max,
                    True,
                )
                thesaurus.save()
            self.stdout.write(
                f"Thesaurus {identifier}: {thesaurus.thesaurus.count()} keywords"
                f"{' (configured)' if changed else ''}"
            )

    def _ensure_groups(self):
        groups = {}
        for slug, (title, description) in GROUPS.items():
            profile = GroupProfile.objects.filter(slug=slug).first()
            if profile is None:
                group, _ = Group.objects.get_or_create(name=slug)
                profile = GroupProfile.objects.create(
                    group=group, slug=slug, title=title, description=description, access="private"
                )
                self.stdout.write(f"Created group {slug}")
            else:
                self.stdout.write(f"Group {slug} already exists")
            groups[slug] = profile.group
        return groups

    def _grant_upload(self, group):
        perm = Permission.objects.get(content_type__app_label="base", codename="add_resourcebase")
        if not group.permissions.filter(pk=perm.pk).exists():
            group.permissions.add(perm)
            self.stdout.write(f"Granted base.add_resourcebase to {group.name}")
