from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController
import numpy as np
import pywavefront

from geojsonbldg import get_latest_combined_obj

app = Ursina()

# === CONFIG ===
DESIRED_SCENE_SIZE = 1000
GROUND_SCALE = DESIRED_SCENE_SIZE * 1.2
PLAYER_START_Y = 10  # keep spawn above ground while debugging floor collision issues
PERLIN_REPEAT = 0.1
WIREFRAME_COLOR = color.black

# === GROUND ===
ground = Entity(
    model='plane',
    scale=GROUND_SCALE,
    collider='box',
    texture='white_cube',
    texture_scale=(GROUND_SCALE, GROUND_SCALE),
    y=0
)

# === LOAD COMBINED OBJ ===
combined_obj = get_latest_combined_obj()
if combined_obj is None:
    print("No combined OBJ found in: assets/geo_buildings")
    exit()

# Load vertices and faces using pywavefront
scene = pywavefront.Wavefront(str(combined_obj), collect_faces=True)
verts = np.array(scene.vertices)
if verts.size == 0:
    print("No vertices found in OBJ:", combined_obj)
    exit()

# Compute bounding box
min_bounds = verts.min(axis=0)
max_bounds = verts.max(axis=0)
center_xz = Vec3((min_bounds[0] + max_bounds[0]) / 2, 0, (min_bounds[2] + max_bounds[2]) / 2)
min_y = min_bounds[1]

# Scale factor
combined_size = max_bounds - min_bounds
scale_factor = DESIRED_SCENE_SIZE / max(combined_size[0], combined_size[2])

# Shift & scale vertices
for i, v in enumerate(verts):
    verts[i] = [
        (v[0] - center_xz.x) * scale_factor,
        (v[1] - min_y) * scale_factor,
        (v[2] - center_xz.z) * scale_factor
    ]

# Create Mesh for Ursina
faces = []
for mesh in scene.mesh_list:
    for f in mesh.faces:
        faces.append([idx + 1 for idx in f])  # OBJ indices are 1-based

city_model = Mesh(vertices=[Vec3(*v) for v in verts], triangles=[tuple(f) for f in faces])

# === WRAP IN PARENT ENTITY ===
geo_parent = Entity()  # parent container for combined city

# Add city as child
city_entity = Entity(
    model=city_model,
    parent=geo_parent,
    texture='perlin_noise',
    texture_scale=(DESIRED_SCENE_SIZE * PERLIN_REPEAT, DESIRED_SCENE_SIZE * PERLIN_REPEAT),
    color=color.white
)

# Wireframe overlay
wire = Entity(model=city_model, parent=city_entity, color=WIREFRAME_COLOR)
wire.model.mode = 'lines'

# Combine into single mesh for performance and enable collider
geo_parent.combine()
geo_parent.collider = 'mesh'
geo_parent.static = True

print(f"Loaded combined city OBJ: {combined_obj.name}, {len(verts)} vertices")

# === PLAYER ===
player = FirstPersonController()
player.gravity = 0.1
player.cursor.visible = False
player.position = Vec3(0, PLAYER_START_Y, 0)

# === SKY ===
Sky()

app.run()