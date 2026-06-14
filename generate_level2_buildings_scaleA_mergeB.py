import csv
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ca_level2_rules as rules
import generate_city_grid as base
import generate_level2_buildings as level2


OUTPUT_DIR = SCRIPT_DIR / "output"
SOURCE_JSON = OUTPUT_DIR / "city_buildings_scheme2_scaleA.json"
BUILDING_JSON = OUTPUT_DIR / "city_buildings_scheme2_scaleA_mergeB.json"
BUILDING_CSV = OUTPUT_DIR / "city_buildings_scheme2_scaleA_mergeB.csv"
TREE_CSV = OUTPUT_DIR / "city_trees_scheme2_scaleA_mergeB.csv"
MICRO_GRID_SIZE = rules.MICRO_GRID_SIZE
MICRO_GRID_LABEL = f"{base.GRID_SIZE * MICRO_GRID_SIZE}x{base.GRID_SIZE * MICRO_GRID_SIZE}"
MICRO_SVG = OUTPUT_DIR / f"meso_ca_level2_{MICRO_GRID_LABEL}_scheme2_scaleA_mergeB.svg"
MERGED_FOOTPRINT_SCALE = 0.92
MERGE_SHAPES = [
    (2, 3),
    (3, 2),
    (2, 2),
    (3, 1),
    (1, 3),
    (2, 1),
    (1, 2),
    (1, 1),
]


def load_scale_a_data(path=SOURCE_JSON):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def group_micro_cells(micro_cells):
    grouped = {}
    for cell in micro_cells:
        key = (cell["macro_x"], cell["macro_y"])
        grouped.setdefault(key, {})[(cell["micro_x"], cell["micro_y"])] = cell
    return grouped


def map_buildings_by_micro(buildings):
    return {
        (building["macro_x"], building["macro_y"], building["micro_x"], building["micro_y"]): building
        for building in buildings
    }


def can_merge_shape(state_grid, visited, start_x, start_y, width_cells, depth_cells, parcel_grid=None):
    if start_x + width_cells > MICRO_GRID_SIZE or start_y + depth_cells > MICRO_GRID_SIZE:
        return False

    target_parcel_id = None
    if parcel_grid is not None:
        target_parcel_id = parcel_grid[start_y][start_x]
        if target_parcel_id is None:
            return False

    for my in range(start_y, start_y + depth_cells):
        for mx in range(start_x, start_x + width_cells):
            if visited[my][mx] or state_grid[my][mx] != rules.MICRO_BUILDING:
                return False
            if parcel_grid is not None and parcel_grid[my][mx] != target_parcel_id:
                return False

    return True


def mark_visited(visited, start_x, start_y, width_cells, depth_cells):
    for my in range(start_y, start_y + depth_cells):
        for mx in range(start_x, start_x + width_cells):
            visited[my][mx] = True


def merged_region_corners(grouped_cells, macro_key, start_x, start_y, width_cells, depth_cells):
    bottom_left = grouped_cells[macro_key][(start_x, start_y)]["corners"][0]
    bottom_right = grouped_cells[macro_key][(start_x + width_cells - 1, start_y)]["corners"][1]
    top_right = grouped_cells[macro_key][(start_x + width_cells - 1, start_y + depth_cells - 1)]["corners"][2]
    top_left = grouped_cells[macro_key][(start_x, start_y + depth_cells - 1)]["corners"][3]
    return [bottom_left, bottom_right, top_right, top_left]


def create_merged_building(
    building_id,
    macro_x,
    macro_y,
    start_x,
    start_y,
    width_cells,
    depth_cells,
    source_buildings,
    source_corners,
):
    footprint = level2.scale_polygon(source_corners, MERGED_FOOTPRINT_SCALE)
    center = level2.polygon_center(footprint)
    center_z = level2.sample_scaled_terrain_height(center["x"], center["y"])
    width, depth = level2.fallback_width_depth_from_polygon(footprint)
    floor_count = max(building["floor_count"] for building in source_buildings)
    height = max(building["height"] for building in source_buildings)
    density = source_buildings[0]["density"]
    roof = "gable" if width_cells >= depth_cells else "hip"
    parcel_id = source_buildings[0].get("parcel_id")

    return {
        "id": building_id,
        "x": round(center["x"], 4),
        "y": round(center["y"], 4),
        "z": round(center_z, 4),
        "width": width,
        "depth": depth,
        "height": round(height, 4),
        "floor_count": floor_count,
        "density": density,
        "type": "house",
        "roof": roof,
        "is_tower": False,
        "macro_x": macro_x,
        "macro_y": macro_y,
        "micro_x": start_x,
        "micro_y": start_y,
        "parcel_id": parcel_id,
        "footprint_cells_x": width_cells,
        "footprint_cells_y": depth_cells,
        "source_cell_count": len(source_buildings),
        "footprint": [
            {"x": round(point["x"], 4), "y": round(point["y"], 4)}
            for point in footprint
        ],
    }


def create_tower_record(building_id, tower):
    record = dict(tower)
    record["id"] = building_id
    if "footprint" in record:
        record["width"], record["depth"] = level2.fallback_width_depth_from_polygon(record["footprint"])
    record["footprint_cells_x"] = 1
    record["footprint_cells_y"] = 1
    record["source_cell_count"] = 1
    return record


