"""Starter Blender city generator.

This module covers the early PRD changes: load and validate city JSON data,
clear the Blender scene, and generate simplified city geometry.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any


DEFAULT_CITY_DATA_PATH = Path(__file__).with_name("city_data.json")
DEFAULT_TERRAIN_DATA_PATH = Path("output/city_grid_30x30_scheme2.json")
ROOF_HEIGHT_RATIO = 0.35
FLOOR_HEIGHT = 3.0
WINDOW_WIDTH = 0.35
WINDOW_HEIGHT = 0.55
WINDOW_SPACING = 1.2
WINDOW_LIGHT_PROBABILITY = 0.0
TOWER_WINDOW_LIGHT_PROBABILITY = 0.0
TOWER_WINDOW_SCALE = 0.75
TOWER_WINDOW_SPACING_MULTIPLIER = 1.8
WINDOW_FACADE_OFFSET = 0.02
TREE_TRUNK_RADIUS = 0.12
TREE_TRUNK_HEIGHT = 1.2
TREE_CROWN_RADIUS = 0.65
TREE_CROWN_HEIGHT = 2.6
TREE_RANDOM_SCALE = 0.3
TREE_SEGMENTS = 16
FOUNDATION_HEIGHT_RATIO = 0.08
FOUNDATION_MAX_HEIGHT = 0.04
FOUNDATION_MARGIN_RATIO = 0.08
FOUNDATION_MAX_MARGIN = 0.02
CAMERA_ORTHO_MARGIN = 1.35
CAMERA_DISTANCE_MULTIPLIER = 1.6
CAMERA_MIN_ORTHO_SCALE = 12.0
CAMERA_DEFAULT_CENTER = (0.0, 0.0, 0.0)
CAMERA_DEFAULT_SIZE = (12.0, 12.0, 8.0)
SUN_LIGHT_ENERGY = 2.2
AREA_LIGHT_ENERGY = 450.0
AREA_LIGHT_SIZE = 14.0
RENDER_RESOLUTION_X = 1600
RENDER_RESOLUTION_Y = 1000
RANDOM_SEED = 42
TERRAIN_STATE_COLORS = {
    0: (0.45, 0.56, 0.40, 1.0),
    1: (0.73, 0.71, 0.62, 1.0),
    2: (0.68, 0.70, 0.74, 1.0),
    3: (0.55, 0.58, 0.65, 1.0),
    4: (0.74, 0.60, 0.34, 1.0),
    5: (0.84, 0.80, 0.66, 1.0),
}

REQUIRED_BUILDING_FIELDS = {
    "id",
    "x",
    "y",
    "z",
    "width",
    "depth",
    "height",
    "type",
    "density",
    "roof",
    "is_tower",
}

REQUIRED_TREE_FIELDS = {"x", "y", "z", "scale"}
TOP_LEVEL_LIST_FIELDS = ("buildings", "trees", "roads")


class CityDataError(ValueError):
    """Raised when city input data does not match the PRD contract."""


class BlenderUnavailableError(RuntimeError):
    """Raised when Blender-only generation is requested outside Blender."""


def get_bpy(required: bool = True) -> Any:
    """Return Blender's `bpy` module, or handle non-Blender execution clearly."""

    try:
        import bpy  # type: ignore[import-not-found]
    except ImportError as exc:
        if required:
            raise BlenderUnavailableError(
                "Blender API is not available. Run this script with Blender "
                "(for example: blender --python blender_generator/city_generator.py)."
            ) from exc
        return None

    return bpy


