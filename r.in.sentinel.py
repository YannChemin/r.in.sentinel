#!/usr/bin/env python3
# %Module
# % description: Downloads and imports Sentinel-1 SAR and Sentinel-2 optical imagery using the cubo library via Microsoft Planetary Computer or Google Earth Engine.
# % keyword: Import
# % keyword: imagery
# % keyword: satellite
# % keyword: Sentinel
# % keyword: Sentinel-1
# % keyword: Sentinel-2
# % keyword: SAR
# % keyword: radar
# % keyword: download
# % keyword: STAC
# % keyword: Planetary Computer
# % keyword: cloud
# % keyword: metadata
# %end

# %option
# % key: collection
# % type: string
# % required: no
# % multiple: no
# % answer: sentinel-2-l2a
# % description: STAC collection or GEE asset ID. Sentinel-2: sentinel-2-l2a (PC) / COPERNICUS/S2_SR_HARMONIZED (GEE). Sentinel-1: sentinel-1-rtc (PC) / COPERNICUS/S1_GRD (GEE).
# % guisection: Config
# %end

# %option
# % key: bands
# % type: string
# % required: no
# % multiple: yes
# % answer: B02,B03,B04,B08,B8A,B11,B12,SCL
# % description: Bands to download. Sentinel-2 default: B02,B03,B04,B08,B8A,B11,B12,SCL. Sentinel-1 default (auto-detected): vv,vh.
# % guisection: Config
# %end

# %option
# % key: start
# % type: string
# % required: yes
# % multiple: no
# % description: Start date (YYYY-MM-DD)
# % guisection: Filter
# %end

# %option
# % key: end
# % type: string
# % required: yes
# % multiple: no
# % description: End date (YYYY-MM-DD)
# % guisection: Filter
# %end

# %option
# % key: resolution
# % type: integer
# % required: no
# % multiple: no
# % answer: 10
# % description: Spatial resolution in meters
# % guisection: Config
# %end

# %option
# % key: clouds
# % type: integer
# % required: no
# % multiple: no
# % description: Maximum cloud cover percentage [0, 100]
# % guisection: Filter
# %end

# %option
# % key: output
# % type: string
# % required: no
# % multiple: no
# % answer: sentinel2
# % description: Prefix for output raster map names
# % guisection: Output
# %end

# %option
# % key: stac
# % type: string
# % required: no
# % multiple: no
# % answer: https://planetarycomputer.microsoft.com/api/stac/v1
# % description: STAC endpoint URL
# % guisection: Config
# %end

# %flag
# % key: g
# % description: Use Google Earth Engine instead of Planetary Computer
# %end

# %flag
# % key: c
# % description: Apply cloud masking using SCL band (Sentinel-2 L2A only)
# %end

# %flag
# % key: s
# % description: Apply spectral cloud index masking (uses B02, B04, B08/B8A; fallback for L1C or when SCL not available)
# %end

# %flag
# % key: l
# % description: List available dates/scenes and exit without downloading
# %end

# %flag
# % key: m
# % description: Apply cloud masking using i.sentinel.mask (requires B02,B03,B04,B08,B8A,B11,B12; auto-added)
# %end

# %flag
# % key: j
# % description: Write per-band metadata JSON to $MAPSET/cell_misc/<map>/description.json
# %end

# %flag
# % key: p
# % description: Print region info and exit
# %end

# %flag
# % key: r
# % description: Create true-color RGB composite with r.composite after import (auto-adds B02, B03, B04 if not listed)
# %end

# %option
# % key: metadata
# % type: string
# % required: no
# % multiple: no
# % description: Directory in which per-band metadata JSON files are saved (alternative to -j)
# % guisection: Output
# %end

# %option
# % key: strds
# % type: string
# % required: no
# % multiple: no
# % description: Prefix for Space-Time Raster Dataset names (one STRDS per band, e.g. strds=s2 → s2_B04, s2_B08 …)
# % guisection: Output
# %end

# %rules
# % exclusive: -g, stac
# % exclusive: -c, -s, -m
# % exclusive: -j, metadata
# %end

import json
import os
import sys
import tempfile

import grass.script as gs

# True-color composite: Sentinel-2 band names for red, green, blue
RGB_BANDS = ("B04", "B03", "B02")

# Sentinel-1 collection identifiers (Planetary Computer + GEE)
S1_COLLECTIONS = frozenset({
    "sentinel-1-rtc",
    "sentinel-1-grd",
    "COPERNICUS/S1_GRD",
})

# Default Sentinel-1 polarization bands (IW / EW dual-pol mode)
S1_DEFAULT_BANDS = ["vv", "vh"]

