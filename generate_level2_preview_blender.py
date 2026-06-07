import json
import math
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_city_grid as base


OUTPUT_DIR = SCRIPT_DIR / "output"
MACRO_JSON = OUTPUT_DIR / "city_grid_30x30_scheme2.json"
BUILDING_JSON = OUTPUT_DIR / "city_buildings_scheme2.json"
BLEND_OUTPUT = OUTPUT_DIR / "city_level2_scheme2.blend"


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def create_material(name, color):
    import bpy

    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    return material


def add_box(vertices, faces, center_x, center_y, base_z, width, depth, height):
    start = len(vertices)
    half_w = width / 2
    half_d = depth / 2
    bottom = base_z
    top = base_z + height

    vertices.extend(
        [
            (center_x - half_w, center_y - half_d, bottom),
            (center_x + half_w, center_y - half_d, bottom),
            (center_x + half_w, center_y + half_d, bottom),
            (center_x - half_w, center_y + half_d, bottom),
            (center_x - half_w, center_y - half_d, top),
            (center_x + half_w, center_y - half_d, top),
            (center_x + half_w, center_y + half_d, top),
            (center_x - half_w, center_y + half_d, top),
        ]
    )
    faces.extend(
        [
            (start, start + 1, start + 2, start + 3),
            (start + 4, start + 7, start + 6, start + 5),
            (start, start + 4, start + 5, start + 1),
            (start + 1, start + 5, start + 6, start + 2),
            (start + 2, start + 6, start + 7, start + 3),
            (start + 3, start + 7, start + 4, start),
        ]
    )


def create_building_mesh(buildings, is_tower=False):
    import bpy

    grid_offset = base.GRID_SIZE * base.CELL_SIZE / 2
    vertices = []
    faces = []

    for building in buildings:
        if bool(building["is_tower"]) != is_tower:
            continue

        add_box(
            vertices,
            faces,
            building["x"] * base.CELL_SIZE - grid_offset,
            building["y"] * base.CELL_SIZE - grid_offset,
            building["z"],
            building["width"],
            building["depth"],
            building["height"],
        )

    if not vertices:
        return None

    mesh_name = "level2_tower_mesh" if is_tower else "level2_building_mesh"
    object_name = "level2_towers" if is_tower else "level2_buildings"
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(object_name, mesh)
    bpy.context.collection.objects.link(obj)
    material = create_material("tower_warm_clay" if is_tower else "building_cool_clay", (0.80, 0.74, 0.68, 1.0) if is_tower else (0.82, 0.83, 0.86, 1.0))
    obj.data.materials.append(material)
    return obj


def add_tree(vertices, faces, x, y, z, scale):
    start = len(vertices)
    radius = scale * 0.75
    height = scale * 4.2
    base_z = z + 0.02
    top_z = z + height

    vertices.extend(
        [
            (x - radius, y - radius, base_z),
            (x + radius, y - radius, base_z),
            (x + radius, y + radius, base_z),
            (x - radius, y + radius, base_z),
            (x, y, top_z),
        ]
    )
    faces.extend(
        [
            (start, start + 1, start + 2, start + 3),
            (start, start + 4, start + 1),
            (start + 1, start + 4, start + 2),
            (start + 2, start + 4, start + 3),
            (start + 3, start + 4, start),
        ]
    )


def create_tree_mesh(trees):
    import bpy

    grid_offset = base.GRID_SIZE * base.CELL_SIZE / 2
    vertices = []
    faces = []

    for tree in trees:
        add_tree(
            vertices,
            faces,
            tree["x"] * base.CELL_SIZE - grid_offset,
            tree["y"] * base.CELL_SIZE - grid_offset,
            tree["z"],
            tree["scale"],
        )

    if not vertices:
        return None

    mesh = bpy.data.meshes.new("level2_tree_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    obj = bpy.data.objects.new("level2_trees", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(create_material("tree_clay_green", (0.56, 0.64, 0.52, 1.0)))
    return obj


def setup_preview_camera():
    import bpy

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 25))
    sun = bpy.context.object
    sun.name = "level2_sun"
    sun.data.energy = 2.4

    bpy.ops.object.camera_add(
        location=(12.5, -20.0, 13.0),
        rotation=(math.radians(58), 0, math.radians(36)),
    )
    camera = bpy.context.object
    bpy.context.scene.camera = camera


def main():
    try:
        import bpy
    except ImportError:
        print("This script must be run inside Blender.")
        return

    macro_grid = load_json(MACRO_JSON)
    city_data = load_json(BUILDING_JSON)

    base.create_blender_grid(macro_grid)
    create_building_mesh(city_data["buildings"], is_tower=False)
    create_building_mesh(city_data["buildings"], is_tower=True)
    create_tree_mesh(city_data["trees"])
    setup_preview_camera()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_OUTPUT))

    print(f"Level-2 Blender preview saved to: {BLEND_OUTPUT}")


if __name__ == "__main__":
    main()