def load_city_data(filepath: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load and validate a PRD-format city JSON file."""

    path = Path(filepath)
    with path.open("r", encoding="utf-8") as file:
        raw_data = json.load(file)

    return validate_city_data(raw_data)


def load_terrain_data(filepath: str | Path | None) -> dict[str, Any] | None:
    """Load optional A-line macro terrain grid data."""

    if filepath is None:
        return None

    path = Path(filepath)
    if not path.exists():
        print(f"Terrain data not found; skipping terrain: {path}")
        return None

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        raise CityDataError(f"{path} must contain a terrain cells list")
    return data


def validate_city_data(data: Any) -> dict[str, list[dict[str, Any]]]:
    """Validate and normalize city data.

    Missing top-level `buildings`, `trees`, and `roads` fields are normalized
    to empty lists. Present fields must be lists.
    """

    if not isinstance(data, dict):
        raise CityDataError("city data must be a JSON object")

    normalized: dict[str, list[dict[str, Any]]] = {}
    for field in TOP_LEVEL_LIST_FIELDS:
        value = data.get(field, [])
        if not isinstance(value, list):
            raise CityDataError(f"{field} must be a list")
        normalized[field] = value

    _validate_items(
        normalized["buildings"],
        REQUIRED_BUILDING_FIELDS,
        item_name="building",
    )
    _validate_items(
        normalized["trees"],
        REQUIRED_TREE_FIELDS,
        item_name="tree",
    )
    for index, road in enumerate(normalized["roads"]):
        if not isinstance(road, dict):
            raise CityDataError(f"road {index} must be an object")
        if "points" not in road or not isinstance(road["points"], list):
            raise CityDataError(f"road {index} missing points list")

    return normalized


def _validate_items(
    items: list[Any],
    required_fields: set[str],
    item_name: str,
) -> None:
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise CityDataError(f"{item_name} {index} must be an object")

        for field in sorted(required_fields):
            if field not in item:
                raise CityDataError(f"{item_name} {index} missing required field: {field}")


def clear_scene() -> None:
    """Clear the current Blender scene.

    Outside Blender this function is a no-op so data-loading checks can run in
    regular Python.
    """

    bpy = get_bpy(required=False)
    if bpy is None:
        print("Blender API not available; skipping scene clear.")
        return

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def create_diffuse_material(name: str, color: tuple[float, float, float, float]) -> Any:
    """Create or update one reusable diffuse clay material."""

    bpy = get_bpy()
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    material.use_nodes = False
    material.diffuse_color = color
    return material


def create_emission_material(
    name: str,
    color: tuple[float, float, float, float],
    strength: float,
) -> Any:
    """Create or update one reusable emission material."""

    bpy = get_bpy()
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    material.diffuse_color = color
    material.use_nodes = True
    nodes = material.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = strength

    return material


def create_materials() -> dict[str, Any]:
    """Create the unified reusable material set for the scene."""

    diffuse_materials = {
        "mat_wall_clay": (0.86, 0.84, 0.78, 1.0),
        "mat_roof_clay": (0.62, 0.60, 0.55, 1.0),
        "mat_trunk": (0.58, 0.56, 0.52, 1.0),
        "mat_tree": (0.78, 0.80, 0.76, 1.0),
        "mat_ground": (0.80, 0.79, 0.74, 1.0),
        "mat_foundation": (0.76, 0.74, 0.68, 1.0),
        "mat_road_primary": (0.50, 0.48, 0.42, 1.0),
        "mat_road_secondary": (0.56, 0.54, 0.48, 1.0),
        "mat_road_alley": (0.42, 0.40, 0.35, 1.0),
        "mat_road_courtyard": (0.64, 0.59, 0.48, 1.0),
    }
    materials = {
        name: create_diffuse_material(name, color)
        for name, color in diffuse_materials.items()
    }
    for state, color in TERRAIN_STATE_COLORS.items():
        materials[f"mat_terrain_state_{state}"] = create_diffuse_material(
            f"mat_terrain_state_{state}",
            color,
        )
    return materials


def create_terrain_surface(terrain_data: dict[str, Any], materials: dict[str, Any]) -> Any:
    """Create a centered A-line 30x30 terrain surface mesh."""

    bpy = get_bpy()
    metadata = terrain_data.get("metadata", {})
    grid_size = int(metadata.get("grid_size", 30))
    cell_size = float(metadata.get("cell_size", 1.0))
    offset = grid_size * cell_size / 2

    cell_lookup = {
        (int(cell["x"]), int(cell["y"])): cell
        for cell in terrain_data["cells"]
    }
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    material_indexes: list[int] = []

    for vy in range(grid_size + 1):
        for vx in range(grid_size + 1):
            neighbor_heights = [
                cell_lookup[(cx, cy)]["height"]
                for cx in (vx - 1, vx)
                for cy in (vy - 1, vy)
                if (cx, cy) in cell_lookup
            ]
            height = sum(neighbor_heights) / len(neighbor_heights) if neighbor_heights else 0.0
            vertices.append(
                (
                    vx * cell_size - offset,
                    vy * cell_size - offset,
                    height,
                )
            )

    for y in range(grid_size):
        for x in range(grid_size):
            bottom_left = y * (grid_size + 1) + x
            bottom_right = bottom_left + 1
            top_left = (y + 1) * (grid_size + 1) + x
            top_right = top_left + 1
            faces.append((bottom_left, bottom_right, top_right, top_left))
            cell = cell_lookup.get((x, y), {})
            material_indexes.append(int(cell.get("state", 0)))

    mesh = bpy.data.meshes.new("Terrain_Surface_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    terrain = bpy.data.objects.new("Terrain_Surface", mesh)
    bpy.context.collection.objects.link(terrain)

    for state in sorted(TERRAIN_STATE_COLORS):
        terrain.data.materials.append(materials[f"mat_terrain_state_{state}"])
    for polygon, material_index in zip(terrain.data.polygons, material_indexes):
        polygon.material_index = max(0, min(material_index, len(TERRAIN_STATE_COLORS) - 1))
    return terrain


def create_road_batch(roads: list[dict[str, Any]], materials: dict[str, Any]) -> Any:
    """Create road polylines as one batched strip mesh."""

    if not roads:
        return None

    bpy = get_bpy()
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    material_indexes: list[int] = []
    material_by_level = {
        "primary": 0,
        "secondary": 1,
        "alley": 2,
        "courtyard_path": 3,
    }

    for road in roads:
        points = road.get("points", [])
        if len(points) < 2:
            continue
        width = float(road.get("width", 0.08))
        material_index = material_by_level.get(road.get("level"), 2)
        for start_point, end_point in zip(points, points[1:]):
            x1, y1, z1 = start_point
            x2, y2, z2 = end_point
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length <= 0.0001:
                continue
            offset_x = -dy / length * width / 2
            offset_y = dx / length * width / 2
            start_index = len(vertices)
            vertices.extend(
                [
                    (x1 + offset_x, y1 + offset_y, z1),
                    (x1 - offset_x, y1 - offset_y, z1),
                    (x2 - offset_x, y2 - offset_y, z2),
                    (x2 + offset_x, y2 + offset_y, z2),
                ]
            )
            faces.append((start_index, start_index + 1, start_index + 2, start_index + 3))
            material_indexes.append(material_index)

    if not faces:
        return None

    mesh = bpy.data.meshes.new("Road_Batch_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    road_batch = bpy.data.objects.new("Road_Batch", mesh)
    bpy.context.collection.objects.link(road_batch)
    for material_name in (
        "mat_road_primary",
        "mat_road_secondary",
        "mat_road_alley",
        "mat_road_courtyard",
    ):
        road_batch.data.materials.append(materials[material_name])
    for polygon, material_index in zip(road_batch.data.polygons, material_indexes):
        polygon.material_index = material_index
    return road_batch


def project_to_terrain(x: float, y: float, z: float) -> float:
    """Return first-version terrain elevation for a point."""

    return z


def create_foundation(
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    foundation_height: float,
    material: Any,
) -> Any:
    """Create one rectangular foundation with its top aligned to `z`."""

    bpy = get_bpy()
    margin = min(min(width, depth) * FOUNDATION_MARGIN_RATIO, FOUNDATION_MAX_MARGIN)
    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=(x, y, z - foundation_height / 2),
    )
    foundation = bpy.context.object
    foundation.name = "Foundation_Block"
    foundation.dimensions = (
        width + margin * 2,
        depth + margin * 2,
        foundation_height,
    )
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if material is not None:
        foundation.data.materials.append(material)

    return foundation


def create_building(
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    height: float,
    material: Any,
) -> Any:
    """Create one ordinary rectangular building body."""

    bpy = get_bpy()
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z + height / 2))
    building = bpy.context.object
    building.name = "House_Block"
    building.dimensions = (width, depth, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if material is not None:
        building.data.materials.append(material)

    return building


def create_tower(
    x: float,
    y: float,
    z: float,
    width: float,
    depth: float,
    height: float,
    material: Any,
) -> Any:
    """Create one flat-top tower body."""

    bpy = get_bpy()
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z + height / 2))
    tower = bpy.context.object
    tower.name = "Tower_Block"
    tower.dimensions = (width, depth, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if material is not None:
        tower.data.materials.append(material)

    return tower


def create_gable_roof(
    x: float,
    y: float,
    z_top: float,
    width: float,
    depth: float,
    roof_height: float,
    material: Any,
) -> Any:
    """Create one gable roof mesh on top of a rectangular house footprint."""

    bpy = get_bpy()
    half_width = width / 2
    half_depth = depth / 2
    z_peak = z_top + roof_height

    if width >= depth:
        vertices = [
            (-half_width, -half_depth, z_top),
            (half_width, -half_depth, z_top),
            (half_width, half_depth, z_top),
            (-half_width, half_depth, z_top),
            (-half_width, 0, z_peak),
            (half_width, 0, z_peak),
        ]
        faces = [
            (0, 1, 2, 3),
            (0, 4, 5, 1),
            (3, 2, 5, 4),
            (0, 3, 4),
            (1, 5, 2),
        ]
    else:
        vertices = [
            (-half_width, -half_depth, z_top),
            (half_width, -half_depth, z_top),
            (half_width, half_depth, z_top),
            (-half_width, half_depth, z_top),
            (0, -half_depth, z_peak),
            (0, half_depth, z_peak),
        ]
        faces = [
            (0, 1, 2, 3),
            (0, 4, 5, 3),
            (1, 2, 5, 4),
            (0, 1, 4),
            (3, 5, 2),
        ]

    mesh = bpy.data.meshes.new("Gable_Roof_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    roof = bpy.data.objects.new("Gable_Roof", mesh)
    roof.location = (x, y, 0)
    bpy.context.collection.objects.link(roof)

    if material is not None:
        roof.data.materials.append(material)

    return roof


def create_box_batch(
    name: str,
    boxes: list[tuple[float, float, float, float, float, float]],
    material: Any,
) -> Any:
    """Create many axis-aligned boxes as one mesh."""

    if not boxes:
        return None

    bpy = get_bpy()
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for x, y, center_z, width, depth, height in boxes:
        start = len(vertices)
        half_width = width / 2
        half_depth = depth / 2
        bottom = center_z - height / 2
        top = center_z + height / 2
        vertices.extend(
            [
                (x - half_width, y - half_depth, bottom),
                (x + half_width, y - half_depth, bottom),
                (x + half_width, y + half_depth, bottom),
                (x - half_width, y + half_depth, bottom),
                (x - half_width, y - half_depth, top),
                (x + half_width, y - half_depth, top),
                (x + half_width, y + half_depth, top),
                (x - half_width, y + half_depth, top),
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

    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    if material is not None:
        obj.data.materials.append(material)
    return obj


def create_gable_roof_batch(
    roofs: list[tuple[float, float, float, float, float, float]],
    material: Any,
) -> Any:
    """Create many gable roofs as one mesh."""

    if not roofs:
        return None

    bpy = get_bpy()
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for x, y, z_top, width, depth, roof_height in roofs:
        start = len(vertices)
        half_width = width / 2
        half_depth = depth / 2
        z_peak = z_top + roof_height

        if width >= depth:
            local_vertices = [
                (x - half_width, y - half_depth, z_top),
                (x + half_width, y - half_depth, z_top),
                (x + half_width, y + half_depth, z_top),
                (x - half_width, y + half_depth, z_top),
                (x - half_width, y, z_peak),
                (x + half_width, y, z_peak),
            ]
            local_faces = [
                (0, 1, 2, 3),
                (0, 4, 5, 1),
                (3, 2, 5, 4),
                (0, 3, 4),
                (1, 5, 2),
            ]
        else:
            local_vertices = [
                (x - half_width, y - half_depth, z_top),
                (x + half_width, y - half_depth, z_top),
                (x + half_width, y + half_depth, z_top),
                (x - half_width, y + half_depth, z_top),
                (x, y - half_depth, z_peak),
                (x, y + half_depth, z_peak),
            ]
            local_faces = [
                (0, 1, 2, 3),
                (0, 4, 5, 3),
                (1, 2, 5, 4),
                (0, 1, 4),
                (3, 5, 2),
            ]

        vertices.extend(local_vertices)
        faces.extend(tuple(start + index for index in face) for face in local_faces)

    mesh = bpy.data.meshes.new("Gable_Roof_Batch_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    roof_batch = bpy.data.objects.new("Gable_Roof_Batch", mesh)
    bpy.context.collection.objects.link(roof_batch)
    if material is not None:
        roof_batch.data.materials.append(material)
    return roof_batch


def create_window_plane(
    location: tuple[float, float, float],
    rotation: tuple[float, float, float],
    width: float,
    height: float,
    material: Any,
) -> Any:
    """Create one facade-mounted window plane."""

    bpy = get_bpy()
    bpy.ops.mesh.primitive_plane_add(size=1, location=location, rotation=rotation)
    window = bpy.context.object
    window.name = "Window_Plane"
    window.dimensions = (width, height, 0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if material is not None:
        window.data.materials.append(material)

    return window


def create_tree(
    x: float,
    y: float,
    z: float,
    scale: float,
    trunk_material: Any,
    crown_material: Any,
    rng: random.Random,
) -> dict[str, Any]:
    """Create one simplified tree from a trunk cylinder and cone crown."""

    bpy = get_bpy()
    varied_scale = scale * (1 + rng.uniform(-TREE_RANDOM_SCALE, TREE_RANDOM_SCALE))
    varied_scale = max(varied_scale, 0.1)
    rotation_z = rng.uniform(0, 6.28318530718)

    trunk_radius = TREE_TRUNK_RADIUS * varied_scale
    trunk_height = TREE_TRUNK_HEIGHT * varied_scale
    crown_radius = TREE_CROWN_RADIUS * varied_scale
    crown_height = TREE_CROWN_HEIGHT * varied_scale
    crown_base_z = z + trunk_height * 0.25

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=TREE_SEGMENTS,
        radius=trunk_radius,
        depth=trunk_height,
        location=(x, y, z + trunk_height / 2),
        rotation=(0, 0, rotation_z),
    )
    trunk = bpy.context.object
    trunk.name = "Tree_Trunk"
    if trunk_material is not None:
        trunk.data.materials.append(trunk_material)

    bpy.ops.mesh.primitive_cone_add(
        vertices=TREE_SEGMENTS,
        radius1=crown_radius,
        radius2=0,
        depth=crown_height,
        location=(x, y, crown_base_z + crown_height / 2),
        rotation=(0, 0, rotation_z),
    )
    crown = bpy.context.object
    crown.name = "Tree_Crown"
    if crown_material is not None:
        crown.data.materials.append(crown_material)

    return {"trunk": trunk, "crown": crown}


def create_tree_batch(
    trees: list[dict[str, Any]],
    trunk_material: Any,
    crown_material: Any,
    rng: random.Random,
) -> Any:
    """Create all trees as one mesh to keep full-city generation responsive."""

    if not trees:
        return None

    bpy = get_bpy()
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    material_indexes: list[int] = []

    def add_face(face: tuple[int, ...], material_index: int) -> None:
        faces.append(face)
        material_indexes.append(material_index)

    for tree in trees:
        x = tree["x"]
        y = tree["y"]
        z = tree["z"]
        varied_scale = tree["scale"] * (1 + rng.uniform(-TREE_RANDOM_SCALE, TREE_RANDOM_SCALE))
        varied_scale = max(varied_scale, 0.1)
        rotation_z = rng.uniform(0, 6.28318530718)

        trunk_radius = TREE_TRUNK_RADIUS * varied_scale
        trunk_height = TREE_TRUNK_HEIGHT * varied_scale
        crown_radius = TREE_CROWN_RADIUS * varied_scale
        crown_height = TREE_CROWN_HEIGHT * varied_scale
        crown_base_z = z + trunk_height * 0.25

        cos_r = math.cos(rotation_z)
        sin_r = math.sin(rotation_z)

        trunk_start = len(vertices)
        for level_z in (z, z + trunk_height):
            for index in range(TREE_SEGMENTS):
                angle = 2 * math.pi * index / TREE_SEGMENTS
                local_x = math.cos(angle) * trunk_radius
                local_y = math.sin(angle) * trunk_radius
                vertices.append(
                    (
                        x + local_x * cos_r - local_y * sin_r,
                        y + local_x * sin_r + local_y * cos_r,
                        level_z,
                    )
                )

        bottom = tuple(trunk_start + index for index in range(TREE_SEGMENTS))
        top = tuple(trunk_start + TREE_SEGMENTS + index for index in range(TREE_SEGMENTS))
        add_face(tuple(reversed(bottom)), 0)
        add_face(top, 0)
        for index in range(TREE_SEGMENTS):
            next_index = (index + 1) % TREE_SEGMENTS
            add_face(
                (
                    trunk_start + index,
                    trunk_start + next_index,
                    trunk_start + TREE_SEGMENTS + next_index,
                    trunk_start + TREE_SEGMENTS + index,
                ),
                0,
            )

        crown_start = len(vertices)
        for index in range(TREE_SEGMENTS):
            angle = 2 * math.pi * index / TREE_SEGMENTS
            local_x = math.cos(angle) * crown_radius
            local_y = math.sin(angle) * crown_radius
            vertices.append(
                (
                    x + local_x * cos_r - local_y * sin_r,
                    y + local_x * sin_r + local_y * cos_r,
                    crown_base_z,
                )
            )
        tip_index = len(vertices)
        vertices.append((x, y, crown_base_z + crown_height))
        base = tuple(crown_start + index for index in range(TREE_SEGMENTS))
        add_face(tuple(reversed(base)), 1)
        for index in range(TREE_SEGMENTS):
            next_index = (index + 1) % TREE_SEGMENTS
            add_face((crown_start + index, crown_start + next_index, tip_index), 1)

    mesh = bpy.data.meshes.new("Tree_Batch_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    tree_batch = bpy.data.objects.new("Tree_Batch", mesh)
    bpy.context.collection.objects.link(tree_batch)
    if trunk_material is not None:
        tree_batch.data.materials.append(trunk_material)
    if crown_material is not None:
        tree_batch.data.materials.append(crown_material)
    for polygon, material_index in zip(tree_batch.data.polygons, material_indexes):
        polygon.material_index = material_index
    return tree_batch


def compute_scene_mesh_bounds() -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return center and size for generated mesh objects in the current scene."""

    bpy = get_bpy()
    mathutils = __import__("mathutils")
    min_corner = [float("inf"), float("inf"), float("inf")]
    max_corner = [float("-inf"), float("-inf"), float("-inf")]
    found_mesh = False

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue

        found_mesh = True
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ mathutils.Vector(corner)
            for axis in range(3):
                min_corner[axis] = min(min_corner[axis], world_corner[axis])
                max_corner[axis] = max(max_corner[axis], world_corner[axis])

    if not found_mesh:
        return CAMERA_DEFAULT_CENTER, CAMERA_DEFAULT_SIZE

    center = tuple((min_corner[axis] + max_corner[axis]) / 2 for axis in range(3))
    size = tuple(max_corner[axis] - min_corner[axis] for axis in range(3))
    return center, size


def _look_at(obj: Any, target: tuple[float, float, float]) -> None:
    """Rotate an object so its local -Z axis points at a target."""

    mathutils = __import__("mathutils")
    direction = mathutils.Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _get_or_create_light(name: str, light_type: str) -> Any:
    bpy = get_bpy()
    light = bpy.data.objects.get(name)
    if light is not None and light.type == "LIGHT" and light.data.type == light_type:
        return light

    light_data = bpy.data.lights.new(name, type=light_type)
    light = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(light)
    return light


def setup_camera_and_lighting() -> dict[str, Any]:
    """Create overview camera and soft lighting for direct preview rendering."""

    bpy = get_bpy()
    mathutils = __import__("mathutils")
    center, size = compute_scene_mesh_bounds()
    max_span = max(size[0], size[1], CAMERA_MIN_ORTHO_SCALE)
    height_span = max(size[2], 1.0)
    distance = max(max_span, height_span) * CAMERA_DISTANCE_MULTIPLIER
    camera_location = mathutils.Vector(
        (
            center[0] - distance,
            center[1] - distance,
            center[2] + distance * 0.9,
        )
    )

    camera_data = bpy.data.cameras.get("Overview_Camera")
    if camera_data is None:
        camera_data = bpy.data.cameras.new("Overview_Camera")

    camera = bpy.data.objects.get("Overview_Camera")
    if camera is None or camera.type != "CAMERA":
        camera = bpy.data.objects.new("Overview_Camera", camera_data)
        bpy.context.collection.objects.link(camera)

    camera.location = camera_location
    _look_at(camera, center)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(max_span * CAMERA_ORTHO_MARGIN, CAMERA_MIN_ORTHO_SCALE)
    camera.data.lens = 35
    bpy.context.scene.camera = camera

    sun = _get_or_create_light("Sun_Key_Light", "SUN")
    sun.data.energy = SUN_LIGHT_ENERGY
    sun.rotation_euler = (
        math.radians(45),
        0,
        math.radians(-35),
    )

    area = _get_or_create_light("Area_Fill_Light", "AREA")
    area.location = (
        center[0] + max_span * 0.2,
        center[1] - max_span * 0.5,
        center[2] + distance * 0.75,
    )
    _look_at(area, center)
    area.data.energy = AREA_LIGHT_ENERGY
    area.data.size = AREA_LIGHT_SIZE

    return {"camera": camera, "sun": sun, "area": area}


def setup_render_settings() -> None:
    """Configure fast preview render settings for the generated city scene."""

    bpy = get_bpy()
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue

    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        if hasattr(eevee, "use_gtao"):
            eevee.use_gtao = True
        if hasattr(eevee, "gtao_distance"):
            eevee.gtao_distance = 3
        if hasattr(eevee, "gtao_factor"):
            eevee.gtao_factor = 1.2

    scene.render.resolution_x = RENDER_RESOLUTION_X
    scene.render.resolution_y = RENDER_RESOLUTION_Y
    scene.render.film_transparent = False

    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.86, 0.88, 0.90)


