# r.in.sentinel

A [GRASS GIS](https://grass.osgeo.org/) addon that downloads and
imports **Sentinel-1 SAR** and **Sentinel-2 optical** imagery directly
into the current mapset using the
[cubo](https://github.com/ESDS-Leipzig/cubo) Python library — from
**Microsoft Planetary Computer** (default, no account needed) or
**Google Earth Engine** (credentials required).

```
g.region n=47.73 s=47.68 e=-2.85 w=-2.93

# Sentinel-2 (optical, cloud-masked)
r.in.sentinel collection=sentinel-2-l2a \
  bands=B02,B03,B04,B08,B8A,B11,B12,SCL \
  start=2023-07-01 end=2023-07-31 clouds=20 \
  output=s2_plumergat

# Sentinel-1 SAR (VV/VH, cloud-independent)
r.in.sentinel collection=sentinel-1-rtc \
  start=2023-07-01 end=2023-07-31 \
  output=s1_plumergat
```

## Why

Sentinel-1 and Sentinel-2 are the most widely used free satellite
missions for land-surface analysis. This module closes the same
no-account gap that
[t.in.era5](https://github.com/YannChemin/t.in.era5) and
[r.in.dem](https://github.com/YannChemin/r.in.dem) close for
reanalysis and elevation data: point it at a region and a date range
and it hands back grouped, optionally cloud-masked GRASS rasters —
no manual STAC querying or GDAL wrangling required.

## Supported sensors

### Sentinel-1 SAR (10 m, C-band)

| Collection ID | Backend | Default bands |
|---|---|---|
| `sentinel-1-rtc` | Planetary Computer | `vv`, `vh` |
| `sentinel-1-grd` | Planetary Computer | `vv`, `vh` |
| `COPERNICUS/S1_GRD` | GEE (`-g`) | `VV`, `VH` |

Sentinel-1 is a radar sensor — it images through clouds and at night.
Cloud masking flags (`-c`, `-s`, `-m`) and the RGB composite flag
(`-r`) are automatically ignored with a warning when a Sentinel-1
collection is selected. A grey color table is applied to each imported
band automatically.

### Sentinel-2 optical (10/20/60 m)

| Collection ID | Backend | Default bands |
|---|---|---|
| `sentinel-2-l2a` | Planetary Computer | `B02,B03,B04,B08,B8A,B11,B12,SCL` |
| `COPERNICUS/S2_SR_HARMONIZED` | GEE (`-g`) | same |

## How it works

The module reads the current computational region to determine the
centre coordinates (reprojected to WGS84) and the download extent.
Each acquisition date is fetched as a `cubo` data cube, sliced into
individual bands, written to a temporary GeoTIFF, and imported with
`r.import` (`extent=region`) so reprojection and clipping happen
automatically. Bands are grouped per date with `i.group`.

### Output naming

Raster maps: `{output}_{YYYYMMDD}_{band}`, e.g.
`s1_plumergat_20230715_vv`, `s2_plumergat_20230615_B04`.
One `i.group` group per acquisition date: `{output}_{YYYYMMDD}`.

### Backends

- **Microsoft Planetary Computer** (default) — no account required.
  The `stac` option accepts any other STAC-compliant endpoint
  (e.g. AWS Earth Search).
- **Google Earth Engine** (`-g` flag) — set `collection` to the GEE
  asset ID; requires `earthengine authenticate` beforehand.

### Cloud removal (Sentinel-2 only)

Three mutually exclusive methods, automatically skipped for Sentinel-1:

- **`-c`** — SCL-based masking (recommended for L2A): keeps only
  Scene-Classification-Layer classes 4/5/6/11 (vegetation, not
  vegetated, water, snow/ice). SCL band is auto-added if not listed.
- **`-s`** — Spectral Cloud Score Index (fallback for L1C):
  `CSI = (B02 + B04) / (2×B08 + ε)`, flagged cloud when
  `CSI > 0.35` and `B02 > 0.175`. Needs B02, B04, B08/B8A.
- **`-m`** — `i.sentinel.mask` cloud masking (requires all 7 optical
  bands; auto-adds missing ones).

### Other flags

- **`-r`** — create a true-color RGB composite with `r.composite`
  after import (Sentinel-2 only; auto-adds B02/B03/B04 if needed).
- **`-l`** — list available acquisition dates and exit, no download.
- **`-p`** — print the resolved region info and exit.
- **`-j`** — write per-band metadata JSON to
  `$MAPSET/cell_misc/<map>/description.json`.

## Options

| Option / flag | Description |
|---|---|
| `collection` | STAC collection or GEE asset ID (see tables above) |
| `bands` | Bands to download (auto-detected from collection if omitted) |
| `start`, `end` | Date range (`YYYY-MM-DD`) |
| `resolution` | Spatial resolution in meters (default: 10) |
| `clouds` | Maximum scene cloud-cover % (Sentinel-2 only) |
| `output` | Prefix for output raster map/group names |
| `stac` | Custom STAC endpoint URL (Planetary Computer backend) |
| `strds` | Create/extend a Space-Time Raster Dataset (one per band) |
| `metadata` | Directory for per-map `description.json` metadata files |
| `-g` | Use Google Earth Engine instead of Planetary Computer |
| `-c` | SCL-based cloud masking (S2 only) |
| `-s` | Spectral Cloud Score Index masking (S2 only) |
| `-m` | i.sentinel.mask cloud masking (S2 only) |
| `-r` | True-color RGB composite after import (S2 only) |
| `-j` | Write per-band metadata JSON |
| `-l` | List scenes and exit |
| `-p` | Print region info and exit |

## Sentinel-1 examples

```sh
g.region n=47.73 s=47.68 e=-2.85 w=-2.93

# VV and VH backscatter, one month
r.in.sentinel collection=sentinel-1-rtc \
  start=2023-07-01 end=2023-07-31 \
  output=s1 strds=s1_ts

# VV only
r.in.sentinel collection=sentinel-1-rtc \
  bands=vv \
  start=2023-07-01 end=2023-07-31 \
  output=s1_vv

# Via GEE
r.in.sentinel collection=COPERNICUS/S1_GRD \
  bands=VV,VH \
  start=2023-07-01 end=2023-07-31 \
  output=s1_gee flags=g
```

## Sentinel-2 examples

```sh
# Surface reflectance with SCL cloud masking
r.in.sentinel collection=sentinel-2-l2a \
  bands=B02,B03,B04,B08,B8A,B11,B12,SCL \
  start=2023-07-01 end=2023-07-31 clouds=20 \
  output=s2 flags=c

# True-color RGB composite
r.in.sentinel collection=sentinel-2-l2a \
  start=2023-07-01 end=2023-07-31 clouds=20 \
  output=s2 flags=cr

# List available dates without downloading
r.in.sentinel collection=sentinel-2-l2a \
  start=2023-07-01 end=2023-07-31 output=dummy flags=l
```

## Requirements

```
pip install cubo rasterio rioxarray
```

For Google Earth Engine support:

```
pip install earthengine-api
earthengine authenticate
```

**PROJ ≥ 7.0 is required.** This module writes GeoTIFFs whose CRS is
resolved via `rasterio.crs.CRS.from_epsg()`, which needs the `proj.db`
authority database introduced in PROJ 6 and stabilized in PROJ 7.
PROJ 9.x, Rasterio ≥ 1.3, and GDAL ≥ 3.5 are recommended. Check with:

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

Downloads small real scenes over Plumergat (56400, France) via
Planetary Computer to confirm the download → slice → import → group
pipeline works end-to-end; skipped automatically if `cubo` isn't
installed, and needs a WGS84/latlong GRASS location plus live network
access otherwise.

## License

Public domain — see [LICENSE](LICENSE) (Unlicense).

## References

- Torres, R. et al. (2012). *GMES Sentinel-1 mission.* Remote Sensing
  of Environment 120:9–24.
  [doi:10.1016/j.rse.2011.05.028](https://doi.org/10.1016/j.rse.2011.05.028)
- Drusch, M. et al. (2012). *Sentinel-2: ESA's optical high-resolution
  mission for GMES operational services.* Remote Sensing of Environment
  120:25–36.
  [doi:10.1016/j.rse.2011.11.026](https://doi.org/10.1016/j.rse.2011.11.026)
- Montero, D. et al. (2023). *A standardized catalogue of spectral
  indices to advance the use of remote sensing in Earth system
  research.* Scientific Data.
- [cubo documentation](https://github.com/ESDS-Leipzig/cubo)
- [Microsoft Planetary Computer STAC](https://planetarycomputer.microsoft.com/api/stac/v1)
- [Sentinel-2 SCL classification](https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview)

## See also

- [r.in.landcover](https://github.com/YannChemin/r.in.landcover) —
  land cover classification importer (ESA WorldCover, MODIS, Dynamic
  World, …)
- [r.hydro.hbv](https://github.com/YannChemin/r.hydro.hbv) — the HBV
  hydrological model this ecosystem's importers feed
- [t.in.era5](https://github.com/YannChemin/t.in.era5) — ERA5(-Land)
  reanalysis importer
- [r.in.dem](https://github.com/YannChemin/r.in.dem) — Copernicus DEM
  importer