def merge_buildings(city_data):
    grouped_micro = group_micro_cells(city_data["micro_cells"])
    building_lookup = map_buildings_by_micro(city_data["buildings"])
    is_parcel_mode = bool(city_data.get("parcels"))
    merged_buildings = []
    building_id = 1

    for macro_key in sorted(grouped_micro):
        macro_x, macro_y = macro_key
        state_grid = [[rules.MICRO_EMPTY for _ in range(MICRO_GRID_SIZE)] for _ in range(MICRO_GRID_SIZE)]
        parcel_grid = [[None for _ in range(MICRO_GRID_SIZE)] for _ in range(MICRO_GRID_SIZE)]
        visited = [[False for _ in range(MICRO_GRID_SIZE)] for _ in range(MICRO_GRID_SIZE)]

        for (mx, my), cell in grouped_micro[macro_key].items():
            state_grid[my][mx] = cell["state"]
            parcel_grid[my][mx] = cell.get("parcel_id")

        for my in range(MICRO_GRID_SIZE):
            for mx in range(MICRO_GRID_SIZE):
                if state_grid[my][mx] == rules.MICRO_TOWER:
                    tower = building_lookup.get((macro_x, macro_y, mx, my))
                    if tower:
                        merged_buildings.append(create_tower_record(building_id, tower))
                        building_id += 1
                    visited[my][mx] = True

        for my in range(MICRO_GRID_SIZE):
            for mx in range(MICRO_GRID_SIZE):
                if visited[my][mx] or state_grid[my][mx] != rules.MICRO_BUILDING:
                    continue

                chosen_shape = (1, 1)
                for width_cells, depth_cells in MERGE_SHAPES:
                    if can_merge_shape(
                        state_grid,
                        visited,
                        mx,
                        my,
                        width_cells,
                        depth_cells,
                        parcel_grid if is_parcel_mode else None,
                    ):
                        chosen_shape = (width_cells, depth_cells)
                        break

                width_cells, depth_cells = chosen_shape
                source_buildings = []
                for sy in range(my, my + depth_cells):
                    for sx in range(mx, mx + width_cells):
                        source = building_lookup.get((macro_x, macro_y, sx, sy))
                        if source:
                            source_buildings.append(source)

                if source_buildings:
                    merged_buildings.append(
                        create_merged_building(
                            building_id,
                            macro_x,
                            macro_y,
                            mx,
                            my,
                            width_cells,
                            depth_cells,
                            source_buildings,
                            merged_region_corners(
                                grouped_micro,
                                macro_key,
                                mx,
                                my,
                                width_cells,
                                depth_cells,
                            ),
                        )
                    )
                    building_id += 1

                mark_visited(visited, mx, my, width_cells, depth_cells)

    return merged_buildings


def export_json(city_data, path=BUILDING_JSON):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(city_data, file, ensure_ascii=False, indent=2)
    return path


def export_building_csv(city_data, path=BUILDING_CSV):
    fieldnames = [
        "id",
        "x",
        "y",
        "z",
        "width",
        "depth",
        "height",
        "floor_count",
        "density",
        "type",
        "roof",
        "is_tower",
        "macro_x",
        "macro_y",
        "micro_x",
        "micro_y",
        "parcel_id",
        "footprint_cells_x",
        "footprint_cells_y",
        "source_cell_count",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(city_data["buildings"])
    return path


def export_tree_csv(city_data, path=TREE_CSV):
    return level2.export_tree_csv(city_data, path)


def export_micro_svg(city_data, path=MICRO_SVG):
    return level2.export_micro_svg(city_data, path)


def main():
    source_data = load_scale_a_data()
    spatial_cell_model = source_data.get("metadata", {}).get("spatial_cell_model", "")
    is_parcel_mode = str(spatial_cell_model).startswith("road_") and "parcel" in str(spatial_cell_model)
    merged_buildings = merge_buildings(source_data)
    merged_data = {
        "metadata": dict(source_data["metadata"]),
        "buildings": merged_buildings,
        "trees": source_data["trees"],
        "micro_cells": source_data["micro_cells"],
        "parcels": source_data.get("parcels", []),
        "road_graph": source_data.get("road_graph"),
        "road_grid_segments": source_data.get("road_grid_segments", []),
    }
    merged_data["metadata"]["scale_scheme"] = "scaleA_mergeB"
    merged_data["metadata"]["merge_shapes"] = MERGE_SHAPES
    if is_parcel_mode:
        merged_data["metadata"]["description"] = (
            "Road-first parcel-bounded micro CA output using scale scheme A plus parcel-safe merge scheme B: "
            "adjacent building micro-cells are merged only when they remain inside the same parcel."
        )
    else:
        merged_data["metadata"]["description"] = (
            "Level-2 meso CA output using scale scheme A plus merge scheme B: "
            "adjacent building micro-cells are merged into 2x2, 3x1, 2x3, and related rectangular blocks."
        )

    json_path = export_json(merged_data)
    building_csv_path = export_building_csv(merged_data)
    tree_csv_path = export_tree_csv(merged_data)
    svg_path = export_micro_svg(merged_data)

    print("Generated level-2 scaleA + mergeB data.")
    print(f"Buildings before merge: {len(source_data['buildings'])}")
    print(f"Buildings after merge: {len(merged_data['buildings'])}")
    print(f"Parcels: {len(merged_data.get('parcels', []))}")
    print(f"Trees: {len(merged_data['trees'])}")
    print(f"JSON saved to: {json_path}")
    print(f"Building CSV saved to: {building_csv_path}")
    print(f"Tree CSV saved to: {tree_csv_path}")
    print(f"Micro SVG saved to: {svg_path}")


if __name__ == "__main__":
    main()
