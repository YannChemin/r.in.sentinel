# r.in.sentinel

A [GRASS GIS](https://grass.osgeo.org/) addon that downloads and
imports Sentinel-2 imagery directly into the current mapset using the
[cubo](https://github.com/ESDS-Leipzig/cubo) Python library — from
**Microsoft Planetary Computer** (default, no account needed) or
**Google Earth Engine** (credentials required) — with two optional
cloud-masking methods applied on import.

```
g.region n=47.73 s=47.68 e=-2.85 w=-2.93

r.in.sentinel collection=sentinel-2-l2a \
  bands=B02,B03,B04,B08,B8A,B11,B12,SCL \
  start=2023-07-01 end=2023-07-31 clouds=20 \
  output=s2_plumergat
```

## Why

Sentinel-2 imagery is a common climate/land-surface input alongside
the ERA5(-Land) reanalysis and Copernicus DEM this ecosystem already
fetches with no account or API key
([t.in.era5](https://github.com/YannChemin/t.in.era5),
[r.in.dem](https://github.com/YannChemin/r.in.dem)) — this module
closes the same gap for optical satellite imagery: point it at a
region and a date range, and it hands back grouped, cloud-masked
GRASS rasters, no manual STAC querying or GDAL wrangling needed.

## How it works

The module reads the current computational region to determine the
centre coordinates (reprojected to WGS84) and the download extent (the
larger of the region's NS/EW extent). Each acquisition date is
downloaded as a `cubo` cube, sliced into individual bands, imported
with `r.import` (`extent=region`, so reprojection and clipping to the
current region happen automatically), and grouped with `i.group`.

### Output naming

Raster maps: `{output}_{YYYYMMDD}_{band}`, e.g. `sentinel2_20230615_B04`.
One `i.group` group per acquisition date: `{output}_{YYYYMMDD}`.

### Backends

- **Microsoft Planetary Computer** (default) — collection
  `sentinel-2-l2a` (surface reflectance), no account required. The
  `stac` option points to any other STAC-compliant endpoint (e.g. AWS
  Earth Search).
- **Google Earth Engine** (`-g` flag) — set `collection` to the GEE
  asset ID (e.g. `COPERNICUS/S2_SR_HARMONIZED`); requires
  `earthengine authenticate` beforehand.

### Cloud removal

Two mutually exclusive methods:

- **`-c`** — SCL-based masking (recommended for L2A): keeps only
  Scene-Classification-Layer classes 4/5/6/11 (vegetation, not
  vegetated, water, snow/ice), nulling everything else. The SCL band is
  added to the download automatically when requested.
- **`-s`** — Spectral Cloud Score Index (fallback for L1C, or when SCL
  is unavailable): `CSI = (B02 + B04) / (2×B08 + ε)`, flagged as cloud
  when `CSI > 0.35` and `B02 > 0.175`. Needs B02, B04, and B08 or B8A.

### Other flags

- **`-l`** — list available acquisition dates and exit, no download.
- **`-p`** — print the resolved region info and exit.

## Options

| Option | Description |
|---|---|
| `collection` | STAC collection (Planetary Computer) or GEE asset ID |
| `bands` | Sentinel-2 bands to download |
| `start`, `end` | Date range (`YYYY-MM-DD`) |
| `resolution` | Spatial resolution in meters |
| `clouds` | Maximum scene cloud-cover percentage |
| `output` | Prefix for output raster maps/groups |
| `stac` | Custom STAC endpoint URL (Planetary Computer backend) |
| `-g` | Use Google Earth Engine instead of Planetary Computer |
| `-c` | SCL-based cloud masking |
| `-s` | Spectral Cloud Score Index masking |
| `-l` | List scenes and exit |
| `-p` | Print region info and exit |

## Requirements

```
pip install cubo rasterio rioxarray
```

For Google Earth Engine support:

```
pip install earthengine-api
earthengine authenticate
```

**PROJ ≥ 7.0 is required.** This module writes UTM GeoTIFFs whose CRS
is resolved via `rasterio.crs.CRS.from_epsg()`, which needs the
`proj.db` authority database introduced in PROJ 6 and stabilized in
PROJ 7 — with an older PROJ, `r.import` can fail with a CRS error or
silently produce an unknown/incorrect projection. PROJ 9.x, Rasterio
≥ 1.3, and GDAL ≥ 3.5 are recommended. Check with:

```
proj --version
python3 -c "import pyproj; print(pyproj.proj_version_str)"
```

## Install

```
g.extension extension=r.in.sentinel url=https://github.com/YannChemin/r.in.sentinel
```

## Testing

```
testsuite/test_r_in_sentinel.py
```

Downloads a small real Sentinel-2 scene over Plumergat (56400,
France) via Planetary Computer to confirm the download → slice →
import → group pipeline works end-to-end; skipped automatically if
`cubo` isn't installed, and needs a WGS84/latlong GRASS location plus
live network access otherwise.

## License

Public domain — see [LICENSE](LICENSE) (Unlicense).

## References

- Montero, D. et al. (2023). *A standardized catalogue of spectral
  indices to advance the use of remote sensing in Earth system
  research.* Scientific Data.
- [cubo documentation](https://github.com/ESDS-Leipzig/cubo)
- [Microsoft Planetary Computer STAC](https://planetarycomputer.microsoft.com/api/stac/v1)
- [Sentinel-2 SCL classification](https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview)

## See also

- [r.hydro.hbv](https://github.com/YannChemin/r.hydro.hbv) — the HBV
  hydrological model this ecosystem's other no-account-needed importers
  ([t.in.era5](https://github.com/YannChemin/t.in.era5),
  [r.in.dem](https://github.com/YannChemin/r.in.dem)) feed
