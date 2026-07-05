## DESCRIPTION

*r.in.sentinel* downloads Sentinel-2 imagery directly into the current
GRASS GIS mapset using the
[cubo](https://github.com/ESDS-Leipzig/cubo) Python library. Data is
fetched from **Microsoft Planetary Computer** (default, no credentials
required) or **Google Earth Engine** (**g** flag, credentials
required). Each acquisition date is imported as individual raster maps
and grouped with *i.group*.

The module reads the current computational region to determine the
centre coordinates (latitude/longitude) and the approximate download
extent. Both latlong and projected locations are supported.

### Output naming

Raster maps are named `{output}_{YYYYMMDD}_{band}`, e.g.
`sentinel2_20230615_B04`. One *i.group* group is created per
acquisition date: `{output}_{YYYYMMDD}`.

### Backends

**Microsoft Planetary Computer** (default)  
Collection `sentinel-2-l2a` provides Sentinel-2 Level-2A surface
reflectance. No account is required. The **stac** option allows
pointing to any STAC-compliant endpoint.

**Google Earth Engine**  
Use the **g** flag and set **collection** to the GEE asset ID, e.g.
`COPERNICUS/S2_SR_HARMONIZED`. GEE credentials must be configured
beforehand (`earthengine authenticate`).

## NOTES

### Cloud removal

Two cloud removal methods are available and are mutually exclusive.

#### SCL-based masking (`-c` flag)

Recommended for Sentinel-2 L2A data. Uses the Scene Classification
Layer (SCL band) to keep only pixels classified as:

| SCL value | Class |
| --------- | ----- |
| 4 | Vegetation |
| 5 | Not vegetated |
| 6 | Water |
| 11 | Snow / Ice |

All other classes (clouds, shadows, saturated pixels, no-data) are set
to NULL. The SCL band is automatically added to the download list when
**-c** is requested.

#### Spectral Cloud Score Index (`-s` flag)

Fallback method suitable for L1C data or when the SCL band is
unavailable. Computes a Cloud Score Index (CSI) from the Blue, Red, and
NIR bands:

```
CSI = (B02 + B04) / (2 × B08 + ε)
```

Pixels are flagged as cloud when `CSI > 0.35` **and** `B02 > 0.175`
(scaled reflectance). Requires **B02**, **B04**, and at least one of
**B08** or **B8A**.

### Region and resolution

The computational region centre is projected to WGS84 to serve as the
cubo cube centre. The download edge size is derived from the larger of
the NS or EW region extent. After download, each band slice is imported
with *r.import* using `extent=region`, which reprojects and clips to
the current computational region automatically.

### Listing scenes

With the **-l** flag the module prints one date per line to stdout and
exits without importing anything.

## REQUIREMENTS

The following Python packages must be installed:

```sh
pip install cubo rasterio rioxarray
```

For GEE support:

```sh
pip install earthengine-api
earthengine authenticate
```

### PROJ version warning

**PROJ ≥ 7.0 is required** (released March 2020).

This module writes UTM GeoTIFFs whose CRS is resolved from an EPSG code
via `rasterio.crs.CRS.from_epsg()`. That lookup hits the `proj.db`
SQLite authority database introduced in PROJ 6 and fully stabilised in
PROJ 7. With an older PROJ the database may be absent, incomplete, or
bundled inside GDAL under a different path, causing `r.import` to fail
with a CRS-related error or silently create an unnamed / unknown
projection in the temporary reprojection location, which then produces
incorrect or null output after `r.proj`.

Check your installed version with:

```sh
proj --version
python3 -c "import pyproj; print(pyproj.proj_version_str)"
```

PROJ 9.x (the current generation, available in most distributions since
2022) is recommended for best accuracy and datum-shift support.
Rasterio ≥ 1.3 and GDAL ≥ 3.5 are also recommended to ensure they are
linked against a PROJ 7+ library.

## EXAMPLES

### Download Sentinel-2 L2A for one month (Planetary Computer)

```sh
g.region n=47.73 s=47.68 e=-2.85 w=-2.93
r.in.sentinel collection=sentinel-2-l2a bands=B02,B03,B04,B08,B8A,B11,B12,SCL \
    start=2023-07-01 end=2023-07-31 clouds=20 output=s2_plumergat
```

### List available scenes without downloading

```sh
r.in.sentinel collection=sentinel-2-l2a start=2023-07-01 end=2023-07-31 \
    output=dummy flags=l
```

### Download with SCL cloud masking

```sh
r.in.sentinel collection=sentinel-2-l2a \
    bands=B02,B03,B04,B08,B8A,B11,B12,SCL \
    start=2023-08-01 end=2023-08-31 clouds=50 \
    output=s2_masked flags=c
```

### Download with spectral cloud index masking (L1C)

```sh
r.in.sentinel collection=sentinel-2-l1c \
    bands=B02,B04,B08 \
    start=2023-09-01 end=2023-09-30 \
    output=s2_l1c flags=s
```

### Use a custom STAC endpoint

```sh
r.in.sentinel collection=sentinel-2-l2a \
    stac=https://earth-search.aws.element84.com/v1 \
    bands=B04,B08 start=2023-06-01 end=2023-06-30 output=s2_aws
```

### Use Google Earth Engine backend

```sh
r.in.sentinel collection=COPERNICUS/S2_SR_HARMONIZED \
    bands=B2,B3,B4,B8 \
    start=2023-07-01 end=2023-07-31 \
    output=s2_gee flags=g
```

## SEE ALSO

*[i.group](i.group.md), [r.import](r.import.md),
[r.in.gdal](r.in.gdal.md), [g.region](g.region.md)*

## REFERENCES

- Montero, D. et al. (2023). *A standardized catalogue of spectral
  indices to advance the use of remote sensing in Earth system
  research.* Scientific Data.
- [cubo documentation](https://github.com/ESDS-Leipzig/cubo)
- [Microsoft Planetary Computer STAC](https://planetarycomputer.microsoft.com/api/stac/v1)
- [Sentinel-2 SCL classification](https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview)

## AUTHOR

Yann Chemin
