import math
import sys
from pathlib import Path
from datetime import datetime
import geohash2  # pip install geohash2

from geojsonbuildingextrusion import (
    _building_height_meters,
    _extrude_footprint,
    export_building_pywavefront,
)


def get_latest_combined_obj(base_dir="assets/geo_buildings"):
    base_path = Path(base_dir)
    if not base_path.exists():
        return None

    run_folders = sorted(path for path in base_path.iterdir() if path.is_dir())
    if not run_folders:
        return None

    combined_obj = run_folders[-1] / "combined.obj"
    return combined_obj if combined_obj.exists() else None

def load_extruded_geojson_buildings(lat, lon, km=1):
    """
    Loads extruded buildings for a given GPS coordinate.
    Returns a list of dicts with 'verts' and 'edges'.
    """

    sandbox_project = Path(__file__).resolve().parent / "sandbox project"
    if str(sandbox_project) not in sys.path:
        sys.path.append(str(sandbox_project))

    try:
        from geo.bounding_box import bounding_square
        from geo.overpass import fetch_buildings, overpass_to_geojson
    except Exception as e:
        print("Import error:", e)
        return []

    try:
        square = bounding_square(lat, lon, km=km)
        footprints_geojson = overpass_to_geojson(fetch_buildings(square))
    except Exception as e:
        print("Overpass error:", e)
        return []

    meters_per_lat = 111_320
    meters_per_lon = meters_per_lat * math.cos(math.radians(lat))

    buildings_from_geojson = []

    for feature in footprints_geojson.get("features", []):
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "Polygon":
            continue

        rings = geometry.get("coordinates", [])
        if not rings:
            continue

        footprint = []
        for coord in rings[0]:
            if len(coord) < 2:
                continue
            point_lon, point_lat = coord[0], coord[1]
            x = (point_lon - lon) * meters_per_lon
            z = (point_lat - lat) * meters_per_lat
            footprint.append((x, z))

        if len(footprint) < 3:
            continue

        top_y = -_building_height_meters(feature.get("properties", {}))
        verts, edges = _extrude_footprint(footprint, top_y)
        if not verts:
            continue

        buildings_from_geojson.append({
            "verts": verts,
            "edges": edges,
        })

    return buildings_from_geojson


def generate_and_save_buildings(lat, lon, km=1, base_dir="assets/geo_buildings"):
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    buildings = load_extruded_geojson_buildings(lat, lon, km)
    if not buildings:
        print("No buildings loaded.")
        return

    run_ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    geoh = geohash2.encode(lat, lon, precision=7)

    # Create unique folder for this run
    run_folder = base_path / f"{run_ts}_{geoh}"
    run_folder.mkdir(parents=True, exist_ok=True)

    combined_vertices = []
    combined_faces = []
    vertex_offset = 0

    for i, building in enumerate(buildings, start=1):
        verts = [(x, -y, z) for x, y, z in building["verts"]]
        faces = building["edges"]  # assuming these are proper triangle faces

        # Save individual building
        file_path = run_folder / f"building_{i}.obj"
        export_building_pywavefront(verts, faces, file_path)

        # Add to combined mesh
        combined_vertices.extend(verts)
        for f in faces:
            combined_faces.append([idx + vertex_offset + 1 for idx in f])
        vertex_offset += len(verts)

    # Save combined mesh
    combined_file = run_folder / "combined.obj"
    with open(combined_file, "w") as f:
        for v in combined_vertices:
            f.write(f"v {v[0]} {v[1]} {v[2]}\n")
        for face in combined_faces:
            f.write(f"f {' '.join(map(str, face))}\n")

    print(f"Saved run to {run_folder}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python geojsonbldg.py <latitude> <longitude> [km]")
        sys.exit(1)

    lat = float(sys.argv[1])
    lon = float(sys.argv[2])
    km = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print(f"Generating sandbox at lat={lat}, lon={lon}, size={km}km")
    generate_and_save_buildings(lat, lon, km)
    print("Generation complete.")
