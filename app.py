"""
Flood Hapi
==========
A Flask web dashboard that takes a UK postcode, downloads EA Risk of Flooding
from Surface Water (RoFSW) data via the Defra DSP geospatial query API,
clips to a configurable radius buffer, and outputs separate shapefiles for
each depth band and risk band as individual 2m grid cells in EPSG:27700.

Requirements:
    pip install flask requests geopandas shapely fiona pyproj

Usage:
    python app.py
    Then open http://localhost:5000 in your browser.
"""

import os
import io
import json
import shutil
import zipfile
import tempfile
import logging
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, jsonify, send_file, Response
import requests
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon, GeometryCollection
from shapely.validation import make_valid
from shapely.prepared import prep
from shapely.ops import unary_union
from pyproj import Transformer
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = "flood-hapi-2025"

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("flood-hapi")

# Reusable HTTP session — keeps TCP/TLS connections alive across requests
_http = requests.Session()
_http.headers.update({"User-Agent": "FloodHapi/1.0"})

# EA Data Services Platform endpoints
EA_QUERY_API = "https://environment.data.gov.uk/backend/catalog/api/geospatial/query"
EA_WMS_URL = "https://environment.data.gov.uk/spatialdata/nafra2-risk-of-flooding-from-surface-water/wms"
POSTCODES_API = "https://api.postcodes.io/postcodes/"

# Coordinate reference systems
CRS_WGS84 = "EPSG:4326"
CRS_BNG = "EPSG:27700"  # British National Grid

# Buffer radius in metres
DEFAULT_RADIUS = 500

# Cache the BNG<->WGS84 transformer (thread-safe after creation)
_transformer_to_wgs84 = Transformer.from_crs(CRS_BNG, CRS_WGS84, always_xy=True)

# Defra DSP layer IDs for NaFRA2 RoFSW
EA_LAYER_IDS = {
    "rofsw":            "7a7d1570-dd33-4edc-9a19-fde1b9fcaadb",
    "rofsw_0_2m_depth": "8aa5d9cb-2a54-4480-b7d6-0aaef9efa576",
    "rofsw_0_3m_depth": "c36f87b8-100f-4162-bab1-7b3d0fb20c62",
    "rofsw_0_6m_depth": "212ee02f-9a47-4c55-a4e0-2c7c6e8d35d2",
    "rofsw_0_9m_depth": "5b3f81a3-f6c7-4637-8b1e-4cf5ef83259e",
    "rofsw_1_2m_depth": "52819ecb-130c-4a4d-a406-6f003af69988",
}