def is_house_building(building: dict[str, Any]) -> bool:
    """Return true when a building record should generate an ordinary house block."""

    return building.get("type") == "house" and building.get("is_tower") is False


def is_tower_building(building: dict[str, Any]) -> bool:
    """Return true when a building record should generate a tower."""

    return building.get("type") == "tower" or building.get("is_tower") is True


def has_gable_roof(building: dict[str, Any]) -> bool:
    """Return true when an ordinary house record should receive a gable roof."""

    return is_house_building(building)


def _window_offsets(facade_length: float, spacing: float) -> list[float]:
    column_count = max(1, int(facade_length // spacing))
    step = facade_length / (column_count + 1)
    return [(-facade_length / 2) + step * (index + 1) for index in range(column_count)]


def add_windows(
    building: dict[str, Any],
    materials: dict[str, Any],
    rng: random.Random,
    is_tower: bool = False,
) -> dict[str, int]:
    """Add window planes to all four facades of a building record."""

    width = building["width"]
    depth = building["depth"]
    height = building["height"]
    x = building["x"]
    y = building["y"]
    z = building["z"]

    window_scale = TOWER_WINDOW_SCALE if is_tower else 1.0
    window_width = WINDOW_WIDTH * window_scale
    window_height = WINDOW_HEIGHT * window_scale
    spacing = WINDOW_SPACING * (TOWER_WINDOW_SPACING_MULTIPLIER if is_tower else 1.0)
    light_probability = (
        TOWER_WINDOW_LIGHT_PROBABILITY if is_tower else WINDOW_LIGHT_PROBABILITY
    )

    row_count = max(1, int(height // FLOOR_HEIGHT))
    row_heights = [
        z + min((row_index + 0.5) * FLOOR_HEIGHT, height - window_height / 2)
        for row_index in range(row_count)
    ]

    dark_material = materials["mat_window_dark"]
    light_material = materials["mat_window_light"]
    total_count = 0
    lit_count = 0

    facade_specs = [
        {
            "length": depth,
            "offset_axis": "y",
            "fixed": (x + width / 2 + WINDOW_FACADE_OFFSET, None),
            "rotation": (0, 1.57079632679, 0),
        },
        {
            "length": depth,
            "offset_axis": "y",
            "fixed": (x - width / 2 - WINDOW_FACADE_OFFSET, None),
            "rotation": (0, -1.57079632679, 0),
        },
        {
            "length": width,
            "offset_axis": "x",
            "fixed": (None, y + depth / 2 + WINDOW_FACADE_OFFSET),
            "rotation": (-1.57079632679, 0, 0),
        },
        {
            "length": width,
            "offset_axis": "x",
            "fixed": (None, y - depth / 2 - WINDOW_FACADE_OFFSET),
            "rotation": (1.57079632679, 0, 0),
        },
    ]

    for facade in facade_specs:
        for offset in _window_offsets(facade["length"], spacing):
            for z_center in row_heights:
                is_lit = rng.random() < light_probability
                material = light_material if is_lit else dark_material
                fixed_x, fixed_y = facade["fixed"]
                if facade["offset_axis"] == "y":
                    location = (fixed_x, y + offset, z_center)
                else:
                    location = (x + offset, fixed_y, z_center)

                create_window_plane(
                    location=location,
                    rotation=facade["rotation"],
                    width=window_width,
                    height=window_height,
                    material=material,
                )
                total_count += 1
                if is_lit:
                    lit_count += 1

    return {"windows": total_count, "lit_windows": lit_count}


def generate_city(
    data: dict[str, list[dict[str, Any]]],
    materials: dict[str, Any],
) -> dict[str, int]:
    """Generate currently supported city geometry and return counts."""

    wall_material = materials["mat_wall_clay"]
    roof_material = materials["mat_roof_clay"]
    foundation_material = materials["mat_foundation"]
    house_count = 0
    gable_roof_count = 0
    tower_count = 0
    foundation_count = 0
    window_count = 0
    lit_window_count = 0
    tree_count = 0
    road_count = 0
    rng = random.Random(RANDOM_SEED)
    house_boxes: list[tuple[float, float, float, float, float, float]] = []
    tower_boxes: list[tuple[float, float, float, float, float, float]] = []
    foundation_boxes: list[tuple[float, float, float, float, float, float]] = []
    gable_roofs: list[tuple[float, float, float, float, float, float]] = []

    for building in data["buildings"]:
        base_z = project_to_terrain(building["x"], building["y"], building["z"])
        foundation_height = min(
            building["height"] * FOUNDATION_HEIGHT_RATIO,
            FOUNDATION_MAX_HEIGHT,
        )
        foundation_margin = min(
            min(building["width"], building["depth"]) * FOUNDATION_MARGIN_RATIO,
            FOUNDATION_MAX_MARGIN,
        )
        foundation_boxes.append(
            (
                building["x"],
                building["y"],
                base_z - foundation_height / 2,
                building["width"] + foundation_margin * 2,
                building["depth"] + foundation_margin * 2,
                foundation_height,
            )
        )
        foundation_count += 1

        if is_tower_building(building):
            tower_boxes.append(
                (
                    building["x"],
                    building["y"],
                    base_z + building["height"] / 2,
                    building["width"],
                    building["depth"],
                    building["height"],
                )
            )
            tower_count += 1
            continue

        if not is_house_building(building):
            continue

        house_boxes.append(
            (
                building["x"],
                building["y"],
                base_z + building["height"] / 2,
                building["width"],
                building["depth"],
                building["height"],
            )
        )
        house_count += 1

        if has_gable_roof(building):
            roof_height = min(building["width"], building["depth"]) * ROOF_HEIGHT_RATIO
            gable_roofs.append(
                (
                    building["x"],
                    building["y"],
                    base_z + building["height"],
                    building["width"],
                    building["depth"],
                    roof_height,
                )
            )
            gable_roof_count += 1

    create_box_batch("Foundation_Batch", foundation_boxes, foundation_material)
    create_box_batch("House_Batch", house_boxes, wall_material)
    create_box_batch("Tower_Batch", tower_boxes, wall_material)
    create_gable_roof_batch(gable_roofs, roof_material)

    if data["trees"]:
        create_tree_batch(
            trees=data["trees"],
            trunk_material=materials["mat_trunk"],
            crown_material=materials["mat_tree"],
            rng=rng,
        )
        tree_count = len(data["trees"])

    if data["roads"]:
        create_road_batch(data["roads"], materials)
        road_count = len(data["roads"])

    return {
        "houses": house_count,
        "gable_roofs": gable_roof_count,
        "towers": tower_count,
        "foundations": foundation_count,
        "windows": window_count,
        "lit_windows": lit_window_count,
        "trees": tree_count,
        "roads": road_count,
    }


def main(
    filepath: str | Path = DEFAULT_CITY_DATA_PATH,
    terrain_filepath: str | Path | None = DEFAULT_TERRAIN_DATA_PATH,
    save_blend: str | Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Clear the scene, load city data, generate houses, and print statistics."""

    clear_scene()
    city_data = load_city_data(filepath)
    terrain_data = load_terrain_data(terrain_filepath)
    print(
        "Loaded city data: "
        f"{len(city_data['buildings'])} buildings, "
        f"{len(city_data['trees'])} trees."
    )

    if get_bpy(required=False) is None:
        print("Blender API not available; skipping house block generation.")
        return city_data

    materials = create_materials()
    if terrain_data is not None:
        create_terrain_surface(terrain_data, materials)
        print(f"Generated terrain cells: {len(terrain_data['cells'])}.")
    generated_counts = generate_city(city_data, materials)
    setup_camera_and_lighting()
    setup_render_settings()
    print(f"Generated house blocks: {generated_counts['houses']}.")
    print(f"Generated gable roofs: {generated_counts['gable_roofs']}.")
    print(f"Generated towers: {generated_counts['towers']}.")
    print(f"Generated foundations: {generated_counts['foundations']}.")
    print(
        "Generated windows: "
        f"{generated_counts['windows']} total, "
        f"{generated_counts['lit_windows']} lit."
    )
    print(f"Generated trees: {generated_counts['trees']}.")
    print(f"Generated roads: {generated_counts['roads']}.")
    print("Camera, lighting, and render settings configured.")

    if save_blend is not None:
        bpy = get_bpy()
        output_path = Path(save_blend)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
        print(f"Saved Blender scene: {output_path}")

    return city_data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse script-only arguments, including Blender's args-after-`--` style."""

    if argv is None:
        argv = sys.argv[1:]
        if "--" in argv:
            argv = argv[argv.index("--") + 1 :]
        elif get_bpy(required=False) is not None:
            argv = []

    parser = argparse.ArgumentParser(description="Generate a Blender city scene.")
    parser.add_argument(
        "--city-data",
        type=Path,
        default=DEFAULT_CITY_DATA_PATH,
        help=f"Path to Blender city data JSON. Default: {DEFAULT_CITY_DATA_PATH}",
    )
    parser.add_argument(
        "--save-blend",
        type=Path,
        default=None,
        help="Optional path to save the generated Blender scene.",
    )
    parser.add_argument(
        "--terrain-data",
        type=Path,
        default=DEFAULT_TERRAIN_DATA_PATH,
        help=f"Path to A-line terrain grid JSON. Default: {DEFAULT_TERRAIN_DATA_PATH}",
    )
    parser.add_argument(
        "--no-terrain",
        action="store_true",
        help="Skip terrain surface generation.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    main(
        args.city_data,
        terrain_filepath=None if args.no_terrain else args.terrain_data,
        save_blend=args.save_blend,
    )
