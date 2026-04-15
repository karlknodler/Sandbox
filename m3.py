import pygame
import sys
from pygame.locals import *
import math
import importlib.util
from pathlib import Path
from near_api.providers import JsonProvider
import webbrowser
import threading
from flask import Flask
import requests
import numpy as np


    
provider = JsonProvider("https://rpc.testnet.near.org")
def check_nft(account_id):
    # Example of a view call using the corrected provider
    response = provider.view_call("your_contract.testnet", "nft_tokens_for_owner", {"account_id": account_id})
    return response
def load_obj(filename):
    vertices = []
    faces = []
    with open(filename, 'r') as file:
        for line in file:
            if line.startswith('v '):
                # Vertex
                parts = line.strip().split()[1:]
                vertices.append([float(part) for part in parts])
            elif line.startswith('f '):
                # Face
                parts = line.strip().split()[1:]
                face = [int(part.split('/')[0]) - 1 for part in parts]
                faces.append(face)
    return np.array(vertices), np.array(faces)
def draw():
    # Load the bird model
    bird_vertices, bird_faces = load_obj('path/to/bird_model.obj')
    
    # Rendering logic using bird_vertices and bird_faces
    # ... (rest of the draw function implementation goes here)
# -------------------------------------------------
# 1. CORE MATH & UTILITIES
# -------------------------------------------------
def world_to_camera_space(x, y, z, camera):
    # Translate
    tx, ty, tz = x - camera["pos"][0], y - camera["pos"][1], z - camera["pos"][2]
    # Yaw
    sy, cy = math.sin(-camera["yaw"]), math.cos(-camera["yaw"])
    tx, tz = (tx * cy - tz * sy, tx * sy + tz * cy)
    # Pitch
    sp, cp = math.sin(-camera["pitch"]), math.cos(-camera["pitch"])
    ty, tz = (ty * cp - tz * sp, ty * sp + tz * cp)
    return tx, ty, tz

def project_point(x, y, z, camera):
    vx, vy, vz = world_to_camera_space(x, y, z, camera)
    if vz < 0.1:
        return None
    f = 260 / vz
    return int(vx * f + 400), int(vy * f + 300)

def fogged_color(color, depth):
    if depth <= 280: return color
    fog_t = min(1.0, (depth - 280) / 670)
    # Fade to dark blue-ish black
    return tuple(int(c * (1 - fog_t) + 11 * fog_t) for c in color)
owned: False
hovered: False
def calculate_area(coords):
    # Shoelace Formula
    n = len(coords)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coords[i][0] * coords[j][1]
        area -= coords[j][0] * coords[i][1]
    return abs(area) / 2.0


