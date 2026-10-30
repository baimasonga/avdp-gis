"""Unit tests for geonode_project.avdp.smart_mapping choices and generated styles (no database).

Run inside the django container:
    python -m unittest geonode_project.tests.test_smart_mapping -v
"""

import unittest
import xml.etree.ElementTree as ET

from geonode_project.avdp import smart_mapping as sm
from geonode_project.avdp import styles

SLD = "{http://www.opengis.net/sld}"


def _profile(kind="point", name="boreholes", strings=None, numbers=None, count=100, area=0.0):
    return sm.Profile(
        name=name,
        title=name.replace("_", " ").title(),
        kind=kind,
        geometry="geom",
        count=count,
        median_area_km2=area,
        strings=strings or {},
        numbers=numbers or {},
    )


def _titles(sld):
    root = ET.fromstring(sld)
    return [r.findtext(f"{SLD}Title") for r in root.iter(f"{SLD}Rule")]


class ChoiceTests(unittest.TestCase):
    def test_status_field_preferred_and_ids_skipped(self):
        prof = _profile(
            strings={
                "site_id": [f"W{i}" for i in range(5)],
                "name": ["A", "B", "C"],
                "district": ["Bo", "Kenema"],
                "status": ["Functional", "Needs repair"],
            }
        )
        self.assertEqual(sm.choose_type_field(prof), "status")

    def test_no_type_field_when_too_many_values(self):
        prof = _profile(strings={"owner": [str(i) for i in range(13)]})
        self.assertIsNone(sm.choose_type_field(prof))

    def test_amount_field_skips_ids_and_years(self):
        prof = _profile(numbers={"fid": (1, 9, []), "year": (2019, 2024, []), "users": (20, 900, [])})
        self.assertEqual(sm.choose_amount_field(prof), "users")

    def test_polygons_prefer_area(self):
        prof = _profile(kind="polygon", numbers={"members": (1, 50, []), "area_ha": (2, 80, [])})
        self.assertEqual(sm.choose_amount_field(prof), "area_ha")

    def test_theme_needs_matching_geometry(self):
        self.assertEqual(sm.guess_theme(_profile(name="community_wells")), "water_points")
        self.assertIsNone(sm.guess_theme(_profile(kind="polygon", name="community_wells")))
        self.assertEqual(sm.guess_theme(_profile(kind="line", name="feeder_roads_2024")), "feeder_roads")

    def test_status_field_uses_semantic_colours(self):
        prof = _profile(strings={"condition": ["Good", "Poor"]})
        self.assertEqual(sm.symbol_for(prof, None, "condition")["mode"], "status")


class PlanTests(unittest.TestCase):
    def test_points_get_all_alternatives(self):
        prof = _profile(strings={"status": ["Functional", "Not functional"]}, numbers={"users": (20, 900, [])})
        (title, default), alternates, choice = sm.plan(prof)
        self.assertEqual(title, "Types by Status")
        self.assertEqual(
            [suffix for suffix, _t, _s in alternates], ["location", "heatmap", "clusters", "size"]
        )
        self.assertEqual(choice["amount_field"], "users")
        for sld in [default] + [s for _x, _t, s in alternates]:
            root = ET.fromstring(sld)  # well-formed
            self.assertIn(styles.STYLE_MARKER, root.find(f".//{SLD}UserStyle/{SLD}Abstract").text)

    def test_polygons_get_choropleth_with_classes(self):
        prof = _profile(
            kind="polygon",
            strings={"landuse": ["Rice", "Cassava"]},
            numbers={"area_ha": (10, 500, [10, 50, 100, 200, 300, 500])},
            area=40,
        )
        _default, alternates, _choice = sm.plan(prof)
        suffixes = [s for s, _t, _x in alternates]
        self.assertEqual(suffixes, ["location", "choropleth"])
        titles = _titles(alternates[1][2])
        self.assertIn("300 – 500", titles)
        self.assertIn("No value", titles)

    def test_large_polygons_stay_polygons_at_overview(self):
        small = sm.plan(_profile(kind="polygon", area=2))[0][1]
        large = sm.plan(_profile(kind="polygon", area=200))[0][1]
        self.assertIn("centroid", small)
        self.assertNotIn("centroid", large)

    def test_lines_get_no_point_styles(self):
        prof = _profile(kind="line", strings={"surface": ["Gravel", "Earth"]}, numbers={"length_km": (1, 9, [])})
        _default, alternates, _choice = sm.plan(prof)
        self.assertEqual([s for s, _t, _x in alternates], ["location"])


class TileSafetyTests(unittest.TestCase):
    def test_cluster_grid_divides_tile_size(self):
        sld = styles.build_cluster_sld("x", "Clusters", "#2a6f97")
        cell = int(sld.split("<ogc:Literal>cellSize</ogc:Literal><ogc:Literal>")[1].split("<")[0])
        self.assertEqual(256 % cell, 0)
        self.assertIn('name="partials">true', sld)

    def test_heatmap_has_no_per_tile_transformation(self):
        sld = styles.build_heatmap_sld("x", "Heat map")
        self.assertNotIn("vec:Heatmap", sld)
        ET.fromstring(sld)


if __name__ == "__main__":
    unittest.main()