# S2 bands default string — used to auto-detect "user didn't touch bands" for S1
S2_DEFAULT_BANDS_STR = "B02,B03,B04,B08,B8A,B11,B12,SCL"

# Bands required by i.sentinel.mask (mapped to Sentinel-2 band names)
SENTINEL_MASK_BANDS = {
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "nir": "B08",
    "nir8a": "B8A",
    "swir11": "B11",
    "swir12": "B12",
}

# Official Sentinel-2 L2A Scene Classification Layer (SCL) legend
# (ESA/Sen2Cor). Unlike r.in.landcover's several land-cover products,
# there's exactly one SCL scheme, so it's applied automatically to any
# imported SCL band rather than gated behind a flag.
SCL_COLOR_RULES = """\
0 0:0:0
1 255:0:0
2 47:47:47
3 100:50:0
4 0:160:0
5 255:255:0
6 0:0:255
7 128:128:128
8 192:192:192
9 255:255:255
10 100:200:255
11 255:150:255
nv 0:0:0
"""

SCL_CATEGORY_RULES = """\
0|No data
1|Saturated or defective
2|Dark area pixels
3|Cloud shadows
4|Vegetation
5|Not vegetated
6|Water
7|Unclassified
8|Cloud medium probability
9|Cloud high probability
10|Thin cirrus
11|Snow or ice
"""


def apply_scl_style(map_name):
    """Applies the official SCL color table and class labels."""
    gs.write_command(
        "r.colors", map=map_name, rules="-", stdin=SCL_COLOR_RULES, quiet=True
    )
    gs.write_command(
        "r.category", map=map_name, separator="pipe", rules="-",
        stdin=SCL_CATEGORY_RULES, quiet=True,
    )


def fetch_stac_sun_angles(stac_url, collection, lat, lon, start, end, clouds=None):
    """Return per-date mean solar zenith and azimuth from a STAC metadata search.

    Does not download any imagery — reads item properties only.

    Returns
    -------
    dict
        {date_str: (mean_solar_zenith, mean_solar_azimuth)} for each date
        that has the required properties.  Dates without sun-angle metadata
        are silently omitted.
    """
    try:
        import pystac_client
    except ImportError:
        gs.warning(
            "pystac_client not available; sun angles cannot be fetched from STAC. "
            "i.sentinel.mask will be skipped."
        )
        return {}

    try:
        import planetary_computer as pc
        sign = pc.sign_inplace
    except ImportError:
        sign = None

    try:
        client = pystac_client.Client.open(
            stac_url,
            modifier=sign,
        )
        search_kwargs = dict(
            collections=[collection],
            datetime=f"{start}/{end}",
            intersects={"type": "Point", "coordinates": [lon, lat]},
        )
        if clouds is not None:
            search_kwargs["query"] = {"eo:cloud_cover": {"lt": clouds}}
        search = client.search(**search_kwargs)
        items = list(search.items())
    except Exception as e:
        gs.warning(f"STAC sun-angle search failed: {e}")
        return {}

    sun_angles = {}
    for item in items:
        date_str = item.datetime.strftime("%Y%m%d") if item.datetime else None
        if date_str is None or date_str in sun_angles:
            continue
        props = item.properties
        zenith = props.get("s2:mean_solar_zenith") or props.get(
            "view:sun_elevation"
        )
        azimuth = props.get("s2:mean_solar_azimuth") or props.get(
            "view:sun_azimuth"
        )
        if zenith is not None and azimuth is not None:
            sun_angles[date_str] = (float(zenith), float(azimuth))

    return sun_angles


def get_region_center_latlon():
    """Compute the center lat/lon and approximate edge size (in meters) of the
    current GRASS computational region.

    Returns
    -------
    tuple
        (lat_center, lon_center, edge_size_m)
    """
    # Check if the current location is geographic (lat/lon)
    proj_info = gs.parse_command("g.proj", flags="p", format="shell")
    is_latlong = proj_info.get("proj") in ("ll", "longlat")

    if is_latlong:
        region = gs.parse_command("g.region", flags="p", format="shell")
        n = float(region["n"])
        s = float(region["s"])
        e = float(region["e"])
        w = float(region["w"])
        lat_center = (n + s) / 2.0
        lon_center = (e + w) / 2.0
        deg_ns = abs(n - s)
        deg_ew = abs(e - w)
        edge_size_m = max(deg_ns, deg_ew) * 111320.0
    else:
        # Projected: -pb adds ll_clat/ll_clon (WGS84 centre) and projected extents
        region = gs.parse_command("g.region", flags="pb", format="shell")
        lat_center = float(region["ll_clat"])
        lon_center = float(region["ll_clon"])
        rows = int(region["rows"])
        cols = int(region["cols"])
        nsres = float(region["nsres"])
        ewres = float(region["ewres"])
        edge_size_m = max(rows * nsres, cols * ewres)

    return lat_center, lon_center, edge_size_m