# -------------------------------------------------
# 2. GEOSPATIAL LOADING
# -------------------------------------------------
def load_buildings(lat, lon):
    print(f"--- Fetching Real-World Data for {lat}, {lon} ---")
    sandbox_project = Path(__file__).resolve().parent / "sandbox project"
    if str(sandbox_project) not in sys.path:
        sys.path.append(str(sandbox_project))

    try:
        from geo.bounding_box import bounding_square
        from geo.overpass import fetch_buildings, overpass_to_geojson
    except ImportError:
        print("Error: 'sandbox project' modules not found. Falling back to cubes.")
    # This provides a single 50x50x50 cube as a fallback
        return [{
            "pos": [0, 0, 100],
            "verts": [
                (-25, 0, -25), (25, 0, -25), (25, -50, -25), (-25, -50, -25), # Base
                (-25, 0, 25),  (25, 0, 25),  (25, -50, 25),  (-25, -50, 25)   # Roof
            ],
            "edges": [
                (0,1), (1,2), (2,3), (3,0), # Bottom square
                (4,5), (5,6), (6,7), (7,4), # Top square
                (0,4), (1,5), (2,6), (3,7)  # Pillars
            ],
            "address": "Fallback Way",
            "price": 50000,
            "hovered": False,
            "owned": False
        }]

    square = bounding_square(lat, lon, km=1)
    data = overpass_to_geojson(fetch_buildings(square))
    
    m_per_lat = 111000
    m_per_lon = m_per_lat * math.cos(math.radians(lat))
    
    loaded = []
    for feature in data.get("features", []):
        geom = feature.get("geometry", {})
        g_type = geom.get("type")
        props = feature.get("properties", {})
        
        # Query building height from properties
        # Try multiple common OSM tags for height
        height_str = props.get("height") or props.get("building:height") or ""
        
        # Parse height value (handle formats like "25", "25m", "25 m", etc.)
        try:
            if height_str:
                # Remove common suffixes
                height_str = str(height_str).replace("m", "").replace("M", "").strip()
                h = float(height_str)
            else:
                # Default fallback based on building type
                building_type = props.get("building", "yes")
                if building_type == "skyscraper":
                    h = 100.0
                elif building_type == "residential":
                    h = 12.0
                elif building_type == "commercial":
                    h = 25.0
                else:
                    h = 18.0  # Default
        except (ValueError, TypeError):
            h = 18.0  # Fallback to default if parsing fails
        
        # 1. Properly handle Polygons vs MultiPolygons
        if g_type == "Polygon":
            # Coordinates is a list of rings; we take the exterior ring [0]
            all_polygons = [geom.get("coordinates", [[]])[0]]
        elif g_type == "MultiPolygon":
            # Coordinates is a list of Polygons; we take the exterior ring of each
            all_polygons = [p[0] for p in geom.get("coordinates", [])]
        else:
            continue # Skip Point, LineString, etc.
            
        for footprint_coords in all_polygons:
            if len(footprint_coords) < 3:
                continue
            
            # Convert GPS to Local Meters
            footprint = []
            for c in footprint_coords:
                lx = (c[0] - lon) * m_per_lon
                lz = (c[1] - lat) * m_per_lat
                footprint.append((lx, lz))
            area_m2 = calculate_area(footprint)
            price_rate = 237
            calculated_price = int(area_m2 * price_rate)
            
            # 2. Extrude logic using queried height
            verts = []
            for fx, fz in footprint: verts.append((fx, 0, fz))        # Base
            for fx, fz in footprint: verts.append((fx, -h, fz))       # Roof (negative for downward)
            
            edges = []
            n = len(footprint)
            for i in range(n):
                j = (i + 1) % n
                edges.append((i, j))          # Base loop
                edges.append((i + n, j + n))  # Roof loop
                edges.append((i, i + n))      # Vertical pillars

            # Calc Center
            cx = sum(p[0] for p in footprint) / n
            cz = sum(p[1] for p in footprint) / n
            
            loaded.append({
                "pos": [cx, 0, cz],
                "verts": [(v[0]-cx, v[1], v[2]-cz) for v in verts],
                "edges": edges,
                "address": props.get("addr:street", "Building"),
                "owner": None,
                "price": calculated_price,
                "area": area_m2,
                "height": h,  # Store the height for reference
                "owned": False,
                "hovered": False
            })
    return loaded
# Helper function for Point-in-Polygon (Ray Casting Algorithm)
def enemy_shoot(enemy, player, bullet_group):
    current_time = pygame.time.get_ticks()
    # Only shoot if player is within 400 pixels and cooldown has passed
    if abs(enemy.rect.x - player.rect.x) < 400:
        if current_time - enemy.last_shot > enemy.cooldown:
            direction = 1 if player.rect.x > enemy.rect.x else -1
            bullet = EnemyBullet(enemy.rect.centerx, enemy.rect.centery, direction)
            bullet_group.add(bullet)
            enemy.last_shot = current_time


