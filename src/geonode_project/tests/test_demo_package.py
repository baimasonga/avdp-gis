"""Unit tests for geonode_project.avdp.demo_package (GDAL only, no database).

Run inside the django container:
    python -m unittest geonode_project.tests.test_demo_package -v
"""

import os
import shutil
import stat
import tempfile
import unittest
import zipfile

from osgeo import ogr, osr

from geonode_project.avdp import demo_package as dp
from geonode_project.avdp import styles
from geonode_project.tests.make_test_package import build


class SafeExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _zip(self, entries):
        path = os.path.join(self.tmp, "p.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name, data in entries:
                if isinstance(name, zipfile.ZipInfo):
                    z.writestr(name, data)
                else:
                    z.writestr(name, data)
        return path

    def test_rejects_path_traversal(self):
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(self._zip([("../evil.csv", "x")]), self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.csv")))

    def test_rejects_absolute_path(self):
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(self._zip([("/etc/evil.csv", "x")]), self.dest)

    def test_rejects_symlink(self):
        info = zipfile.ZipInfo("link.csv")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(self._zip([(info, "/etc/passwd")]), self.dest)

    def test_rejects_unexpected_file_type(self):
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(self._zip([("run.sh", "#!/bin/sh")]), self.dest)

    def test_rejects_unsafe_characters(self):
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(self._zip([("bad$(name).csv", "x")]), self.dest)

    def test_rejects_zip_bomb_ratio(self):
        path = os.path.join(self.tmp, "bomb.zip")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("big.csv", "0" * (20 * 1024 * 1024))
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(path, self.dest)

    def test_rejects_non_zip(self):
        path = os.path.join(self.tmp, "not.zip")
        with open(path, "w") as handle:
            handle.write("not a zip")
        with self.assertRaises(dp.PackageError):
            dp.safe_extract(path, self.dest)


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.zip = build(os.path.join(cls.tmp, "fixture.zip"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _extract(self):
        dest = tempfile.mkdtemp(dir=self.tmp)
        dp.safe_extract(self.zip, dest)
        return dest

    def test_fixture_is_valid(self):
        result = dp.summary(dp.validate(dp.discover(self._extract())))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["total_features"], 140)

    def test_discovery_does_not_confuse_plot_layers(self):
        found = dp.discover(self._extract())
        self.assertIn("demonstration_plots", found["demonstration_plots"].geojson)
        self.assertIn("farm_plots", found["farm_plots"].geojson)

    def test_missing_layer_fails(self):
        root = self._extract()
        for dirpath, _, files in os.walk(root):
            for f in files:
                if f.startswith("water_points"):
                    os.remove(os.path.join(dirpath, f))
        result = dp.summary(dp.validate(dp.discover(root)))
        self.assertFalse(result["ok"])

    def test_wrong_feature_count_fails(self):
        root = self._extract()
        path = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f == "grain_stores.geojson"][0]
        ds = ogr.Open(path, 1)
        layer = ds.GetLayer(0)
        layer.DeleteFeature(layer.GetNextFeature().GetFID())
        ds = None
        report = [r for r in dp.validate(dp.discover(root)) if r.key == "grain_stores"][0]
        self.assertFalse(report.ok)

    def test_wrong_crs_fails(self):
        root = self._extract()
        shp = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f == "feeder_roads.shp"][0]
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32629)  # UTM 29N
        with open(shp[:-4] + ".prj", "w") as handle:
            handle.write(srs.ExportToWkt())
        report = [r for r in dp.validate(dp.discover(root)) if r.key == "feeder_roads"][0]
        self.assertFalse(report.ok)
        self.assertTrue(any("EPSG:4326" in e for e in report.sources["shapefile"].errors))

    def test_missing_prj_fails(self):
        root = self._extract()
        shp = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f == "water_points.shp"][0]
        os.remove(shp[:-4] + ".prj")
        report = [r for r in dp.validate(dp.discover(root)) if r.key == "water_points"][0]
        self.assertFalse(report.ok)


class StyleTests(unittest.TestCase):
    def test_categorised_sld_is_well_formed(self):
        from xml.etree import ElementTree

        sld = styles.build_sld("water_points", "avdp_demo_water_points", "Water points", ["point"],
                               "status", ["Functional", "Needs <repair>"])
        root = ElementTree.fromstring(sld)
        rules = root.findall(".//{http://www.opengis.net/sld}Rule")
        self.assertEqual(len(rules), 3)  # two categories + "other"

    def test_single_rule_without_field(self):
        sld = styles.build_sld("feeder_roads", "r", "Roads", ["line"])
        self.assertIn("LineSymbolizer", sld)


if __name__ == "__main__":
    unittest.main()
