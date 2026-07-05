#!/usr/bin/env python3
# %Module
# % description: Downloads and imports Sentinel-2 imagery using the cubo library via Microsoft Planetary Computer or Google Earth Engine.
# % keyword: imagery
# % keyword: satellite
# % keyword: Sentinel
# % keyword: import
# % keyword: download
# % keyword: STAC
# % keyword: Planetary Computer
# % keyword: cloud
# %end

# %option
# % key: collection
# % type: string
# % required: no
# % multiple: no
# % answer: sentinel-2-l2a
# % description: Name of the Sentinel-2 collection in the STAC catalogue
# % guisection: Config
# %end

# %option
# % key: bands
# % type: string
# % required: no
# % multiple: yes
# % answer: B02,B03,B04,B08,B8A,B11,B12,SCL
# % description: Sentinel-2 bands to download
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
# % key: p
# % description: Print region info and exit
# %end

# %rules
# % exclusive: -g, stac
# % exclusive: -c, -s
# %end

import os
import sys
import tempfile

import grass.script as gs


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
        # Ensure float32; replace infinities with NaN
        arr = np.where(np.isfinite(arr), arr, np.nan).astype(np.float32)

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
            dtype="float32",
            crs=crs_obj,
            transform=transform,
            nodata=float("nan"),
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
    list_only = flags["l"]
    print_region = flags["p"]

    clouds = int(clouds_raw) if clouds_raw else None

    # GEE uses a different default collection name
    if use_gee and collection == "sentinel-2-l2a":
        gs.message(
            "Note: for GEE the common Sentinel-2 SR collection is "
            "'COPERNICUS/S2_SR_HARMONIZED'. "
            "Override with the 'collection' option if needed."
        )

    # --- Parse band list ---
    bands = [b.strip() for b in bands_raw.split(",") if b.strip()]

    # Ensure SCL is included when SCL cloud masking is requested
    if do_scl_mask and "SCL" not in bands:
        gs.message("Adding SCL band to download list for cloud masking.")
        bands.append("SCL")

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

    # --- Import each date/band ---
    imported_maps_total = 0
    groups_created = []

    for date_str in unique_dates:
        indices = [i for i, d in enumerate(date_strs) if d == date_str]

        # Mosaic overlapping tiles: mean of valid pixels across tiles
        if len(indices) == 1:
            da_day = da.isel(time=indices[0])  # dims: (band, y, x)
        else:
            gs.verbose(
                f"  {date_str}: mosaicking {len(indices)} overlapping tile(s)…"
            )
            da_day = da.isel(time=indices).mean(dim="time", skipna=True)

        band_maps = []

        for j, b in enumerate(da.coords["band"].values):
            band_name = str(b)
            map_name = f"{output_prefix}_{date_str}_{band_name}"

            gs.verbose(f"Importing {map_name} …")

            arr_2d = da_day.isel(band=j)  # dims: (y, x)

            try:
                import_band_to_grass(arr_2d, map_name, crs_str, transform)
                band_maps.append(map_name)
                imported_maps_total += 1
            except Exception as e:
                gs.warning(f"Failed to import {map_name}: {e}")

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

    gs.message(
        f"Done. Imported {imported_maps_total} raster map(s) "
        f"across {len(groups_created)} scene group(s)."
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
