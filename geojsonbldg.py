import math
import sys
from pathlib import Path
from datetime import datetime
import geohash2

def ensure_ccw(points):
    """Ensure polygon is counter-clockwise (XZ plane)."""
    area = 0.0
    for i in range(len(points)):
        x1, z1 = points[i]
        x2, z2 = points[(i + 1) % len(points)]
        area += (x2 - x1) * (z2 + z1)
    if area > 0:  # clockwise
        return list(reversed(points))
    return points


def triangulate_polygon(points):
    """
    Basic ear clipping triangulation.
    Assumes simple polygon (no holes, no self-intersections).
    Returns list of index triplets.
    """
    def area(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])

    def is_point_in_triangle(p, a, b, c):
        b1 = area(p, a, b) < 0.0
        b2 = area(p, b, c) < 0.0
        b3 = area(p, c, a) < 0.0
        return (b1 == b2) and (b2 == b3)

    indices = list(range(len(points)))
    triangles = []

    while len(indices) > 2:
        ear_found = False
        for i in range(len(indices)):
            prev_i = indices[i - 1]
            curr_i = indices[i]
            next_i = indices[(i + 1) % len(indices)]

            a = points[prev_i]
            b = points[curr_i]
            c = points[next_i]

            if area(a, b, c) <= 0:
                continue

            ear = True
            for other in indices:
                if other in (prev_i, curr_i, next_i):
                    continue
                if is_point_in_triangle(points[other], a, b, c):
                    ear = False
                    break

            if ear:
                triangles.append((prev_i, curr_i, next_i))
                del indices[i]
                ear_found = True
                break

        if not ear_found:
            break  # polygon may be degenerate

    return triangles

def _building_height_meters(props):
    if "height" in props:
        try:
            return float(props["height"])
        except:
            pass

    if "building:levels" in props:
        try:
            return float(props["building:levels"]) * 3.0
        except:
            pass

    return 10.0  # fallback default
    
def extrude_footprint(points_xz, height):
    """
    Extrudes 2D polygon (XZ) into 3D solid.
    Returns:
        vertices: [(x,y,z), ...]
        triangles: [(a,b,c), ...]
    """

    # Remove duplicate closing point
    if len(points_xz) > 2 and points_xz[0] == points_xz[-1]:
        points_xz = points_xz[:-1]

    if len(points_xz) < 3:
        return [], []

    points_xz = ensure_ccw(points_xz)
    n = len(points_xz)

    vertices = []
    triangles = []

    # Bottom vertices
    for x, z in points_xz:
        vertices.append((x, 0.0, z))

    # Top vertices
    for x, z in points_xz:
        vertices.append((x, height, z))

    # --- Roof ---
    roof_tris = triangulate_polygon(points_xz)
    for a, b, c in roof_tris:
        triangles.append((a + n, b + n, c + n))

    # --- Floor (reverse winding) ---
    for a, b, c in roof_tris:
        triangles.append((c, b, a))

    # --- Walls ---
    for i in range(n):
        next_i = (i + 1) % n

        bottom_i = i
        bottom_next = next_i
        top_i = i + n
        top_next = next_i + n

        triangles.append((bottom_i, bottom_next, top_next))
        triangles.append((bottom_i, top_next, top_i))

    return vertices, triangles

# -------------------------------------------------
# OSM FETCH
# -------------------------------------------------

def fetch_osm_buildings(lat, lon, km):
    from geo.bounding_box import bounding_square
    from geo.overpass import fetch_buildings, overpass_to_geojson

    square = bounding_square(lat, lon, km=km)
    geojson = overpass_to_geojson(fetch_buildings(square))
    return geojson


# -------------------------------------------------
# GEOJSON → EXTRUDED BUILDINGS
# -------------------------------------------------

def geojson_to_extruded_mesh(lat, lon, geojson):
    meters_per_lat = 111_320
    meters_per_lon = meters_per_lat * math.cos(math.radians(lat))

    all_vertices = []
    all_triangles = []
    vertex_offset = 0

    for feature in geojson.get("features", []):
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

        height = _building_height_meters(feature.get("properties", {}))

        verts, tris = extrude_footprint(footprint, height)

        # Add to global mesh
        all_vertices.extend(verts)

        for a, b, c in tris:
            all_triangles.append((
                a + vertex_offset,
                b + vertex_offset,
                c + vertex_offset
            ))

        vertex_offset += len(verts)

    return all_vertices, all_triangles


# -------------------------------------------------
# EXPORT
# -------------------------------------------------

def save_combined_obj(vertices, triangles, lat, lon, base_dir="assets/geo_buildings"):
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    geoh = geohash2.encode(lat, lon, precision=7)

    run_folder = base_path / f"{run_ts}_{geoh}"
    run_folder.mkdir(parents=True, exist_ok=True)

    combined_file = run_folder / "combined.obj"

    with open(combined_file, "w") as f:
        # Write vertices
        for x, y, z in vertices:
            f.write(f"v {x} {y} {z}\n")

        # OBJ is 1-indexed
        for a, b, c in triangles:
            f.write(f"f {a+1} {b+1} {c+1}\n")

    print(f"Saved city mesh to: {combined_file}")
    return combined_file


# -------------------------------------------------
# PUBLIC API
# -------------------------------------------------

def generate_city(lat, lon, km=1):
    print("Fetching OSM buildings...")
    geojson = fetch_osm_buildings(lat, lon, km)

    print("Extruding buildings...")
    vertices, triangles = geojson_to_extruded_mesh(lat, lon, geojson)

    if not vertices:
        print("No buildings found.")
        return None

    print("Saving combined OBJ...")
    return save_combined_obj(vertices, triangles, lat, lon)


def get_latest_combined_obj(base_dir="assets/geo_buildings"):
    base_path = Path(base_dir)

    if not base_path.exists():
        raise FileNotFoundError("Geo buildings directory does not exist.")

    run_folders = [p for p in base_path.iterdir() if p.is_dir()]
    if not run_folders:
        raise FileNotFoundError("No run folders found.")

    latest_folder = sorted(run_folders)[-1]
    combined_file = latest_folder / "combined.obj"

    if not combined_file.exists():
        raise FileNotFoundError(f"No combined.obj in {latest_folder}")

    return combined_file


# -------------------------------------------------
# CLI ENTRY
# -------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python geojson_city_builder.py <lat> <lon> [km]")
        sys.exit(1)

    lat = float(sys.argv[1])
    lon = float(sys.argv[2])
    km = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print(f"Generating city at lat={lat}, lon={lon}, radius={km}km")
    generate_city(lat, lon, km)
