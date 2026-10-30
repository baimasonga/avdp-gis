"""Unit tests for district boundaries, count choropleths and the dashboard layout (no database).

Run inside the django container:
    python -m unittest geonode_project.tests.test_districts -v
"""

import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from types import SimpleNamespace

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geonode_project.settings")
django.setup()

from geonode_project.avdp import boundaries as bnd  # noqa: E402
from geonode_project.avdp import dashboard, styles  # noqa: E402

SLD = "{http://www.opengis.net/sld}"
NAMES = [
    "Kailahun", "Kenema", "Kono", "Bombali", "Koinadugu", "Tonkolili", "Fabala", "Bo",
    "Bonthe", "Moyamba", "Pujehun", "Western Area Rural", "Western Area Urban", "Kambia", "Karene", "Port Loko",
]


def _square(x, y, size=0.1):
    return [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]


def _admin2(path, names=NAMES, offset=0.0):
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": _square(-12.5 + (i % 4) * 0.5 + offset, 7.5 + (i // 4) * 0.5)},
            "properties": {"adm2_name": n, "adm2_pcode": f"SL{i:04d}", "adm1_name": "P", "adm1_pcode": "SL01"},
        }
        for i, n in enumerate(names)
    ]
    with open(path, "w") as handle:
        json.dump({"type": "FeatureCollection", "features": features}, handle)


class DistrictKeyTests(unittest.TestCase):
    def test_spellings_match(self):
        self.assertEqual(bnd.district_key("Fabala"), bnd.district_key("Falaba District"))
        self.assertEqual(bnd.district_key("Western Urban"), bnd.district_key("Western Area Urban"))
        self.assertEqual(bnd.district_key("Freetown"), bnd.district_key("Western Area Urban"))
        self.assertEqual(bnd.district_key("Port-Loko"), bnd.district_key("Port Loko"))
        self.assertNotEqual(bnd.district_key("Bo"), bnd.district_key("Bombali"))

    def test_only_admin2_files_are_picked(self):
        self.assertTrue(bnd._is_adm2("sle_admin2.shp"))
        self.assertTrue(bnd._is_adm2("geoBoundaries-SLE-ADM2.geojson"))
        self.assertFalse(bnd._is_adm2("sle_admin2_em.shp"))
        self.assertFalse(bnd._is_adm2("sle_admin3.shp"))
        self.assertFalse(bnd._is_adm2("sle_adminlines.dbf"))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_zip_is_prepared_and_falaba_renamed(self):
        src = os.path.join(self.tmp, "sle_admin2.geojson")
        _admin2(src)
        archive = os.path.join(self.tmp, "b.zip")
        with zipfile.ZipFile(archive, "w") as z:
            z.write(src, "sle_admin2.geojson")
            z.writestr("sle_adminlines.dbf", b" " * (2 * 1024 * 1024))  # padded table: skipped, not rejected
        out, summary = bnd.prepare(archive, os.path.join(self.tmp, "work"))
        self.assertEqual(len(summary["districts"]), 16)
        self.assertIn("Falaba", summary["districts"])
        with open(out) as handle:
            props = [f["properties"] for f in json.load(handle)["features"]]
        self.assertEqual({p["district_source_name"] for p in props if p["district"] == "Falaba"}, {"Fabala"})
        self.assertTrue(all(p["area_sqkm"] > 0 for p in props))

    def test_wrong_count_is_rejected(self):
        src = os.path.join(self.tmp, "adm2.geojson")
        _admin2(src, NAMES[:14])
        with self.assertRaises(bnd.BoundaryError):
            bnd.prepare(src, self.tmp)

    def test_outside_sierra_leone_is_rejected(self):
        src = os.path.join(self.tmp, "adm2.geojson")
        _admin2(src, offset=20)
        with self.assertRaises(bnd.BoundaryError):
            bnd.prepare(src, self.tmp)


class CountChoroplethTests(unittest.TestCase):
    def test_zero_class_and_integer_labels(self):
        sld = styles.build_choropleth_sld("s", "t", "n", "features", [0, 1, 6, 18, 22], counts=True, small=False)
        titles = [r.findtext(f"{SLD}Title") for r in ET.fromstring(sld).iter(f"{SLD}Rule")]
        self.assertEqual(titles[0], "None")
        self.assertIn("1–5", titles)
        self.assertIn("18–22", titles)
        self.assertNotIn("centroid", sld)  # districts stay polygons

    def test_boundary_labels_once_per_district(self):
        sld = bnd.build_boundary_sld("b", geometry="the_geom")
        self.assertIn('name="interiorPoint"', sld)
        self.assertIn("the_geom", sld)
        self.assertIn('name="partials">true', sld)


class DashboardTests(unittest.TestCase):
    def _dataset(self, name):
        return SimpleNamespace(
            alternate=f"geonode:{name}",
            title=name,
            pk=1,
            ll_bbox_polygon=SimpleNamespace(extent=(-13.3, 6.9, -10.2, 10.0)),
            default_style=SimpleNamespace(name=name),
            use_featureinfo_custom_template=False,
            featureinfo_custom_template="",
        )

    def test_layout_fits_six_columns_without_overlap(self):
        data = dashboard.build(self._dataset("summary"), self._dataset("districts"), synthetic=True)
        cells = set()
        for widget in data["widgets"]:
            g = widget["dataGrid"]
            self.assertLessEqual(g["x"] + g["w"], 6)
            for x in range(g["x"], g["x"] + g["w"]):
                for y in range(g["y"], g["y"] + g["h"]):
                    self.assertNotIn((x, y), cells)
                    cells.add((x, y))
        self.assertEqual({l["i"] for l in data["layouts"]["md"]}, {w["id"] for w in data["widgets"]})
        self.assertIn("SYNTHETIC", data["widgets"][0]["text"])

    def test_chart_uses_trace_format(self):
        data = dashboard.build(self._dataset("summary"), self._dataset("districts"), synthetic=False)
        chart = next(w for w in data["widgets"] if w["widgetType"] == "chart")
        trace = chart["charts"][0]["traces"][0]
        self.assertEqual(chart["selectedChartId"], chart["charts"][0]["chartId"])
        self.assertEqual(trace["options"]["aggregateFunction"], "Sum")


if __name__ == "__main__":
    unittest.main()
