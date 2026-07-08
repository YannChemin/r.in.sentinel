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

### Sentinel-1 SAR units

Sentinel-1 backscatter (`vv`, `vh`, `hh`, `hv`) is imported as **linear
power** (gamma0), matching what both Planetary Computer's
`sentinel-1-rtc` and GEE's `COPERNICUS/S1_GRD` return. Many downstream
tools expect **dB** instead (10 × log10 of linear power) - pass the
**d** flag to convert those bands at import time. The **angle**
(incidence angle, degrees) band, if requested, is left untouched since
it is not a power quantity.

```
r.in.sentinel collection=sentinel-1-rtc bands=vv,vh \
  start=2024-01-01 end=2024-07-01 output=s1 -d strds=s1
```

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

### Per-band metadata JSON

With the **-j** flag the module writes a `description.json` file for
each imported raster map to the standard GRASS location
`$MAPSET/cell_misc/<map_name>/description.json`. Alternatively, the
**metadata** option allows specifying a directory where the files are
saved (`<metadata_dir>/<map_name>/description.json`). The two options
are mutually exclusive.

Each JSON file records:

| Key | Description |
| --- | ----------- |
| `collection` | STAC collection name |
| `band` | Band identifier (e.g. `B04`) |
| `date` | Acquisition date (`YYYYMMDD`) |
| `start_date` / `end_date` | Query date range |
| `epsg` | EPSG code of the downloaded data |
| `resolution_m` | Spatial resolution in metres |
| `stac_endpoint` | STAC endpoint URL (null for GEE) |
| `gee` | `true` when downloaded from Google Earth Engine |
| `cloud_cover_max` | Maximum cloud cover filter applied |
| `scl_masked` | Whether SCL cloud masking was applied |
| `spectral_masked` | Whether spectral CSI masking was applied |
| `n_tiles_mosaicked` | Number of overlapping tiles merged |
| `central_lat` / `central_lon` | Region centre in WGS84 |

### Space-Time Raster Dataset (STRDS)

When the **strds** option is set, the module creates one STRDS per downloaded
band and registers all imported maps into it after the import loop. The STRDS
names follow the pattern `{strds}_{band}`, e.g. `s2_B04`, `s2_B08`, `s2_SCL`.

Temporal registration uses the acquisition timestamp already embedded in each
raster map by `r.timestamp` (format `DD Mon YYYY HH:MM:SS.ffffff`), so no
additional timestamp file is required. The `-i` flag of `t.register` reads
these stored timestamps automatically.

This makes the imported data immediately usable with TGRASS tools such as
`t.rast.series`, `t.rast.algebra`, and `t.rast.list`.

#### Cloud masking with i.sentinel.mask (`-m` flag)

The **-m** flag invokes *i.sentinel.mask* automatically for each acquired
date. The following bands are required by *i.sentinel.mask* and are added
to the download list automatically if not already requested:

| Role | Band |
| ---- | ---- |
| blue | B02 |
| green | B03 |
| red | B04 |
| nir | B08 |
| nir8a | B8A |
| swir11 | B11 |
| swir12 | B12 |

Solar zenith and azimuth angles needed by *i.sentinel.mask* are fetched
automatically from the STAC item properties (`s2:mean_solar_zenith`,
`s2:mean_solar_azimuth`) and written to `cell_misc/<map>/description.json`
for each imported band. *i.sentinel.mask* is then called with the `-s`
(rescale from DN to reflectance) and `-c` (cloud-only, no shadow) flags.

After masking, cloudy pixels are set to NULL in every imported band for
that date using `r.mapcalc`. The resulting cloud mask raster
(`{output}_{YYYYMMDD}_cloud_mask`) is kept, included in the *i.group*
group, given a timestamp via `r.timestamp`, and registered in the STRDS
if the **strds** option is set.

If solar angle metadata is unavailable for a given date (GEE backend,
or STAC item without sun-angle properties), masking is skipped for that
date with a warning.

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

### Download with i.sentinel.mask cloud masking (auto-adds required bands)

```sh
g.region n=47.73 s=47.68 e=-2.85 w=-2.93
r.in.sentinel collection=sentinel-2-l2a \
    bands=B02,B04,B08 \
    start=2023-07-01 end=2023-07-31 clouds=30 \
    output=s2 flags=m
# B03, B8A, B11, B12 are added automatically; cloud_mask maps are created
# per date and cloudy pixels are nulled in all bands.
```

### Import directly into a Space-Time Raster Dataset

```sh
g.region n=47.73 s=47.68 e=-2.85 w=-2.93
r.in.sentinel collection=sentinel-2-l2a \
    bands=B02,B03,B04,B08,B8A,B11,B12,SCL \
    start=2023-07-01 end=2023-07-31 clouds=20 \
    output=s2 strds=s2_ts flags=c
# Result: STRDS s2_ts_B02, s2_ts_B04, …, s2_ts_SCL
t.rast.list input=s2_ts_B04
```

### Download with metadata JSON written to the standard GRASS location

```sh
r.in.sentinel collection=sentinel-2-l2a bands=B02,B03,B04,B08,SCL \
    start=2023-07-01 end=2023-07-31 clouds=20 \
    output=s2_plumergat flags=j
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
[r.in.gdal](r.in.gdal.md), [g.region](g.region.md),
[i.sentinel.mask](i.sentinel.mask.md),
[t.create](t.create.md), [t.register](t.register.md),
[t.rast.series](t.rast.series.md), [t.rast.algebra](t.rast.algebra.md)*

## REFERENCES

- Montero, D. et al. (2023). *A standardized catalogue of spectral
  indices to advance the use of remote sensing in Earth system
  research.* Scientific Data.
- [cubo documentation](https://github.com/ESDS-Leipzig/cubo)
- [Microsoft Planetary Computer STAC](https://planetarycomputer.microsoft.com/api/stac/v1)
- [Sentinel-2 SCL classification](https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm-overview)

## AUTHOR

Yann Chemin