# RoFSW output layer definitions
ROFSW_LAYERS = {
    "risk_band_High": {
        "ea_layer": "rofsw",
        "filter_field": "risk_band",
        "filter_value": "High",
        "description": "High risk - >=3.3% (1 in 30) chance per year",
        "filename": "risk_band_High",
    },
    "risk_band_Medium": {
        "ea_layer": "rofsw",
        "filter_field": "risk_band",
        "filter_value": "Medium",
        "description": "Medium risk - <3.3% but >=1% (1 in 100) chance per year",
        "filename": "risk_band_Medium",
    },
    "risk_band_Low": {
        "ea_layer": "rofsw",
        "filter_field": "risk_band",
        "filter_value": "Low",
        "description": "Low risk - <1% but >=0.1% (1 in 1000) chance per year",
        "filename": "risk_band_Low",
    },
    "depth_0.2m": {
        "ea_layer": "rofsw_0_2m_depth",
        "filter_field": None,
        "filter_value": None,
        "description": "Flooding depth >= 0.2m",
        "filename": "depth_0_2m",
    },
    "depth_0.3m": {
        "ea_layer": "rofsw_0_3m_depth",
        "filter_field": None,
        "filter_value": None,
        "description": "Flooding depth >= 0.3m",
        "filename": "depth_0_3m",
    },
    "depth_0.6m": {
        "ea_layer": "rofsw_0_6m_depth",
        "filter_field": None,
        "filter_value": None,
        "description": "Flooding depth >= 0.6m",
        "filename": "depth_0_6m",
    },
    "depth_0.9m": {
        "ea_layer": "rofsw_0_9m_depth",
        "filter_field": None,
        "filter_value": None,
        "description": "Flooding depth >= 0.9m",
        "filename": "depth_0_9m",
    },
    "depth_1.2m": {
        "ea_layer": "rofsw_1_2m_depth",
        "filter_field": None,
        "filter_value": None,
        "description": "Flooding depth >= 1.2m",
        "filename": "depth_1_2m",
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def geocode_postcode(postcode: str) -> dict:
    """Geocode a UK postcode using postcodes.io."""
    clean = postcode.strip().upper().replace(" ", "")
    if len(clean) > 4:
        formatted = clean[:-3] + " " + clean[-3:]
    else:
        formatted = clean

    url = POSTCODES_API + formatted.replace(" ", "%20")
    log.info(f"Geocoding postcode: {formatted}")

    resp = _http.get(url, timeout=15)
    if resp.status_code == 404:
        raise ValueError(f"Postcode '{formatted}' not found. Please check and try again.")
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 200 or not data.get("result"):
        raise ValueError(f"Postcode '{formatted}' not found. Please check and try again.")

    r = data["result"]
    return {
        "postcode": r["postcode"],
        "lat": r["latitude"],
        "lng": r["longitude"],
        "easting": r["eastings"],
        "northing": r["northings"],
        "admin_district": r.get("admin_district", ""),
        "region": r.get("region", ""),
    }


def create_buffer_bbox(easting: float, northing: float, radius: float = DEFAULT_RADIUS) -> tuple[tuple, tuple]:
    """Create a bounding box in BNG and WGS84 around a point."""
    bbox_bng = (
        easting - radius,
        northing - radius,
        easting + radius,
        northing + radius,
    )
    min_lng, min_lat = _transformer_to_wgs84.transform(bbox_bng[0], bbox_bng[1])
    max_lng, max_lat = _transformer_to_wgs84.transform(bbox_bng[2], bbox_bng[3])
    bbox_wgs84 = (min_lng, min_lat, max_lng, max_lat)
    return bbox_bng, bbox_wgs84


def create_buffer_polygon(easting: float, northing: float, radius: float = DEFAULT_RADIUS) -> Polygon:
    """Create a circular buffer polygon in BNG."""
    return Point(easting, northing).buffer(radius)


def download_ea_layer(layer_name: str, bbox_wgs84: tuple, max_retries: int = 3) -> gpd.GeoDataFrame:
    """
    Download raw vector data from the Defra DSP geospatial query API.
    Retries up to max_retries times on failure (EA API can be flaky).
    """
    layer_id = EA_LAYER_IDS[layer_name]
    t0 = time.perf_counter()
    log.info(f"Downloading EA layer: {layer_name} ({layer_id})")

    min_lng, min_lat, max_lng, max_lat = bbox_wgs84
    query_polygon = {
        "type": "Polygon",
        "coordinates": [[
            [min_lng, min_lat],
            [min_lng, max_lat],
            [max_lng, max_lat],
            [max_lng, min_lat],
            [min_lng, min_lat],
        ]]
    }

    url = f"{EA_QUERY_API}?layer={layer_id}"
    for attempt in range(1, max_retries + 1):
        try:
            resp = _http.post(
                url,
                headers={
                    "Accept": "application/zipped-shapefile",
                    "Content-Type": "application/geo+json",
                },
                json=query_polygon,
                timeout=180,
            )
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt < max_retries:
                wait = attempt * 3
                log.warning(f"  -> {layer_name} attempt {attempt} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                log.error(f"  -> {layer_name} failed after {max_retries} attempts: {e}")
                raise
    dl_time = time.perf_counter() - t0

    if len(resp.content) < 100:
        log.warning(f"  -> Empty/tiny response for {layer_name} ({dl_time:.1f}s)")
        return gpd.GeoDataFrame()

    # Read shapefile from zip in memory — no disk I/O
    t1 = time.perf_counter()
    zip_buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(zip_buf) as zf:
        shp_names = [n for n in zf.namelist() if n.endswith(".shp")]
        if not shp_names:
            log.warning(f"  -> No .shp in download for {layer_name}")
            return gpd.GeoDataFrame()

        # Extract to temp dir (required for multi-file shapefile format)
        tmpdir = tempfile.mkdtemp()
        try:
            zf.extractall(tmpdir)
            gdf = gpd.read_file(os.path.join(tmpdir, shp_names[0]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if gdf.empty:
        return gdf

    # Explode MultiPolygons into individual 2m grid cells
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)

    # Ensure BNG
    if gdf.crs and gdf.crs != CRS_BNG:
        gdf = gdf.to_crs(CRS_BNG)

    parse_time = time.perf_counter() - t1
    log.info(f"  -> {layer_name}: {len(gdf)} cells (download {dl_time:.1f}s, parse {parse_time:.1f}s)")

    return gdf


def clip_to_buffer(gdf: gpd.GeoDataFrame, buffer_polygon, prepared_buffer=None) -> gpd.GeoDataFrame:
    """
    Clip a GeoDataFrame to the circular buffer polygon.
    Uses a prepared geometry for fast contains-check pre-filter, then only
    clips edge cells that partially intersect.
    """
    if gdf.empty:
        return gdf

    if prepared_buffer is None:
        prepared_buffer = prep(buffer_polygon)

    # Fast pre-filter: cells whose centroid is inside the buffer are fully contained
    # (2m grid cells are tiny relative to 250-1000m buffer, so centroid test is reliable)
    centroids = gdf.geometry.centroid
    inside_mask = centroids.apply(prepared_buffer.contains)

    # Cells fully inside — no clipping needed
    fully_inside = gdf[inside_mask]

    # Edge cells: intersect the buffer but centroid outside
    edge_candidates = gdf[~inside_mask]

    if edge_candidates.empty:
        return fully_inside.copy()

    # Only clip edge cells — much smaller set
    edge_intersects = edge_candidates[edge_candidates.geometry.apply(prepared_buffer.intersects)]

    if edge_intersects.empty:
        return fully_inside.copy()

    # Fix only invalid geometries in the edge set
    invalid_mask = ~edge_intersects.geometry.is_valid
    if invalid_mask.any():
        edge_intersects = edge_intersects.copy()
        edge_intersects.loc[invalid_mask, "geometry"] = edge_intersects.loc[invalid_mask, "geometry"].apply(make_valid)

    clipped_edges = gpd.clip(edge_intersects, buffer_polygon)

    if not clipped_edges.empty:
        # Extract polygon geometries from any GeometryCollections
        def extract_polygons(geom):
            if isinstance(geom, (Polygon, MultiPolygon)):
                return geom
            if isinstance(geom, GeometryCollection):
                polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
                if not polys:
                    return None
                if len(polys) == 1:
                    return polys[0]
                return unary_union(polys)
            return None

        clipped_edges = clipped_edges.copy()
        clipped_edges["geometry"] = clipped_edges["geometry"].apply(extract_polygons)
        clipped_edges = clipped_edges.dropna(subset=["geometry"])

    result = gpd.GeoDataFrame(pd.concat([fully_inside, clipped_edges], ignore_index=True), crs=gdf.crs)
    return result


def save_as_shapefile(gdf: gpd.GeoDataFrame, output_path: Path, layer_name: str) -> bool:
    """Save a GeoDataFrame as a shapefile."""
    if gdf.empty:
        log.info(f"  -> Skipping empty layer: {layer_name}")
        return False
    filepath = output_path / f"{layer_name}.shp"
    gdf.to_file(filepath, driver="ESRI Shapefile")
    return True


def create_zip(source_dir: Path, zip_path: Path) -> None:
    """Create a zip file from all files in the source directory."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in source_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(source_dir))


def _process_single_layer(layer_key: str, layer_config: dict, raw_gdf: gpd.GeoDataFrame,
                          buffer_poly, prepared_buffer, shp_dir: Path) -> tuple[str, dict]:
    """Process a single output layer: filter, clip, save."""
    try:
        if raw_gdf.empty:
            return layer_key, {
                "features": 0,
                "status": "no_data",
                "description": layer_config["description"],
            }

        gdf = raw_gdf

        # Apply attribute filter (for risk bands)
        if layer_config.get("filter_field"):
            field = layer_config["filter_field"]
            value = layer_config["filter_value"]
            if field in gdf.columns:
                gdf = gdf[gdf[field].str.upper() == value.upper()]

        if gdf.empty:
            return layer_key, {
                "features": 0,
                "status": "no_data",
                "description": layer_config["description"],
            }

        gdf_clipped = clip_to_buffer(gdf, buffer_poly, prepared_buffer)
        filename = layer_config["filename"]
        saved = save_as_shapefile(gdf_clipped, shp_dir, filename)

        return layer_key, {
            "features": len(gdf_clipped),
            "status": "ok" if saved else "empty_after_clip",
            "description": layer_config["description"],
            "filename": f"{filename}.shp" if saved else None,
        }

    except Exception as e:
        log.error(f"Error processing layer {layer_key}: {e}")
        return layer_key, {
            "features": 0,
            "status": "error",
            "error": str(e),
            "description": layer_config["description"],
        }


def process_postcode(postcode: str, radius: float = DEFAULT_RADIUS) -> dict:
    """
    Main processing function:
    1. Geocode postcode to BNG coordinates
    2. Create circular buffer and bounding box
    3. Download all 6 RoFSW layers from EA in parallel
    4. Clip rofsw once, then split by risk band (avoids 3x redundant clips)
    5. Clip + save depth layers sequentially (avoids GDAL threading crashes)
    6. Save search buffer polygon as shapefile
    7. Package everything into a zip with metadata
    """
    t_start = time.perf_counter()

    # Step 1: Geocode
    log.info(f"Processing postcode: {postcode}")
    location = geocode_postcode(postcode)
    log.info(f"  Location: {location['postcode']} -> E{location['easting']} N{location['northing']}")

    # Step 2: Create buffer
    bbox_bng, bbox_wgs84 = create_buffer_bbox(location["easting"], location["northing"], radius)
    buffer_poly = create_buffer_polygon(location["easting"], location["northing"], radius)
    prepared_buffer = prep(buffer_poly)
    log.info(f"  BNG bbox: {bbox_bng}")

    # Step 3: Set up output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_postcode = postcode.strip().upper().replace(" ", "")
    job_name = f"RoFSW_{clean_postcode}_{timestamp}"
    job_dir = OUTPUT_DIR / job_name
    shp_dir = job_dir / "shapefiles"
    shp_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "postcode": location["postcode"],
        "easting": location["easting"],
        "northing": location["northing"],
        "lat": location["lat"],
        "lng": location["lng"],
        "admin_district": location["admin_district"],
        "radius": radius,
        "bbox_bng": list(bbox_bng),
        "bbox_wgs84": list(bbox_wgs84),
        "layers": {},
        "job_name": job_name,
        "errors": [],
    }

    # Step 4: Download all unique EA layers in PARALLEL
    unique_layers = set(cfg["ea_layer"] for cfg in ROFSW_LAYERS.values())
    raw_data = {}

    t_dl = time.perf_counter()
    log.info(f"Downloading {len(unique_layers)} EA layers in parallel...")
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(download_ea_layer, name, bbox_wgs84): name
            for name in unique_layers
        }
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                raw_data[name] = future.result()
            except Exception as e:
                log.error(f"Download failed for {name}: {e}")
                raw_data[name] = gpd.GeoDataFrame()

    log.info(f"  All downloads complete in {time.perf_counter() - t_dl:.1f}s")

    # Step 5: Clip rofsw ONCE, then split by risk band (avoids 3x redundant clips)
    t_proc = time.perf_counter()
    rofsw_gdf = raw_data.get("rofsw", gpd.GeoDataFrame())
    rofsw_clipped = None
    if not rofsw_gdf.empty:
        rofsw_clipped = clip_to_buffer(rofsw_gdf, buffer_poly, prepared_buffer)
        log.info(f"  Clipped rofsw once: {len(rofsw_gdf)} -> {len(rofsw_clipped)} cells")

    # Process risk bands from the pre-clipped data (no re-clipping)
    for layer_key in ["risk_band_High", "risk_band_Medium", "risk_band_Low"]:
        cfg = ROFSW_LAYERS[layer_key]
        if rofsw_clipped is None or rofsw_clipped.empty:
            results["layers"][layer_key] = {
                "features": 0,
                "status": "no_data",
                "description": cfg["description"],
            }
            continue

        field = cfg["filter_field"]
        value = cfg["filter_value"]
        if field in rofsw_clipped.columns:
            filtered = rofsw_clipped[rofsw_clipped[field].str.upper() == value.upper()]
        else:
            filtered = rofsw_clipped

        filename = cfg["filename"]
        saved = save_as_shapefile(filtered, shp_dir, filename)
        results["layers"][layer_key] = {
            "features": len(filtered),
            "status": "ok" if saved else "empty_after_clip",
            "description": cfg["description"],
            "filename": f"{filename}.shp" if saved else None,
        }

    # Step 6: Clip + save depth layers sequentially
    # (parallel clipping can crash GDAL/GEOS on large datasets)
    depth_layers = {k: v for k, v in ROFSW_LAYERS.items() if k.startswith("depth_")}

    for lk, lc in depth_layers.items():
        layer_key, layer_result = _process_single_layer(
            lk, lc,
            raw_data.get(lc["ea_layer"], gpd.GeoDataFrame()),
            buffer_poly, prepared_buffer, shp_dir,
        )
        results["layers"][layer_key] = layer_result
        if layer_result.get("error"):
            results["errors"].append(f"{layer_key}: {layer_result['error']}")

    log.info(f"  All layers processed in {time.perf_counter() - t_proc:.1f}s")

    # Step 7: Save buffer polygon as shapefile
    buffer_gdf = gpd.GeoDataFrame(
        [{"postcode": location["postcode"], "radius_m": radius, "geometry": buffer_poly}],
        crs=CRS_BNG,
    )
    buffer_filename = f"search_buffer_{int(radius)}m"
    save_as_shapefile(buffer_gdf, shp_dir, buffer_filename)
    results["layers"]["search_buffer"] = {
        "features": 1,
        "status": "ok",
        "description": f"{int(radius)}m buffer around {location['postcode']}",
        "filename": f"{buffer_filename}.shp",
    }

    # Step 8: Save metadata
    metadata_path = job_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(
            {
                "postcode": location["postcode"],
                "easting": location["easting"],
                "northing": location["northing"],
                "lat": location["lat"],
                "lng": location["lng"],
                "radius_m": radius,
                "crs": CRS_BNG,
                "generated": datetime.now().isoformat(),
                "source": "Environment Agency - NaFRA2 Risk of Flooding from Surface Water (RoFSW)",
                "licence": "Open Government Licence v3.0",
                "attribution": "Contains Environment Agency information (c) Environment Agency and/or database right",
            },
            f,
            indent=2,
        )

    # Step 9: Create zip
    zip_path = OUTPUT_DIR / f"{job_name}.zip"
    create_zip(job_dir, zip_path)
    results["zip_file"] = str(zip_path)
    results["zip_filename"] = f"{job_name}.zip"

    shutil.rmtree(job_dir, ignore_errors=True)

    total_features = sum(
        layer.get("features", 0) for layer in results["layers"].values()
    )
    results["total_features"] = total_features

    total_time = time.perf_counter() - t_start
    log.info(f"Processing complete: {total_features} features in {total_time:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/process", methods=["POST"])
def api_process():
    """Process a postcode and return results."""
    data = request.get_json()
    postcode = data.get("postcode", "").strip()
    radius = float(data.get("radius", DEFAULT_RADIUS))

    if not postcode:
        return jsonify({"error": "Please enter a postcode"}), 400

    try:
        results = process_postcode(postcode, radius)
        return jsonify(results)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": "Cannot connect to EA Data Services. Check your internet connection."
        }), 503
    except Exception as e:
        log.exception("Processing error")
        return jsonify({"error": f"Processing failed: {str(e)}"}), 500


@app.route("/api/download/<filename>")
def api_download(filename):
    """Download a generated zip file."""
    filepath = OUTPUT_DIR / filename
    if not filepath.exists() or not filename.endswith(".zip"):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route("/api/wms-preview")
def wms_preview():
    """Proxy WMS GetMap request for map preview (avoids CORS)."""
    bbox = request.args.get("bbox", "")
    width = request.args.get("width", "800")
    height = request.args.get("height", "800")
    layer = request.args.get("layer", "rofsw")

    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "CRS": "EPSG:27700",
        "BBOX": bbox,
        "WIDTH": width,
        "HEIGHT": height,
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
        "STYLES": "",
    }

    try:
        resp = _http.get(EA_WMS_URL, params=params, timeout=30)
        resp.raise_for_status()
        return Response(resp.content, mimetype="image/png")
    except Exception as e:
        log.error(f"WMS proxy error: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Flood Hapi - Egyptian Flood Intelligence")
    print("  EA Surface Water Flood Risk Data Tool")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 60 + "\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
