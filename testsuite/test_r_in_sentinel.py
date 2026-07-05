#!/usr/bin/env python3
# Test for r.in.sentinel
# Requires: GRASS GIS session in a latlong (WGS84) location
# Downloads: Small Sentinel-2 scenes over Plumergat (56400), France

import json
import os
import pathlib
import unittest

from grass.gunittest.case import TestCase
from grass.gunittest.main import test

try:
    import cubo  # noqa: F401

    HAS_CUBO = True
except ImportError:
    HAS_CUBO = False

# Plumergat, Brittany, France — small coastal area, good test for cloud cover
PLUMERGAT_N = 47.73
PLUMERGAT_S = 47.68
PLUMERGAT_E = -2.85
PLUMERGAT_W = -2.93


class TestRInSentinel(TestCase):
    """Tests for r.in.sentinel module."""

    output_prefix = "test_sentinel"

    @classmethod
    def setUpClass(cls):
        if not HAS_CUBO:
            raise unittest.SkipTest("cubo library not installed")
        cls.use_temp_region()
        cls.runModule(
            "g.region",
            n=PLUMERGAT_N,
            s=PLUMERGAT_S,
            e=PLUMERGAT_E,
            w=PLUMERGAT_W,
        )

    @classmethod
    def tearDownClass(cls):
        import grass.script as gs

        cls.del_temp_region()
        mapset = gs.gisenv()["MAPSET"]

        rasters = gs.list_grouped("raster").get(mapset, [])
        to_remove = [m for m in rasters if m.startswith(cls.output_prefix)]
        if to_remove:
            gs.run_command(
                "g.remove", type="raster", name=",".join(to_remove), flags="f"
            )

        groups = gs.list_grouped("group").get(mapset, [])
        to_remove_g = [g for g in groups if g.startswith(cls.output_prefix)]
        if to_remove_g:
            gs.run_command(
                "g.remove", type="group", name=",".join(to_remove_g), flags="f"
            )

        # Remove STRDS created by tests
        try:
            import grass.temporal as tgis

            tgis.init()
            strds_list = gs.read_command(
                "t.list", type="strds", columns="name"
            ).strip()
            for line in strds_list.splitlines():
                name = line.split("|")[0].strip()
                if name.startswith(cls.output_prefix):
                    gs.run_command("t.remove", flags="rf", inputs=name, type="strds")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _rasters_for_prefix(self, prefix):
        import grass.script as gs

        mapset = gs.gisenv()["MAPSET"]
        return [
            r
            for r in gs.list_grouped("raster").get(mapset, [])
            if r.startswith(prefix)
        ]

    def _groups_for_prefix(self, prefix):
        import grass.script as gs

        mapset = gs.gisenv()["MAPSET"]
        return [
            g
            for g in gs.list_grouped("group").get(mapset, [])
            if g.startswith(prefix)
        ]

    def _strds_maps(self, strds_name):
        """Return list of map names registered in a STRDS."""
        import grass.script as gs

        out = gs.read_command(
            "t.rast.list", input=strds_name, columns="name", flags="u"
        ).strip()
        return [
            line.split("|")[0].strip()
            for line in out.splitlines()
            if "|" in line
        ]

    # ------------------------------------------------------------------
    # Basic download + import
    # ------------------------------------------------------------------

    def test_download_and_import(self):
        """Basic Sentinel-2 download, import, and i.group creation."""
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B02,B03,B04,SCL",
            start="2023-07-01",
            end="2023-07-31",
            clouds=30,
            output=self.output_prefix,
        )
        rasters = self._rasters_for_prefix(self.output_prefix)
        self.assertGreater(len(rasters), 0, "No rasters were imported")

        groups = self._groups_for_prefix(self.output_prefix)
        self.assertGreater(len(groups), 0, "No i.group groups were created")

        # Each group name should match pattern prefix_YYYYMMDD
        for g in groups:
            suffix = g[len(self.output_prefix) + 1 :]
            self.assertEqual(len(suffix), 8, f"Group name suffix not YYYYMMDD: {g}")
            self.assertTrue(suffix.isdigit(), f"Group name suffix not numeric: {g}")

    # ------------------------------------------------------------------
    # Timestamps and semantic labels
    # ------------------------------------------------------------------

    def test_timestamps_set(self):
        """r.timestamp is set on every imported raster."""
        import grass.script as gs

        prefix = self.output_prefix + "_ts_check"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04",
            start="2023-07-01",
            end="2023-07-10",
            clouds=30,
            output=prefix,
        )
        rasters = self._rasters_for_prefix(prefix)
        self.assertGreater(len(rasters), 0, "No rasters to check timestamps on")
        for rmap in rasters:
            ts = gs.read_command("r.timestamp", map=rmap).strip()
            self.assertNotEqual(ts, "none", f"r.timestamp not set on {rmap}")
            self.assertGreater(len(ts), 0, f"Empty timestamp on {rmap}")

    def test_semantic_labels_set(self):
        """Semantic labels (e.g. S2_4) are set on each imported band."""
        import grass.script as gs

        prefix = self.output_prefix + "_sl_check"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04,B08,SCL",
            start="2023-07-01",
            end="2023-07-10",
            clouds=30,
            output=prefix,
        )
        rasters = self._rasters_for_prefix(prefix)
        self.assertGreater(len(rasters), 0, "No rasters imported for semantic label test")
        for rmap in rasters:
            info = gs.raster_info(rmap)
            label = info.get("semantic_label", "")
            self.assertTrue(
                label.startswith("S2_"),
                f"Unexpected semantic_label '{label}' on {rmap}",
            )

    # ------------------------------------------------------------------
    # JSON metadata
    # ------------------------------------------------------------------

    def test_json_metadata_written(self):
        """description.json files are created in cell_misc when -j is used."""
        import grass.script as gs

        prefix = self.output_prefix + "_jmeta"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04,SCL",
            start="2023-07-01",
            end="2023-07-15",
            clouds=30,
            output=prefix,
            flags="cj",
        )
        env = gs.gisenv()
        cell_misc = (
            pathlib.Path(env["GISDBASE"])
            / env["LOCATION_NAME"]
            / env["MAPSET"]
            / "cell_misc"
        )
        jsons = list(cell_misc.glob(f"{prefix}_*/description.json"))
        self.assertGreater(len(jsons), 0, "No description.json files written")

        # Validate required fields in one file
        required_fields = {
            "collection",
            "band",
            "date",
            "epsg",
            "resolution_m",
            "scl_masked",
        }
        with open(jsons[0]) as fh:
            data = json.load(fh)
        for field in required_fields:
            self.assertIn(field, data, f"Field '{field}' missing from description.json")
        self.assertEqual(data["collection"], "sentinel-2-l2a")
        self.assertIsInstance(data["epsg"], int)

    # ------------------------------------------------------------------
    # STRDS creation and registration
    # ------------------------------------------------------------------

    def test_strds_creation(self):
        """STRDS are created with one dataset per band and maps correctly registered."""
        import grass.script as gs
        import grass.temporal as tgis

        prefix = self.output_prefix + "_strds"
        strds_prefix = self.output_prefix + "_ts"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04,B08",
            start="2023-07-01",
            end="2023-07-15",
            clouds=30,
            output=prefix,
            strds=strds_prefix,
        )

        tgis.init()
        strds_list_raw = gs.read_command(
            "t.list", type="strds", columns="name"
        ).strip()
        strds_names = [
            line.split("|")[0].strip()
            for line in strds_list_raw.splitlines()
            if line.strip()
        ]
        mapset = gs.gisenv()["MAPSET"]
        our_strds = [
            s for s in strds_names if s.startswith(strds_prefix)
        ]
        # One STRDS per band requested
        self.assertIn(
            f"{strds_prefix}_B04", our_strds, "STRDS for B04 not created"
        )
        self.assertIn(
            f"{strds_prefix}_B08", our_strds, "STRDS for B08 not created"
        )

        # Each STRDS must contain at least one map
        for sname in [f"{strds_prefix}_B04", f"{strds_prefix}_B08"]:
            maps = self._strds_maps(sname)
            self.assertGreater(
                len(maps), 0, f"STRDS '{sname}' is empty"
            )

    def test_strds_timestamps(self):
        """Maps in STRDS have valid start_time (from r.timestamp)."""
        import grass.script as gs
        import grass.temporal as tgis

        prefix = self.output_prefix + "_strds_ts"
        strds_prefix = self.output_prefix + "_tsts"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04",
            start="2023-07-01",
            end="2023-07-15",
            clouds=30,
            output=prefix,
            strds=strds_prefix,
        )

        tgis.init()
        strds_name = f"{strds_prefix}_B04"
        out = gs.read_command(
            "t.rast.list",
            input=strds_name,
            columns="name,start_time",
            flags="u",
        ).strip()
        rows = [line for line in out.splitlines() if "|" in line]
        self.assertGreater(len(rows), 0, "No maps found in STRDS")
        for row in rows:
            parts = row.split("|")
            ts = parts[1].strip()
            self.assertNotEqual(
                ts, "None", f"Map in STRDS has null start_time: {row}"
            )
            # Expect format YYYY-MM-DD HH:MM:SS
            self.assertRegex(
                ts,
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",
                f"Unexpected timestamp format: {ts}",
            )

    def test_strds_with_scl_masking(self):
        """STRDS creation works correctly when combined with SCL cloud masking."""
        import grass.script as gs
        import grass.temporal as tgis

        prefix = self.output_prefix + "_strds_scl"
        strds_prefix = self.output_prefix + "_tsscl"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04,B08,SCL",
            start="2023-08-01",
            end="2023-08-15",
            clouds=50,
            output=prefix,
            strds=strds_prefix,
            flags="c",
        )

        tgis.init()
        strds_name = f"{strds_prefix}_B04"
        maps = self._strds_maps(strds_name)
        self.assertGreater(len(maps), 0, f"STRDS '{strds_name}' is empty after SCL masking")

    # ------------------------------------------------------------------
    # SCL cloud masking
    # ------------------------------------------------------------------

    def test_scl_cloud_masking(self):
        """SCL masking reduces non-null cell count compared to unmasked import."""
        import grass.script as gs

        prefix_raw = self.output_prefix + "_raw"
        prefix_masked = self.output_prefix + "_sclmasked"

        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04,SCL",
            start="2023-07-01",
            end="2023-07-10",
            clouds=60,
            output=prefix_raw,
        )
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B04,SCL",
            start="2023-07-01",
            end="2023-07-10",
            clouds=60,
            output=prefix_masked,
            flags="c",
        )

        raw_maps = self._rasters_for_prefix(prefix_raw + "_")
        b04_raw = [m for m in raw_maps if m.endswith("_B04")]
        b04_masked = [
            m.replace(prefix_raw, prefix_masked) for m in b04_raw
        ]

        for raw, masked in zip(sorted(b04_raw), sorted(b04_masked)):
            if masked not in self._rasters_for_prefix(prefix_masked):
                continue
            raw_stats = gs.parse_command("r.univar", map=raw, flags="g")
            masked_stats = gs.parse_command("r.univar", map=masked, flags="g")
            raw_n = int(raw_stats.get("n", 0))
            masked_n = int(masked_stats.get("n", 0))
            # Cloud-masked map should have fewer or equal valid pixels
            self.assertLessEqual(
                masked_n,
                raw_n,
                f"Masked map '{masked}' has more valid pixels than raw '{raw}'",
            )

    # ------------------------------------------------------------------
    # Spectral cloud index masking
    # ------------------------------------------------------------------

    def test_spectral_cloud_mask(self):
        """Spectral CSI masking runs without error and produces rasters."""
        prefix = self.output_prefix + "_smask"
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B02,B04,B08",
            start="2023-09-01",
            end="2023-09-15",
            output=prefix,
            flags="s",
        )
        rasters = self._rasters_for_prefix(prefix)
        self.assertGreater(len(rasters), 0, "No rasters with spectral masking")

    # ------------------------------------------------------------------
    # List-only mode
    # ------------------------------------------------------------------

    def test_list_scenes(self):
        """List mode (-l) exits without importing anything."""
        import grass.script as gs

        prefix = self.output_prefix + "_list"
        mapset = gs.gisenv()["MAPSET"]
        before = set(gs.list_grouped("raster").get(mapset, []))

        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            start="2023-07-01",
            end="2023-07-10",
            output=prefix,
            flags="l",
        )
        after = set(gs.list_grouped("raster").get(mapset, []))
        new_rasters = after - before
        self.assertEqual(
            len(new_rasters), 0, f"List mode imported rasters: {new_rasters}"
        )


if __name__ == "__main__":
    test()