def download_cube(
    lat,
    lon,
    collection,
    start,
    end,
    bands,
    edge_size_m,
    resolution,
    use_gee,
    stac_url,
    clouds=None,
):
    """Download a data cube using the cubo library.

    Parameters
    ----------
    lat : float
        Center latitude.
    lon : float
        Center longitude.
    collection : str
        STAC collection name.
    start : str
        Start date (YYYY-MM-DD).
    end : str
        End date (YYYY-MM-DD).
    bands : list of str
        Band names to download.
    edge_size_m : float
        Approximate edge size of the requested cube in meters.
    resolution : float
        Spatial resolution in meters.
    use_gee : bool
        Use Google Earth Engine backend.
    stac_url : str
        STAC endpoint URL.
    clouds : int or None
        Maximum cloud cover percentage filter.

    Returns
    -------
    xarray.DataArray
        The downloaded data cube.
    """
    try:
        import cubo
    except ImportError:
        gs.fatal(
            "The 'cubo' Python library is not installed. "
            "Install it with: pip install cubo"
        )

    # Convert edge size from meters to pixels
    edge_size = int(round(edge_size_m / resolution))
    if edge_size < 2:
        edge_size = 2
    if edge_size % 2 != 0:
        edge_size += 1

    gs.verbose(
        f"Requesting cube: center=({lat:.4f}, {lon:.4f}), "
        f"edge_size={edge_size}px, resolution={resolution}m"
    )

    kwargs = {}
    if clouds is not None:
        kwargs["query"] = {"eo:cloud_cover": {"lt": clouds}}

    if use_gee:
        da = cubo.create(
            lat=lat,
            lon=lon,
            collection=collection,
            start_date=start,
            end_date=end,
            bands=bands,
            edge_size=edge_size,
            units="px",
            resolution=float(resolution),
            gee=True,
            **kwargs,
        )
    else:
        da = cubo.create(
            lat=lat,
            lon=lon,
            collection=collection,
            start_date=start,
            end_date=end,
            bands=bands,
            edge_size=edge_size,
            units="px",
            resolution=float(resolution),
            stac=stac_url,
            gee=False,
            **kwargs,
        )

    # Realize dask arrays
    gs.verbose("Computing data cube (downloading data)…")
    da = da.compute()
    return da


def apply_scl_cloud_mask(da):
    """Apply cloud masking using the SCL (Scene Classification Layer) band.

    Keeps pixels classified as:
      4 = Vegetation
      5 = Not Vegetated
      6 = Water
      11 = Snow / Ice

    Parameters
    ----------
    da : xarray.DataArray
        Data cube with a 'band' dimension containing 'SCL'.

    Returns
    -------
    xarray.DataArray
        Masked data cube (cloudy pixels set to NaN).
    """
    band_values = da.coords["band"].values
    if "SCL" not in band_values:
        gs.warning(
            "SCL band not found in the data cube; cloud masking skipped."
        )
        return da

    scl = da.sel(band="SCL").round()  # mosaic mean may give fractional SCL
    clear_mask = (scl == 4) | (scl == 5) | (scl == 6) | (scl == 11)
    da_masked = da.where(clear_mask)
    return da_masked


def apply_spectral_cloud_mask(da, threshold=0.35):
    """Apply spectral cloud index masking.

    Uses a Blue/NIR brightness ratio to detect bright clouds.
    Requires B02, B04, and either B08 or B8A.

    Parameters
    ----------
    da : xarray.DataArray
        Data cube with a 'band' dimension.
    threshold : float
        Cloud Score Index threshold above which pixels are flagged as cloud.

    Returns
    -------
    xarray.DataArray
        Masked data cube (cloud pixels set to NaN).
    """
    import numpy as np

    band_values = list(da.coords["band"].values)

    if "B02" not in band_values or "B04" not in band_values:
        gs.warning(
            "B02 and/or B04 not available; spectral cloud masking skipped."
        )
        return da

    nir_band = None
    if "B08" in band_values:
        nir_band = "B08"
    elif "B8A" in band_values:
        nir_band = "B8A"
    else:
        gs.warning(
            "Neither B08 nor B8A available; spectral cloud masking skipped."
        )
        return da

    b02 = da.sel(band="B02").astype(float) / 10000.0
    b04 = da.sel(band="B04").astype(float) / 10000.0
    b08 = da.sel(band=nir_band).astype(float) / 10000.0

    # Cloud Score Index: high when blue/red are high and NIR is low (cloud-like)
    csi = (b02 + b04) / (2.0 * b08 + 1e-10)
    blue_bright = b02 > 0.175
    is_cloud = (csi > threshold) & blue_bright
    clear_mask = ~is_cloud

    da_masked = da.where(clear_mask)
    return da_masked


