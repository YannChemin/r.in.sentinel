#!/usr/bin/env python3
# Test for r.in.sentinel
# Requires: GRASS GIS session in a latlong (WGS84) location
# Downloads: A small Sentinel-2 scene over Plumergat (56400), France

import os
import unittest

from grass.gunittest.case import TestCase
from grass.gunittest.main import test

try:
    import cubo

    HAS_CUBO = True
except ImportError:
    HAS_CUBO = False

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
        # Set region to Plumergat area (requires WGS84/latlong location)
        cls.runModule(
            "g.region",
            n=PLUMERGAT_N,
            s=PLUMERGAT_S,
            e=PLUMERGAT_E,
            w=PLUMERGAT_W,
        )

    @classmethod
    def tearDownClass(cls):
        cls.del_temp_region()
        import grass.script as gs

        mapset = gs.gisenv()["MAPSET"]
        maps = gs.list_grouped("raster").get(mapset, [])
        to_remove = [m for m in maps if m.startswith(cls.output_prefix)]
        if to_remove:
            gs.run_command(
                "g.remove",
                type="raster",
                name=",".join(to_remove),
                flags="f",
            )
        groups = gs.list_grouped("group").get(mapset, [])
        to_remove_g = [g for g in groups if g.startswith(cls.output_prefix)]
        if to_remove_g:
            gs.run_command(
                "g.remove",
                type="group",
                name=",".join(to_remove_g),
                flags="f",
            )

    def test_download_and_import(self):
        """Test basic Sentinel-2 download, import, and group creation over Plumergat."""
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B02,B03,B04,SCL",
            start="2023-07-01",
            end="2023-07-31",
            clouds=30,
            output=self.output_prefix,
            overwrite=True,
        )
        import grass.script as gs

        mapset = gs.gisenv()["MAPSET"]
        rasters = gs.list_grouped("raster").get(mapset, [])
        sentinel_rasters = [r for r in rasters if r.startswith(self.output_prefix)]
        self.assertTrue(len(sentinel_rasters) > 0, "No rasters were imported")

        groups = gs.list_grouped("group").get(mapset, [])
        sentinel_groups = [g for g in groups if g.startswith(self.output_prefix)]
        self.assertTrue(len(sentinel_groups) > 0, "No i.group groups were created")

    def test_cloud_masking(self):
        """Test download with SCL-based cloud masking."""
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B02,B04,B08,SCL",
            start="2023-08-01",
            end="2023-08-15",
            clouds=50,
            output=self.output_prefix + "_cmask",
            flags="c",
            overwrite=True,
        )

    def test_spectral_cloud_mask(self):
        """Test download with spectral cloud index masking."""
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            bands="B02,B04,B08",
            start="2023-09-01",
            end="2023-09-15",
            output=self.output_prefix + "_smask",
            flags="s",
            overwrite=True,
        )

    def test_list_scenes(self):
        """Test listing available scenes without downloading."""
        self.assertModule(
            "r.in.sentinel",
            collection="sentinel-2-l2a",
            start="2023-07-01",
            end="2023-07-10",
            output=self.output_prefix + "_list",
            flags="l",
        )


if __name__ == "__main__":
    test()
