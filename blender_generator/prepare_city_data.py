"""Convert Swarm-Algorithm outputs into Blender generator city_data.json.

The Blender generator consumes one JSON object with `buildings`, `trees`, and
`roads` lists. The A-line pipeline currently writes buildings as JSON and trees
as CSV, so this adapter joins them into that shared format.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
from typing import Any

try:
    from blender_generator import agent_road_network
except ImportError:
    import agent_road_network


DEFAULT_BUILDINGS_PATH = Path("output/city_buildings_scheme2_scaleA_mergeB.json")
DEFAULT_TREES_PATH = Path("output/city_trees_scheme2_scaleA_mergeB.csv")
DEFAULT_MACRO_GRID_PATH = Path("output/city_grid_15x15_scheme2.json")
DEFAULT_OUTPUT_PATH = Path("blender_generator/city_data.json")
A_LINE_GRID_SIZE = 15.0
A_LINE_CELL_SIZE = 1.0
VISUAL_FLOOR_HEIGHT = 0.14
HOUSE_MIN_FLOORS = 2
HOUSE_MAX_FLOORS = 3
TOWER_MIN_VISUAL_FLOORS = 8
TOWER_MAX_VISUAL_FLOORS = 9
TOWER_MIN_VISUAL_FOOTPRINT = 0.24
MACRO_BUILDING_CAPS = {
    "low": (2, 4),
    "medium": (4, 6),
    "high": (6, 8),
}
TOWER_PODIUM_CAP_RANGE = (2, 4)

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
NUMERIC_BUILDING_FIELDS = {"x", "y", "z", "width", "depth", "height"}
NUMERIC_TREE_FIELDS = {"x", "y", "z", "scale"}


class AdapterError(ValueError):
    """Raised when A-line outputs cannot be converted safely."""


def _to_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"{field} must be numeric, got {value!r}") from exc


def _to_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"{field} must be an integer, got {value!r}") from exc


def normalize_visual_height(building: dict[str, Any]) -> None:
    """Use compact review heights while preserving A-line source values."""

    building.setdefault("source_floor_count", building.get("floor_count"))
    building.setdefault("source_height", building.get("height"))
    if building["is_tower"]:
        floor_span = TOWER_MAX_VISUAL_FLOORS - TOWER_MIN_VISUAL_FLOORS + 1
        floor_count = TOWER_MIN_VISUAL_FLOORS + building["id"] % floor_span
        building["width"] = max(building["width"], TOWER_MIN_VISUAL_FOOTPRINT)
        building["depth"] = max(building["depth"], TOWER_MIN_VISUAL_FOOTPRINT)
    else:
        floor_span = HOUSE_MAX_FLOORS - HOUSE_MIN_FLOORS + 1
        floor_count = HOUSE_MIN_FLOORS + building["id"] % floor_span

    building["floor_count"] = floor_count
    building["height"] = round(floor_count * VISUAL_FLOOR_HEIGHT, 4)


def load_buildings(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    buildings = payload.get("buildings") if isinstance(payload, dict) else payload
    if not isinstance(buildings, list):
        raise AdapterError(f"{path} must contain a buildings list")

    normalized: list[dict[str, Any]] = []
    for index, building in enumerate(buildings):
        if not isinstance(building, dict):
            raise AdapterError(f"building {index} must be an object")

        missing = REQUIRED_BUILDING_FIELDS - set(building)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise AdapterError(f"building {index} missing required fields: {missing_fields}")

        item = dict(building)
        item["id"] = _to_int(item["id"], f"building {index}.id")
        for field in NUMERIC_BUILDING_FIELDS:
            item[field] = _to_float(item[field], f"building {index}.{field}")
        if "footprint" in item:
            if not isinstance(item["footprint"], list) or len(item["footprint"]) < 3:
                raise AdapterError(f"building {index}.footprint must be a list of at least 3 points")
            normalized_footprint = []
            for point_index, point in enumerate(item["footprint"]):
                if not isinstance(point, dict):
                    raise AdapterError(f"building {index}.footprint[{point_index}] must be an object")
                normalized_footprint.append(
                    {
                        "x": _to_float(point.get("x"), f"building {index}.footprint[{point_index}].x"),
                        "y": _to_float(point.get("y"), f"building {index}.footprint[{point_index}].y"),
                    }
                )
            item["footprint"] = normalized_footprint
        item["is_tower"] = bool(item["is_tower"])
        normalize_visual_height(item)
        normalized.append(item)

    return normalized


def load_building_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise AdapterError(f"{path} must contain an object payload")
    return payload


def load_macro_grid(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or not isinstance(payload.get("cells"), list):
        raise AdapterError(f"{path} must contain a macro grid cells list")
    return payload


def load_trees(path: Path) -> list[dict[str, float]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise AdapterError(f"{path} must contain a CSV header")

        missing = REQUIRED_TREE_FIELDS - set(reader.fieldnames)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise AdapterError(f"{path} missing required columns: {missing_fields}")

        trees: list[dict[str, float]] = []
        for index, row in enumerate(reader):
            trees.append(
                {
                    field: _to_float(row[field], f"tree {index}.{field}")
                    for field in NUMERIC_TREE_FIELDS
                }
            )

    return trees


def center_xy(
    x: float,
    y: float,
    grid_size: float = A_LINE_GRID_SIZE,
) -> tuple[float, float]:
    grid_offset = grid_size * A_LINE_CELL_SIZE / 2
    return (
        round(x * A_LINE_CELL_SIZE - grid_offset, 4),
        round(y * A_LINE_CELL_SIZE - grid_offset, 4),
    )


def evenly_sample(items: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Return an evenly spread preview sample across the full A-line sequence."""

    if limit is None or limit >= len(items):
        return items
    if limit == 0:
        return []
    if limit == 1:
        return [items[0]]

    last_index = len(items) - 1
    indexes = {
        round(index * last_index / (limit - 1))
        for index in range(limit)
    }
    return [items[index] for index in sorted(indexes)]