class EnemyBullet(pygame.sprite.Sprite):
    def __init__(self, x, y, direction):
        super().__init__()
        self.image = pygame.Surface((10, 5))
        self.image.fill((255, 0, 0))  # Red bullet
        self.rect = self.image.get_rect(center=(x, y))
        self.speed = 7
        self.direction = direction # -1 for left, 1 for right

    def update(self):
        self.rect.x += self.speed * self.direction
        # Remove bullet if it goes off-screen
        if self.rect.right < 0 or self.rect.left > 800:
            self.kill()
def is_inside(x, y, poly):
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside
# --- BRIDGE SETUP ---
user_data = {"account_id": None}
app = Flask(__name__)

@app.route('/callback')
def callback():
    # This captures the account_id sent back from the wallet
    acc = requests.args.get('account_id')
    if acc:
        user_data["account_id"] = acc
        return f"Logged in as {acc}! You can close this tab and return to the game."
    return "Login failed."

def run_flask():
    # Use a port that matches your NEAR wallet redirect URI
    app.run(port=5000, debug=False, use_reloader=False)

def start_bridge():
    threading.Thread(target=run_flask, daemon=True).start()

def open_wallet_selector():
    # Replace with your actual NEAR login URL
    # Usually: https://testnet.mynearwallet.com/login/?success_url=http://127.0.0.1:5000/callback
    auth_url = "https://testnet.mynearwallet.com/login/?success_url=http://127.0.0.1:5000/callback"
    webbrowser.open(auth_url)
def painter_simple_ground(screen, camera, bird):
    tile_size = 200
    grid_range = 10 # 10 tiles in every direction
    
    depths_quads = []
    
    # Create a grid of many small tiles centered around the bird
    # This ensures the ground "follows" you and sorts correctly
    start_x = int(bird["pos"][0] / tile_size) - grid_range
    start_z = int(bird["pos"][2] / tile_size) - grid_range
    
    for x in range(start_x, start_x + grid_range * 2):
        for z in range(start_z, start_z + grid_range * 2):
            x_m = x * tile_size
            z_m = z * tile_size
            
            quad = [(x_m, 0, z_m), (x_m + tile_size, 0, z_m), 
                    (x_m + tile_size, 0, z_m + tile_size), (x_m, 0, z_m + tile_size)]
            
            # Calculate depth for sorting
            cam_depths = []
            for vx, vy, vz in quad:
                _, _, cz = world_to_camera_space(vx, vy, vz, camera)
                cam_depths.append(cz)
            
            avg_z = sum(cam_depths) / 4
            if avg_z > 0: # Only keep quads in front of the camera
                depths_quads.append((quad, avg_z, max(cam_depths)))

    # Sort and draw as usual...
    depths_quads.sort(key=lambda x: x[1], reverse=True)
    
    for (quad, avg_depth, max_depth), _ in zip(depths_quads, range(len(depths_quads))):
        # Use one or two alternating colors for a checkerboard effect
        color = (11, 11, 11) if (quad[0][0] + quad[0][2]) % (tile_size*2) == 0 else (200, 222, 200)
        
        projected = [project_point(v[0], v[1], v[2], camera) for v in quad]
        valid_points = [p for p in projected if p is not None]
        
        if len(valid_points) >= 3:
            shaded = fogged_color(color, avg_depth)
            pygame.draw.polygon(screen, shaded, valid_points)


# -------------------------------------------------
# 3. INITIALIZATION
# -------------------------------------------------
pygame.init()
screen = pygame.display.set_mode((800, 600))
clock = pygame.time.Clock()
# Initialize Font
pygame.font.init()
# Use a system font (None uses the default Pygame font)
font = pygame.font.SysFont("Arial", 24, bold=True)


start_bridge()

logged_in = False
account_id = "Not Connected"
# Player Stats
player_cash = 1000000  # Starting money

# --- COMMAND LINE PARSING ---
# Usage: python m2.py [lat] [lon]
try:
    start_lat = float(sys.argv[1]) if len(sys.argv) > 1 else 44.9778
    start_lon = float(sys.argv[2]) if len(sys.argv) > 2 else -93.2650