def import_band_to_grass(band_array_2d, map_name, crs_str, transform):
    """Write a 2-D band array to a temp GeoTIFF and import it into GRASS GIS.

    Parameters
    ----------
    band_array_2d : xarray.DataArray or numpy.ndarray
        2-D array with shape (rows, cols) = (y, x).
    map_name : str
        Output GRASS raster map name.
    crs_str : str
        CRS string (e.g. 'EPSG:32630').
    transform : affine.Affine
        Affine geotransform for the GeoTIFF.
    """
    import numpy as np
    import rasterio
    from rasterio.crs import CRS

    tmp_path = gs.tempfile(create=False) + ".tif"

    try:
        arr = (
            band_array_2d.values
            if hasattr(band_array_2d, "values")
            else band_array_2d
        )
        # cubo/rioxarray return float64 regardless of the source
        # asset's own dtype -- confirmed empirically: Sentinel-2's DN
        # reflectance bands and the SCL classification band (both
        # genuinely integer -- SCL is a discrete class code, DN is a
        # scaled integer reflectance) come back as float64. Checking
        # whether the actual finite values are integer-valued (rather
        # than assuming float means "continuous") writes these as a
        # proper CELL (integer) raster, matching how GRASS's own
        # i.sentinel.import stores Sentinel-2 bands, and is what makes
        # r.category/r.colors on the SCL band meaningful at all
        # (r.category errors on a genuinely floating-point map).
        finite_mask = np.isfinite(arr)
        is_integer_valued = finite_mask.any() and bool(
            np.all(np.mod(arr[finite_mask], 1) == 0)
            and np.all(np.abs(arr[finite_mask]) < 65535)
        )
        if is_integer_valued:
            arr = np.where(finite_mask, arr, 0).astype(np.uint16)
            nodata_val = 0
            dtype_str = "uint16"
        else:
            arr = np.where(finite_mask, arr, np.nan).astype(np.float32)
            nodata_val = float("nan")
            dtype_str = "float32"

        # CRS: resolve EPSG to full WKT at write time via rasterio/GDAL.
        # GRASS reads the embedded WKT through r.import — EPSG never reaches GRASS.
        epsg_int = int(float(crs_str.replace("EPSG:", "")))
        crs_obj = CRS.from_epsg(epsg_int)

        height, width = arr.shape
        with rasterio.open(
            tmp_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype=dtype_str,
            crs=crs_obj,
            transform=transform,
            nodata=nodata_val,
        ) as dst:
            dst.write(arr, 1)

        # Use r.import which handles reprojection and clips to current region
        gs.run_command(
            "r.import",
            input=tmp_path,
            output=map_name,
            extent="region",
            overwrite=True,
            quiet=True,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def sentinel2_semantic_label(band_name):
    """Return the GRASS semantic label for a Sentinel-2 band name.

    E.g. 'B02' -> 'S2_2', 'B8A' -> 'S2_8A', 'SCL' -> 'S2_SCL'.
    Returns None for unrecognised names.
    """
    b = band_name.upper()
    if b == "SCL":
        return "S2_SCL"
    if b.startswith("B"):
        suffix = b[1:].lstrip("0") or "0"
        return f"S2_{suffix}"
    return None


def sentinel1_semantic_label(band_name):
    """Return the GRASS semantic label for a Sentinel-1 band name.

    E.g. 'vv' -> 'S1_VV', 'vh' -> 'S1_VH', 'angle' -> 'S1_angle'.
    Returns None for unrecognised names.
    """
    mapping = {
        "vv": "S1_VV",
        "vh": "S1_VH",
        "hh": "S1_HH",
        "hv": "S1_HV",
        "angle": "S1_angle",
        "VV": "S1_VV",
        "VH": "S1_VH",
        "HH": "S1_HH",
        "HV": "S1_HV",
    }
    return mapping.get(band_name)


def write_band_metadata(map_name, metadata_dict, metadata_dir=None):
    """Write per-band metadata as description.json.

    Follows the convention of i.sentinel.import: one JSON file per raster map
    written to $MAPSET/cell_misc/<map_name>/description.json when metadata_dir
    is None, or to <metadata_dir>/<map_name>/description.json otherwise.
    """
    if metadata_dir is None:
        env = gs.gisenv()
        cell_misc = os.path.join(
            env["GISDBASE"], env["LOCATION_NAME"], env["MAPSET"], "cell_misc"
        )
        json_path = os.path.join(cell_misc, map_name, "description.json")
    else:
        json_path = os.path.join(metadata_dir, map_name, "description.json")

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w") as fh:
        json.dump(metadata_dict, fh, indent=2)


def main():
    """Main function."""
    try:
        import numpy as np
        import pandas as pd
        from rasterio.transform import Affine
    except ImportError as e:
        gs.fatal(
            f"Required Python library not found: {e}. "
            "Install numpy, pandas, and rasterio."
        )

    # --- Parse options and flags ---
    collection = options["collection"]
    bands_raw = options["bands"]
    start = options["start"]
    end = options["end"]
    resolution = int(options["resolution"])
    clouds_raw = options["clouds"]
    output_prefix = options["output"]
    stac_url = options["stac"]

    use_gee = flags["g"]
    do_scl_mask = flags["c"]
    do_spectral_mask = flags["s"]
    do_sentinel_mask = flags["m"]
    do_rgb = flags["r"]
    list_only = flags["l"]
    print_region = flags["p"]
    write_json = flags["j"]
    metadata_dir = options["metadata"] if options["metadata"] else None
    # -m always writes description.json so i.sentinel.mask can read sun angles
    do_metadata = write_json or do_sentinel_mask or (metadata_dir is not None)
    strds_prefix = options["strds"] if options["strds"] else None

    clouds = int(clouds_raw) if clouds_raw else None

    # --- Parse band list ---
    bands = [b.strip() for b in bands_raw.split(",") if b.strip()]

    # --- Detect Sentinel-1 vs Sentinel-2 ---
    is_s1 = (
        collection in S1_COLLECTIONS
        or collection.lower().startswith("sentinel-1")
    )

    if is_s1:
        # Auto-swap S2 default bands → S1 defaults when user didn't change them
        bands_csv = ",".join(bands)
        if bands_csv == S2_DEFAULT_BANDS_STR:
            gs.message(
                "Sentinel-1 collection detected; "
                f"switching default bands to: {', '.join(S1_DEFAULT_BANDS)}"
            )
            bands = list(S1_DEFAULT_BANDS)
        # Suppress S2-only processing flags with informative warnings
        if do_scl_mask:
            gs.warning("SCL cloud masking (-c) is not applicable to Sentinel-1 SAR; ignored.")
            do_scl_mask = False
        if do_spectral_mask:
            gs.warning("Spectral cloud masking (-s) is not applicable to Sentinel-1 SAR; ignored.")
            do_spectral_mask = False
        if do_sentinel_mask:
            gs.warning("i.sentinel.mask (-m) is not applicable to Sentinel-1 SAR; ignored.")
            do_sentinel_mask = False
        if do_rgb:
            gs.warning("RGB composite (-r) is not applicable to Sentinel-1 SAR; ignored.")
            do_rgb = False
        if clouds is not None:
            gs.warning(
                "Cloud cover filter has no effect for Sentinel-1 SAR "
                "(SAR is cloud-independent); ignored."
            )
            clouds = None

    # --- GEE collection hints ---
    if use_gee and not is_s1 and collection == "sentinel-2-l2a":
        gs.message(
            "Note: for GEE the common Sentinel-2 SR collection is "
            "'COPERNICUS/S2_SR_HARMONIZED'. "
            "Override with the 'collection' option if needed."
        )
    if use_gee and is_s1 and collection == "sentinel-1-rtc":
        gs.message(
            "Note: for GEE the Sentinel-1 collection is "
            "'COPERNICUS/S1_GRD'. "
            "Override with the 'collection' option if needed."
        )

    # Ensure SCL is included when SCL cloud masking is requested
    if do_scl_mask and "SCL" not in bands:
        gs.message("Adding SCL band to download list for cloud masking.")
        bands.append("SCL")

    # Ensure B02/B03/B04 are present when RGB composite is requested
    if do_rgb:
        added_rgb = [b for b in RGB_BANDS if b not in bands]
        if added_rgb:
            gs.message(f"Adding bands required for RGB composite: {', '.join(added_rgb)}")
            bands.extend(added_rgb)

    # Ensure all i.sentinel.mask bands are present when -m is requested
    if do_sentinel_mask:
        added = []
        for s2_band in SENTINEL_MASK_BANDS.values():
            if s2_band not in bands:
                bands.append(s2_band)
                added.append(s2_band)
        if added:
            gs.message(
                f"Adding bands required by i.sentinel.mask: {', '.join(added)}"
            )

    # --- Get region centre and size ---
    gs.message("Determining region centre and extent…")
    try:
        lat, lon, edge_size_m = get_region_center_latlon()
    except Exception as e:
        gs.fatal(f"Failed to determine region parameters: {e}")

    gs.message(
        f"Region centre: lat={lat:.4f}, lon={lon:.4f}, "
        f"approximate edge={edge_size_m:.0f} m"
    )

    if print_region:
        gs.message(
            f"lat={lat}, lon={lon}, edge_size_m={edge_size_m}, "
            f"resolution={resolution}"
        )
        return 0

    # --- Download ---
    gs.message(
        f"Downloading {collection} data from "
        f"{'GEE' if use_gee else stac_url} …"
    )
    gs.message(f"  Bands  : {', '.join(bands)}")
    gs.message(f"  Period : {start} → {end}")
    if clouds is not None:
        gs.message(f"  Max cloud cover: {clouds}%")

    try:
        da = download_cube(
            lat=lat,
            lon=lon,
            collection=collection,
            start=start,
            end=end,
            bands=bands,
            edge_size_m=edge_size_m,
            resolution=resolution,
            use_gee=use_gee,
            stac_url=stac_url,
            clouds=clouds,
        )
    except Exception as e:
        gs.fatal(f"Failed to download data cube: {e}")

    # Check for empty results
    if da.coords["time"].size == 0:
        gs.message("No scenes found for the given parameters. Exiting.")
        return 0

    n_scenes = da.coords["time"].size
    gs.message(f"Downloaded {n_scenes} scene(s).")

    # --- List-only mode ---
    if list_only:
        unique_dates_list = list(
            dict.fromkeys(
                pd.DatetimeIndex(da.coords["time"].values).strftime("%Y-%m-%d")
            )
        )
        gs.message("Available dates:")
        for d in unique_dates_list:
            print(d)
        return 0

    # --- Cloud masking ---
    if do_scl_mask:
        gs.message("Applying SCL-based cloud masking…")
        da = apply_scl_cloud_mask(da)

    if do_spectral_mask:
        gs.message("Applying spectral cloud index masking…")
        da = apply_spectral_cloud_mask(da)

    # --- CRS and transform ---
    epsg = da.attrs.get("epsg", 4326)
    crs_str = f"EPSG:{epsg}"
    gs.verbose(f"Data CRS: {crs_str}")

    # Ensure the computational region has a resolution compatible with the data.
    # r.import delegates to r.proj, which needs a non-trivial region resolution
    # to produce the correct pixel count in the output raster.
    proj_info = gs.parse_command("g.proj", flags="p", format="shell")
    if proj_info.get("proj") in ("ll", "longlat"):
        res_deg = resolution / 111320.0
        gs.run_command("g.region", nsres=res_deg, ewres=res_deg)
    # For projected locations the user's region resolution is already in metres.

    x = da.coords["x"].values
    y = da.coords["y"].values
    x_res = float(x[1] - x[0])
    y_res = float(y[1] - y[0])
    transform = Affine(
        x_res, 0, float(x[0]) - x_res / 2.0,
        0, y_res, float(y[0]) - y_res / 2.0,
    )

    # --- Group time indices by calendar date (mosaic overlapping tiles) ---
    import numpy as np

    times_pd = pd.DatetimeIndex(da.coords["time"].values)
    date_strs = times_pd.strftime("%Y%m%d")
    # preserve acquisition order, deduplicate
    unique_dates = list(dict.fromkeys(date_strs))

    gs.message(f"Unique acquisition dates: {', '.join(unique_dates)}")

    # --- Fetch sun angles from STAC for i.sentinel.mask ---
    sun_angles = {}
    if do_sentinel_mask and not use_gee:
        gs.message("Fetching solar angles from STAC metadata…")
        sun_angles = fetch_stac_sun_angles(
            stac_url, collection, lat, lon, start, end, clouds
        )
        if not sun_angles:
            gs.warning(
                "No solar angles found in STAC metadata; "
                "i.sentinel.mask will be skipped for all dates."
            )

    # --- Import each date/band ---
    imported_maps_total = 0
    groups_created = []
    # Track imported maps per band for STRDS registration: {band_name: [map_name, ...]}
    band_map_registry = {str(b): [] for b in da.coords["band"].values}

    for date_str in unique_dates:
        indices = [i for i, d in enumerate(date_strs) if d == date_str]

        # Use the timestamp of the first tile for r.timestamp
        acq_time = times_pd[indices[0]]
        timestamp_str = acq_time.strftime("%d %b %Y %H:%M:%S.%f")

        # Mosaic overlapping tiles by priority overlay (first tile's
        # valid pixels win; later tiles only fill in gaps the earlier
        # ones left as nodata), not a pixel-wise mean: the SCL band is
        # categorical (class codes, e.g. 4=Vegetation, 6=Water), and
        # averaging two class codes produces a class that doesn't
        # exist (mean of 4 and 6 is 5="Not vegetated", a real but
        # meaningless answer purely by coincidence of the numbering).
        if len(indices) == 1:
            da_day = da.isel(time=indices[0])  # dims: (band, y, x)
        else:
            gs.verbose(
                f"  {date_str}: mosaicking {len(indices)} overlapping tile(s)…"
            )
            da_day = da.isel(time=indices[0])
            for i in indices[1:]:
                da_day = da_day.combine_first(da.isel(time=i))

        band_maps = []

        for j, b in enumerate(da.coords["band"].values):
            band_name = str(b)
            map_name = f"{output_prefix}_{date_str}_{band_name}"

            gs.verbose(f"Importing {map_name} …")

            arr_2d = da_day.isel(band=j)  # dims: (y, x)

            try:
                import_band_to_grass(arr_2d, map_name, crs_str, transform)
                band_maps.append(map_name)
                band_map_registry[band_name].append(map_name)
                imported_maps_total += 1

                if band_name == "SCL":
                    apply_scl_style(map_name)
                elif is_s1:
                    gs.run_command("r.colors", map=map_name, color="grey", quiet=True)

                # Set acquisition timestamp on the raster map
                gs.run_command(
                    "r.timestamp", map=map_name, date=timestamp_str, quiet=True
                )

                # Set source and history metadata; add semantic label when known
                support_args = {
                    "map": map_name,
                    "source1": "GEE" if use_gee else stac_url,
                    "source2": collection,
                    "history": (
                        f"band={band_name} date={date_str} "
                        f"epsg={epsg} resolution={resolution}m "
                        f"n_tiles={len(indices)}"
                    ),
                }
                sem_label = (
                    sentinel1_semantic_label(band_name)
                    if is_s1
                    else sentinel2_semantic_label(band_name)
                )
                if sem_label:
                    support_args["semantic_label"] = sem_label
                gs.run_command("r.support", quiet=True, **support_args)

                if do_metadata:
                    meta = {
                        "collection": collection,
                        "band": band_name,
                        "date": date_str,
                        "start_date": start,
                        "end_date": end,
                        "epsg": int(epsg),
                        "resolution_m": resolution,
                        "stac_endpoint": None if use_gee else stac_url,
                        "gee": use_gee,
                        "cloud_cover_max": clouds,
                        "scl_masked": do_scl_mask,
                        "spectral_masked": do_spectral_mask,
                        "sentinel_masked": do_sentinel_mask,
                        "n_tiles_mosaicked": len(indices),
                        "central_lat": lat,
                        "central_lon": lon,
                    }
                    # Add sun angles so i.sentinel.mask can read them via metadata=default
                    if date_str in sun_angles:
                        zenith, azimuth = sun_angles[date_str]
                        meta["MEAN_SUN_ZENITH_ANGLE"] = zenith
                        meta["MEAN_SUN_AZIMUTH_ANGLE"] = azimuth
                    write_band_metadata(map_name, meta, metadata_dir)
            except Exception as e:
                gs.warning(f"Failed to import {map_name}: {e}")

        # --- i.sentinel.mask cloud masking ---
        if do_sentinel_mask and band_maps:
            # Check all 7 required bands were actually imported for this date
            mask_band_maps = {
                role: f"{output_prefix}_{date_str}_{s2b}"
                for role, s2b in SENTINEL_MASK_BANDS.items()
            }
            missing = [
                role
                for role, m in mask_band_maps.items()
                if m not in band_maps
            ]
            if missing:
                gs.warning(
                    f"{date_str}: skipping i.sentinel.mask — "
                    f"missing band(s): {', '.join(missing)}"
                )
            elif date_str not in sun_angles:
                gs.warning(
                    f"{date_str}: skipping i.sentinel.mask — "
                    "no solar angles available for this date"
                )
            else:
                cloud_raster = f"{output_prefix}_{date_str}_cloud_mask"
                try:
                    gs.run_command(
                        "i.sentinel.mask",
                        flags="sc",  # -s rescale DN→reflectance, -c cloud-only
                        scale_fac=10000,
                        cloud_raster=cloud_raster,
                        overwrite=True,
                        quiet=True,
                        **mask_band_maps,
                    )
                    gs.verbose(f"  {date_str}: cloud mask created → {cloud_raster}")

                    # Null out cloudy pixels in all imported bands
                    nulled = 0
                    for bmap in band_maps:
                        gs.mapcalc(
                            f"{bmap} = if(isnull({cloud_raster}), {bmap}, null())",
                            overwrite=True,
                            quiet=True,
                        )
                        nulled += 1
                    gs.message(
                        f"{date_str}: i.sentinel.mask applied to {nulled} band(s)."
                    )

                    # Include cloud mask raster in the date group
                    band_maps.append(cloud_raster)
                    band_map_registry.setdefault("cloud_mask", []).append(
                        cloud_raster
                    )
                    imported_maps_total += 1

                    # Set timestamp on the cloud mask map too
                    gs.run_command(
                        "r.timestamp",
                        map=cloud_raster,
                        date=timestamp_str,
                        quiet=True,
                    )
                except Exception as e:
                    gs.warning(
                        f"{date_str}: i.sentinel.mask failed: {e}"
                    )

        if band_maps:
            group_name = f"{output_prefix}_{date_str}"
            try:
                gs.run_command(
                    "i.group",
                    group=group_name,
                    subgroup=group_name,
                    input=",".join(band_maps),
                    quiet=True,
                )
                groups_created.append(group_name)
                gs.message(
                    f"Created group '{group_name}' with {len(band_maps)} band(s)."
                )
            except Exception as e:
                gs.warning(f"Failed to create group '{group_name}': {e}")

        # --- RGB true-color composite ---
        if do_rgb and band_maps:
            r_map = f"{output_prefix}_{date_str}_B04"
            g_map = f"{output_prefix}_{date_str}_B03"
            b_map = f"{output_prefix}_{date_str}_B02"
            if all(m in band_maps for m in (r_map, g_map, b_map)):
                rgb_name = f"{output_prefix}_{date_str}_RGB"
                try:
                    gs.run_command(
                        "r.composite",
                        red=r_map, green=g_map, blue=b_map,
                        output=rgb_name,
                        overwrite=True, quiet=True,
                    )
                    gs.message(f"  {date_str}: RGB composite → {rgb_name}")
                    band_map_registry.setdefault("RGB", []).append(rgb_name)
                    imported_maps_total += 1
                    gs.run_command(
                        "r.timestamp", map=rgb_name, date=timestamp_str, quiet=True
                    )
                    gs.run_command(
                        "r.support", map=rgb_name,
                        source1="GEE" if use_gee else stac_url,
                        source2=collection,
                        history=f"r.composite B04/B03/B02 date={date_str}",
                        quiet=True,
                    )
                except Exception as e:
                    gs.warning(f"{date_str}: RGB composite failed: {e}")
            else:
                gs.warning(
                    f"{date_str}: skipping RGB composite — "
                    "one or more of B02/B03/B04 not imported"
                )

    gs.message(
        f"Done. Imported {imported_maps_total} raster map(s) "
        f"across {len(groups_created)} scene group(s)."
    )

    # --- STRDS registration ---
    if strds_prefix and imported_maps_total > 0:
        gs.message("Creating Space-Time Raster Datasets…")
        try:
            import grass.temporal as tgis
            tgis.init()
        except Exception as e:
            gs.warning(f"Failed to initialise temporal framework: {e}")
        sensor_name = "Sentinel-1" if is_s1 else "Sentinel-2"
        strds_created = []
        for band_name, map_list in band_map_registry.items():
            if not map_list:
                continue
            strds_name = f"{strds_prefix}_{band_name}"
            try:
                gs.run_command(
                    "t.create",
                    type="strds",
                    temporaltype="absolute",
                    output=strds_name,
                    title=f"{sensor_name} {collection} — band {band_name}",
                    description=(
                        f"Imported by r.in.sentinel from {collection}, "
                        f"{start} to {end}, band {band_name}"
                    ),
                    overwrite=True,
                    quiet=True,
                )
                # reads r.timestamp stored on each map automatically (no flag needed)
                gs.run_command(
                    "t.register",
                    type="raster",
                    input=strds_name,
                    maps=",".join(map_list),
                    overwrite=True,
                    quiet=True,
                )
                strds_created.append(strds_name)
                gs.message(
                    f"  STRDS '{strds_name}': {len(map_list)} map(s) registered."
                )
            except Exception as e:
                gs.warning(f"Failed to create/register STRDS '{strds_name}': {e}")

        if strds_created:
            gs.message(
                f"Created {len(strds_created)} STRDS: {', '.join(strds_created)}"
            )
            gs.message(
                "Tip: apply cloud masking per scene with i.sentinel.mask, "
                "then re-register the masked maps."
            )

    return 0


if __name__ == "__main__":
    options, flags = gs.parser()

    # Dependency check
    try:
        import cubo  # noqa: F401
    except ImportError:
        gs.fatal(
            "The 'cubo' Python library is required but not installed. "
            "Install it with: pip install cubo"
        )

    sys.exit(main())
