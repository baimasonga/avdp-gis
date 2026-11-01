"""Unit tests for KoboToolbox/ODK submission handling and the map story (no network, no database).

Run inside the django container:
    python -m unittest geonode_project.tests.test_fieldsync -v
"""

import os
import unittest
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geonode_project.settings")
django.setup()

from geonode_project.avdp import fieldsync, story  # noqa: E402

KOBO = [
    {
        "_id": 7, "formhub/uuid": "x", "__version__": "v1", "meta/instanceID": "uuid:1",
        "grp_site/site_name": "Well 1", "grp_site/gps": "7.96 -11.74 120 5", "grp_status/status": "Functional",
        "respondent_name": "Someone", "phone_number": "000", "_geolocation": [7.96, -11.74],
        "_submission_time": "2026-10-01T09:00:00", "_attachments": [],
    },
    {"_id": 8, "grp_site/site_name": "Well 2", "grp_site/gps": None, "_geolocation": [None, None]},
]
ODK = [
    {
        "__id": "uuid:1",
        "__system": {"submissionDate": "2026-10-02T09:00:00Z", "submitterName": "enumerator"},
        "site": {"site_name": "Store 1", "location": {"type": "Point", "coordinates": [-11.19, 7.88, 100]}},
        "store": {"condition": "Good", "capacity_t": 40, "farmer_name": "Someone"},
        "meta": {"instanceID": "uuid:1"},
    }
]


class KoboTests(unittest.TestCase):
    def setUp(self):
        self.rows = fieldsync.to_rows(KOBO, "kobo")

    def test_location_from_geopoint_and_skips_missing(self):
        self.assertEqual(len(self.rows.features), 1)
        self.assertEqual(self.rows.features[0]["geometry"]["coordinates"], [-11.74, 7.96])
        self.assertEqual(self.rows.skipped_no_location, 1)

    def test_groups_dropped_system_fields_kept_or_removed(self):
        props = self.rows.features[0]["properties"]
        self.assertEqual(props["site_name"], "Well 1")
        self.assertEqual(props["status"], "Functional")
        self.assertEqual(props["submission_id"], 7)
        self.assertEqual(props["submitted"], "2026-10-01T09:00:00")
        for system in ("formhub_uuid", "uuid", "__version__", "instanceid", "_attachments"):
            self.assertNotIn(system, props)

    def test_personal_data_left_out_unless_kept(self):
        self.assertEqual(self.rows.excluded, {"respondent_name", "phone_number"})
        kept = fieldsync.to_rows(KOBO, "kobo", keep_personal=["phone_number"])
        self.assertIn("phone_number", kept.features[0]["properties"])


class OdkTests(unittest.TestCase):
    def test_geojson_point_and_nested_groups(self):
        rows = fieldsync.to_rows(ODK, "odk")
        f = rows.features[0]
        self.assertEqual(f["geometry"]["coordinates"], [-11.19, 7.88])
        self.assertEqual(f["properties"]["condition"], "Good")
        self.assertEqual(f["properties"]["capacity_t"], 40)
        self.assertEqual(f["properties"]["submitted"], "2026-10-02T09:00:00Z")
        self.assertIn("farmer_name", rows.excluded)

    def test_same_columns_on_every_feature(self):
        subs = ODK + [{"__id": "uuid:2", "site": {"location": {"type": "Point", "coordinates": [-11.0, 8.0]}}}]
        rows = fieldsync.to_rows(subs, "odk")
        self.assertEqual(set(rows.features[0]["properties"]), set(rows.features[1]["properties"]))


class StoryTests(unittest.TestCase):
    def _ds(self, name):
        return SimpleNamespace(
            alternate=f"geonode:{name}", title=name, pk=1,
            ll_bbox_polygon=SimpleNamespace(extent=(-13.3, 6.9, -10.2, 10.0)),
            default_style=SimpleNamespace(name=name), use_featureinfo_custom_template=False,
            featureinfo_custom_template="",
        )

    def test_every_map_background_points_to_a_resource(self):
        data = story.build(self._ds("summary"), self._ds("districts"), self._ds("water"), synthetic=True)
        ids = {r["id"] for r in data["resources"]}
        refs = []

        def walk(items):
            for item in items:
                bg = item.get("background") or {}
                if bg.get("resourceId"):
                    refs.append(bg["resourceId"])
                walk(item.get("contents", []))

        walk(data["sections"])
        self.assertTrue(refs)
        self.assertTrue(set(refs) <= ids)
        self.assertEqual(len(data["resources"]), 2)
        self.assertIn("SYNTHETIC", data["sections"][1]["contents"][0]["contents"][0]["html"])


if __name__ == "__main__":
    unittest.main()