except ValueError:
    print("Invalid arguments. Using default: Minneapolis.")
    start_lat, start_lon = 44.9778, -93.2650

buildings = load_buildings(start_lat, start_lon)

camera = {"pos": [0, -150, -400], "yaw": 0.0, "pitch": 0.0}
bird = {"pos": [0, -100, 0]} # Start at center of new location

pygame.event.set_grab(True)
pygame.mouse.set_visible(False)

mouse_clicked = False

# -------------------------------------------------
# 4. MAIN LOOP
# -------------------------------------------------
# --- Inside your while True loop ---
while True:
    dt = clock.tick(30) / 1000.0
    keys = pygame.key.get_pressed()
    screen.fill((0,0,0))
   
    enemies = [Enemy(bird["pos"], position=(0, -100, 600))]
    ullets = [] # List to store active EnemyBullet objects
     # OR use the simple version:
    painter_simple_ground(screen, camera, bird)
    # 1. Get absolute mouse position (needed for clicking buildings)
    mx, my = pygame.mouse.get_pos()
    
    # 2. Reset click state every frame
    mouse_clicked = False 
    
    # 3. Get relative movement for camera (only if grabbed)
    dx, dy = pygame.mouse.get_rel()

# 4. THE ONLY EVENT LOOP YOU NEED
    for event in pygame.event.get():
        if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
            pygame.quit(); sys.exit()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                current_state = pygame.event.get_grab()
                pygame.event.set_grab(not current_state)
                pygame.mouse.set_visible(current_state) 
        
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Check UI first:
            if not logged_in and (50 <= mx <= 250 and 100 <= my <= 150):
                open_wallet_selector()
            else:
                # If we didn't click the button, allow the click to buy buildings
                mouse_clicked = True
    
        

    # --- After the loop, check for background login updates ---
    if user_data["account_id"] and not logged_in:
        account_id = user_data["account_id"]
        logged_in = True
        print(f"User connected: {account_id}")
    
    # 5. Only rotate camera if mouse is grabbed
    if pygame.event.get_grab():
        camera["yaw"] -= dx * 0.002
        camera["pitch"] = max(-1.2, min(1.2, camera["pitch"] - dy * 0.002))
    
    # Movement
    sy, cy = math.sin(camera["yaw"]), math.cos(camera["yaw"])
    move_speed = 300.0 * dt
    if keys[pygame.K_w]: bird["pos"][0] -= sy * move_speed; bird["pos"][2] += cy * move_speed
    if keys[pygame.K_s]: bird["pos"][0] += sy * move_speed; bird["pos"][2] -= cy * move_speed
    if keys[pygame.K_a]: bird["pos"][0] -= cy * move_speed; bird["pos"][2] -= sy * move_speed
    if keys[pygame.K_d]: bird["pos"][0] += cy * move_speed; bird["pos"][2] += sy * move_speed
    if keys[pygame.K_SPACE]: bird["pos"][1] -= move_speed
    if keys[pygame.K_LSHIFT]: bird["pos"][1] += move_speed
    

    # Follow cam (simplified)
    camera["pos"] = [bird["pos"][0] - sy*200, bird["pos"][1] - 50, bird["pos"][2] + cy*200]

# --- Update Enemies ---
for e in enemies:
    # update() returns True if the enemy's cooldown has reset and they are in range
    shoot_triggered = e.update(bird["pos"], dt) 
    
    if shoot_triggered:
        # Create a bullet directed from enemy to player
        direction = (pygame.Vector3(bird["pos"]) - e.pos).normalize()
        # Add a new bullet dictionary (or class instance) to our list
        bullets.append({
            "pos": pygame.Vector3(e.pos), 
            "vel": direction * 500, # 500 units per second speed
            "life": 3.0 # Bullet expires after 3 seconds
        })