def get_macro_key(item: dict[str, Any]) -> tuple[Any, Any]:
    return item.get("macro_x"), item.get("macro_y")


def get_target_house_cap(buildings: list[dict[str, Any]]) -> int:
    density_counts = Counter(
        building.get("density")
        for building in buildings
        if not building.get("is_tower")
    )
    density = density_counts.most_common(1)[0][0] if density_counts else "low"
    min_cap, max_cap = MACRO_BUILDING_CAPS.get(density, MACRO_BUILDING_CAPS["low"])
    if len(buildings) <= min_cap:
        return len(buildings)
    return min(max_cap, max(min_cap, len(buildings) // 2))


def building_priority(building: dict[str, Any]) -> tuple[float, float, float, float]:
    """Rank tower, large footprint, and macro-boundary buildings first."""

    width_cells = float(building.get("footprint_cells_x", 1) or 1)
    depth_cells = float(building.get("footprint_cells_y", 1) or 1)
    area_score = width_cells * depth_cells
    edge_score = max(
        abs(float(building.get("micro_x", 0)) - 2.5),
        abs(float(building.get("micro_y", 0)) - 2.5),
    )
    source_count = float(building.get("source_cell_count", 1) or 1)
    return (
        1.0 if building.get("is_tower") else 0.0,
        area_score,
        edge_score,
        source_count,
    )


def cap_buildings_per_macro(buildings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Limit each macro cell to compact review counts while keeping key massing."""

    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for building in buildings:
        grouped.setdefault(get_macro_key(building), []).append(building)

    capped: list[dict[str, Any]] = []
    for macro_key in sorted(grouped):
        macro_buildings = grouped[macro_key]
        towers = [building for building in macro_buildings if building.get("is_tower")]
        houses = [building for building in macro_buildings if not building.get("is_tower")]

        selected_towers = sorted(
            towers,
            key=building_priority,
            reverse=True,
        )[:1]
        if selected_towers:
            min_podium, max_podium = TOWER_PODIUM_CAP_RANGE
            podium_cap = min(max_podium, max(min_podium, len(houses) // 2))
            selected_houses = sorted(
                houses,
                key=building_priority,
                reverse=True,
            )[:podium_cap]
        else:
            house_cap = get_target_house_cap(houses)
            selected_houses = sorted(
                houses,
                key=building_priority,
                reverse=True,
            )[:house_cap]

        capped.extend(sorted(selected_towers + selected_houses, key=lambda item: item["id"]))

    return capped


def select_macro_groups(
    buildings: list[dict[str, Any]],
    trees: list[dict[str, Any]],
    max_macro_cells: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep whole macro cells so previews preserve local building groupings."""

    if max_macro_cells is None:
        return buildings, trees
    if max_macro_cells == 0:
        return [], []

    building_counts = Counter(get_macro_key(building) for building in buildings)
    tower_macro_keys = {
        get_macro_key(building)
        for building in buildings
        if building.get("is_tower")
    }
    ranked_macro_keys = sorted(
        building_counts,
        key=lambda macro_key: (
            1 if macro_key in tower_macro_keys else 0,
            building_counts[macro_key],
            macro_key[0],
            macro_key[1],
        ),
        reverse=True,
    )
    selected_macro_keys = {
        macro_key
        for macro_key in ranked_macro_keys[:max_macro_cells]
    }

    selected_buildings = [
        building
        for building in buildings
        if get_macro_key(building) in selected_macro_keys
    ]
    selected_trees = [
        tree
        for tree in trees
        if get_macro_key(tree) in selected_macro_keys
    ]
    return selected_buildings, selected_trees


def recenter_a_line_coordinates(city_data: dict[str, Any]) -> None:
    """Match A-line Blender preview coordinates by centering the macro grid."""

    for building in city_data["buildings"]:
        building["x"], building["y"] = center_xy(building["x"], building["y"])
        if "footprint" in building:
            for point in building["footprint"]:
                point["x"], point["y"] = center_xy(point["x"], point["y"])
    for tree in city_data["trees"]:
        tree["x"], tree["y"] = center_xy(tree["x"], tree["y"])


def build_city_data(
    buildings_path: Path,
    trees_path: Path,
    max_buildings: int | None = None,
    max_trees: int | None = None,
    max_macro_cells: int | None = None,
    cap_macro_buildings: bool = True,
    recenter: bool = True,
    macro_grid_path: Path | None = DEFAULT_MACRO_GRID_PATH,
) -> dict[str, Any]:
    building_payload = load_building_payload(buildings_path)
    buildings = load_buildings(buildings_path)
    trees = load_trees(trees_path)
    macro_grid = load_macro_grid(macro_grid_path)
    spatial_cell_model = building_payload.get("metadata", {}).get("spatial_cell_model", "")
    is_parcel_mode = str(spatial_cell_model).startswith("road_") and "parcel" in str(spatial_cell_model)
    if cap_macro_buildings and not is_parcel_mode:
        buildings = cap_buildings_per_macro(buildings)
    buildings, trees = select_macro_groups(buildings, trees, max_macro_cells)
    selected_macro_keys = {get_macro_key(building) for building in buildings}
    if max_macro_cells is None:
        buildings = evenly_sample(buildings, max_buildings)
        trees = evenly_sample(trees, max_trees)
        selected_macro_keys = None

    road_graph = building_payload.get("road_graph")
    if not isinstance(road_graph, dict):
        raise AdapterError(f"{buildings_path} missing required road_graph object")
    world_scale = float(building_payload.get("metadata", {}).get("world_scale", 1.0) or 1.0)

    city_data = {
        "metadata": {
            "source_spatial_cell_model": building_payload.get("metadata", {}).get("spatial_cell_model"),
            "world_scale": world_scale,
            "height_model": building_payload.get("metadata", {}).get("height_model", "shared_scaled_terrain_sampler"),
        },
        "buildings": buildings,
        "trees": trees,
        "roads": agent_road_network.road_graph_to_blender_roads(
            road_graph,
            z_lookup=terrain_height_lookup(macro_grid, world_scale=world_scale),
        ),
    }
    if recenter:
        recenter_a_line_coordinates(city_data)
    return city_data


def scaled_terrain_height(centered_x: float, centered_y: float, grid_size: float, world_scale: float) -> float:
    source_x = centered_x / world_scale + grid_size / 2
    source_y = centered_y / world_scale + grid_size / 2
    cx = (grid_size - 1) / 2
    cy = (grid_size - 1) / 2
    dx = (source_x - cx) / grid_size
    dy = (source_y - cy) / grid_size
    hill = 2.0 * math.exp(-7.0 * (dx * dx + dy * dy))
    wave = 0.25 * math.sin(source_x * 0.25) + 0.2 * math.cos(source_y * 0.22)
    return round(hill + wave, 3)


def terrain_height_lookup(macro_grid: dict[str, Any] | None, world_scale: float = 1.0):
    if macro_grid is None:
        return None
    grid_size = float(macro_grid.get("metadata", {}).get("grid_size", A_LINE_GRID_SIZE))

    def lookup(centered_x: float, centered_y: float) -> float:
        return scaled_terrain_height(centered_x, centered_y, grid_size, world_scale)

    return lookup


def write_city_data(city_data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(city_data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert A-line building JSON and tree CSV into Blender city_data.json."
    )
    parser.add_argument(
        "--buildings",
        type=Path,
        default=DEFAULT_BUILDINGS_PATH,
        help=f"Path to A-line buildings JSON. Default: {DEFAULT_BUILDINGS_PATH}",
    )
    parser.add_argument(
        "--trees",
        type=Path,
        default=DEFAULT_TREES_PATH,
        help=f"Path to A-line trees CSV. Default: {DEFAULT_TREES_PATH}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output city_data.json path. Default: {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--macro-grid",
        type=Path,
        default=DEFAULT_MACRO_GRID_PATH,
        help=f"Path to A-line macro grid JSON for road generation. Default: {DEFAULT_MACRO_GRID_PATH}",
    )
    parser.add_argument(
        "--max-buildings",
        type=int,
        default=None,
        help="Optional preview limit for the number of buildings to write.",
    )
    parser.add_argument(
        "--max-trees",
        type=int,
        default=None,
        help="Optional preview limit for the number of trees to write.",
    )
    parser.add_argument(
        "--max-macro-cells",
        type=int,
        default=None,
        help="Optional preview limit for whole macro cells; keeps all buildings and trees inside selected cells.",
    )
    parser.add_argument(
        "--no-recenter",
        action="store_true",
        help="Keep original A-line x/y coordinates instead of centering the macro grid.",
    )
    parser.add_argument(
        "--no-macro-building-cap",
        action="store_true",
        help="Keep all A-line buildings instead of limiting each macro cell for review.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_buildings is not None and args.max_buildings < 0:
        raise AdapterError("--max-buildings must be greater than or equal to 0")
    if args.max_trees is not None and args.max_trees < 0:
        raise AdapterError("--max-trees must be greater than or equal to 0")
    if args.max_macro_cells is not None and args.max_macro_cells < 0:
        raise AdapterError("--max-macro-cells must be greater than or equal to 0")

    city_data = build_city_data(
        args.buildings,
        args.trees,
        max_buildings=args.max_buildings,
        max_trees=args.max_trees,
        max_macro_cells=args.max_macro_cells,
        cap_macro_buildings=not args.no_macro_building_cap,
        recenter=not args.no_recenter,
        macro_grid_path=args.macro_grid,
    )
    write_city_data(city_data, args.output)
    print(
        "Wrote Blender city data: "
        f"{len(city_data['buildings'])} buildings, "
        f"{len(city_data['trees'])} trees, "
        f"{len(city_data['roads'])} roads -> {args.output}"
    )


if __name__ == "__main__":
    main()