# --- Update Bullets ---
for b in bullets[:]: # Use a slice copy [:] to allow removing items while looping
    b["pos"] += b["vel"] * dt
    b["life"] -= dt
    
    # Collision Check (Simple distance-based)
    if (b["pos"] - pygame.Vector3(bird["pos"])).length() < 20:
        print("PLAYER HIT!")
        player_cash -= 1000 # Penalty for being hit
        bullets.remove(b)
    elif b["life"] <= 0:
        bullets.remove(b)

# Draw Buildings
    for b in buildings:
        # 1. Distance check
        dist = math.sqrt((bird["pos"][0]-b["pos"][0])**2 + (bird["pos"][2]-b["pos"][2])**2)
        if dist > 1500: continue
        
        # 2. Project vertices
        proj = []
        base_proj = [] # We need this for the hover detection
        depths = []
        
        for i, (vx, vy, vz) in enumerate(b["verts"]):
            wx, wy, wz = vx + b["pos"][0], vy + b["pos"][1], vz + b["pos"][2]
            _, _, cam_z = world_to_camera_space(wx, wy, wz, camera)
            depths.append(cam_z)
            p = project_point(wx, wy, wz, camera)
            proj.append(p)
            
            # vy == 0 identifies the base vertices in your load_buildings logic
            if vy == 0:
                base_proj.append(p)
            
        # 3. Frustum Culling (Don't draw if behind camera)
        if not depths or min(depths) < 1: continue
        
        # 4. HOVER & CLICK LOGIC
        # We default to False, then check if mouse is inside the 2D footprint
        b["hovered"] = False
        if not pygame.event.get_grab() and len(base_proj) > 2:
            if is_inside(mx, my, base_proj):
                b["hovered"] = True
                if mouse_clicked:
                    if not b.get("owned", False):
                        if player_cash >= b["price"]:
                            player_cash -= b["price"]
                            b["owned"] = True
                            print(f"Purchased! Remaining: ${player_cash}")
                        else:
                            print("Not enough cash!")

        # 5. COLOR LOGIC
        if b.get("owned"):
            color = (50, 255, 50) # Green
        elif b["hovered"]:
            color = (255, 255, 0) # Yellow
        else:
            color = fogged_color((180, 180, 255), min(depths))

        # 6. DRAW THE LINES
        line_width = 2 if b["hovered"] else 1
        for start_idx, end_idx in b["edges"]:
            pygame.draw.line(screen, color, proj[start_idx], proj[end_idx], line_width)

        # --- Draw Enemies ---
    for e in enemies:
        e.draw(screen, camera, project_point)

    # --- Draw Bullets ---
    for b in bullets:
        p = project_point(b["pos"].x, b["pos"].y, b["pos"].z, camera)
        if p: # Only draw if the bullet is in front of the camera
            pygame.draw.circle(screen, (255, 255, 0), p, 4) # Yellow projectile
    # UI Rendering
    color = (0, 255, 0) if logged_in else (255, 0, 0)
    status_text = font.render(f"Wallet: {account_id}", True, color)
    screen.blit(status_text, (50, 50))

    if not logged_in:
        pygame.draw.rect(screen, (100, 100, 250), (50, 100, 200, 50))
        btn_text = font.render("Connect Wallet", True, (255, 255, 255))
        screen.blit(btn_text, (65, 110))
    # --- DRAW UI OVERLAY ---
    # 1. Create text surface: render(text, antialias, color)
    cash_text = f"CASH: ${int(player_cash):,}" # Adding commas for readability
    text_surface = font.render(cash_text, True, (255, 255, 255))
    
    # 2. Draw a dark backing box for readability
    bg_rect = pygame.Rect(10, 10, text_surface.get_width() + 20, 40)
    pygame.draw.rect(screen, (30, 30, 50), bg_rect)
    pygame.draw.rect(screen, (255, 255, 255), bg_rect, 2) # White border
    
    # 3. Put the text on top
    screen.blit(text_surface, (20, 15))


    pygame.display.flip()