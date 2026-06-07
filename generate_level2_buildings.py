import csv
import json
import math
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ca_level2_rules as rules
import generate_city_grid as base


OUTPUT_DIR = SCRIPT_DIR / "output"
SOURCE_MACRO_JSON = OUTPUT_DIR / "city_grid_30x30_scheme2.json"
BUILDING_JSON = OUTPUT_DIR / "city_buildings_scheme2.json"
BUILDING_CSV = OUTPUT_DIR / "city_buildings_scheme2.csv"
TREE_CSV = OUTPUT_DIR / "city_trees_scheme2.csv"
MICRO_SVG = OUTPUT_DIR / "meso_ca_level2_180x180_scheme2.svg"

MICRO_GRID_SIZE = rules.MICRO_GRID_SIZE
FLOOR_HEIGHT = 0.32
BUILDING_FOOTPRINT_SCALE = 0.86
TREE_BASE_SCALE = 0.10


def load_macro_grid(path=SOURCE_MACRO_JSON):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_world_position(macro_cell, mx, my, micro_grid_size=MICRO_GRID_SIZE):
    local_x = (mx + 0.5) / micro_grid_size
    local_y = (my + 0.5) / micro_grid_size
    world_x = macro_cell["x"] + local_x
    world_y = macro_cell["y"] + local_y
    world_z = base.get_height(world_x, world_y, base.GRID_SIZE)
    return world_x, world_y, world_z


def roof_for_building(macro_cell, micro_state, mx, my):
    if micro_state == rules.MICRO_TOWER:
        return "flat"

    value = rules.stable_noise(
        macro_cell["x"] * MICRO_GRID_SIZE + mx,
        macro_cell["y"] * MICRO_GRID_SIZE + my,
        seed=611,
    )
    return "gable" if value < 0.72 else "hip"


def create_building_record(building_id, macro_cell, mx, my, micro_state):
    world_x, world_y, world_z = get_world_position(macro_cell, mx, my)
    floor_count = rules.get_floor_count(macro_cell, micro_state, mx, my)
    micro_size = base.CELL_SIZE / MICRO_GRID_SIZE
    is_tower = micro_state == rules.MICRO_TOWER
    footprint_scale = 0.66 if is_tower else BUILDING_FOOTPRINT_SCALE
    building_type = "tower" if is_tower else "house"

    return {
        "id": building_id,
        "x": round(world_x, 4),
        "y": round(world_y, 4),
        "z": round(world_z, 4),
        "width": round(micro_size * footprint_scale, 4),
        "depth": round(micro_size * footprint_scale, 4),
        "height": round(floor_count * FLOOR_HEIGHT, 4),
        "floor_count": floor_count,
        "density": macro_cell["density"],
        "type": building_type,
        "roof": roof_for_building(macro_cell, micro_state, mx, my),
        "is_tower": is_tower,
        "macro_x": macro_cell["x"],
        "macro_y": macro_cell["y"],
        "micro_x": mx,
        "micro_y": my,
    }


def create_tree_record(macro_cell, mx, my):
    world_x, world_y, world_z = get_world_position(macro_cell, mx, my)
    noise = rules.stable_noise(
        macro_cell["x"] * MICRO_GRID_SIZE + mx,
        macro_cell["y"] * MICRO_GRID_SIZE + my,
        seed=907,
    )

    return {
        "x": round(world_x, 4),
        "y": round(world_y, 4),
        "z": round(world_z, 4),
        "scale": round(TREE_BASE_SCALE * (0.75 + noise * 0.75), 4),
        "macro_x": macro_cell["x"],
        "macro_y": macro_cell["y"],
        "micro_x": mx,
        "micro_y": my,
    }


def generate_level2_data(macro_grid):
    buildings = []
    trees = []
    micro_cells = []
    building_id = 1

    for macro_cell in macro_grid["cells"]:
        micro_states = rules.generate_micro_layout(macro_cell, MICRO_GRID_SIZE)

        for my in range(MICRO_GRID_SIZE):
            for mx in range(MICRO_GRID_SIZE):
                micro_state = micro_states[my][mx]
                world_x, world_y, world_z = get_world_position(macro_cell, mx, my)
                micro_cells.append(
                    {
                        "macro_x": macro_cell["x"],
                        "macro_y": macro_cell["y"],
                        "micro_x": mx,
                        "micro_y": my,
                        "x": round(world_x, 4),
                        "y": round(world_y, 4),
                        "z": round(world_z, 4),
                        "state": micro_state,
                    }
                )

                if micro_state in (rules.MICRO_BUILDING, rules.MICRO_TOWER):
                    buildings.append(create_building_record(building_id, macro_cell, mx, my, micro_state))
                    building_id += 1
                elif micro_state == rules.MICRO_TREE:
                    trees.append(create_tree_record(macro_cell, mx, my))

    return {
        "metadata": {
            "source_macro_file": str(SOURCE_MACRO_JSON),
            "macro_scheme": macro_grid["metadata"].get("scheme", "scheme2"),
            "micro_grid_size": MICRO_GRID_SIZE,
            "micro_ca_iterations": rules.MICRO_CA_ITERATIONS,
            "micro_random_seed": rules.MICRO_RANDOM_SEED,
            "floor_height": FLOOR_HEIGHT,
            "description": "Level-2 meso CA output: building bounding boxes and tree points generated inside each macro cell.",
        },
        "buildings": buildings,
        "trees": trees,
        "micro_cells": micro_cells,
    }


def export_building_json(city_data, path=BUILDING_JSON):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(city_data, file, ensure_ascii=False, indent=2)
    return path


def export_building_csv(city_data, path=BUILDING_CSV):
    path.parent.mkdir(parents=True, exist_ok=True)
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
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(city_data["buildings"])
    return path


def export_tree_csv(city_data, path=TREE_CSV):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["x", "y", "z", "scale", "macro_x", "macro_y", "micro_x", "micro_y"]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(city_data["trees"])
    return path


def export_micro_svg(city_data, path=MICRO_SVG):
    path.parent.mkdir(parents=True, exist_ok=True)
    grid_size = base.GRID_SIZE * MICRO_GRID_SIZE
    cell_px = 4
    margin = 18
    legend_width = 210
    width = margin * 2 + grid_size * cell_px + legend_width
    height = margin * 2 + grid_size * cell_px
    labels = {
        rules.MICRO_EMPTY: "0 empty",
        rules.MICRO_BUILDING: "1 building",
        rules.MICRO_COURTYARD: "2 courtyard",
        rules.MICRO_PATH: "3 path",
        rules.MICRO_TREE: "4 tree",
        rules.MICRO_TOWER: "5 tower",
    }

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f5ef"/>',
        '<text x="18" y="14" font-family="Arial" font-size="12" font-weight="700" fill="#222">Meso CA Level 2 - 180x180 micro grid</text>',
    ]

    for micro_cell in city_data["micro_cells"]:
        gx = micro_cell["macro_x"] * MICRO_GRID_SIZE + micro_cell["micro_x"]
        gy = micro_cell["macro_y"] * MICRO_GRID_SIZE + micro_cell["micro_y"]
        state = micro_cell["state"]
        x = margin + gx * cell_px
        y = margin + gy * cell_px
        lines.append(
            f'<rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" fill="{rules.MICRO_COLORS[state]}" stroke="#4b4b4b" stroke-width="0.12"/>'
        )

    legend_x = margin + grid_size * cell_px + 30
    legend_y = margin + 26
    lines.append(f'<text x="{legend_x}" y="{legend_y - 12}" font-family="Arial" font-size="12" font-weight="700" fill="#222">Legend</text>')

    for index, state in enumerate([0, 1, 2, 3, 4, 5]):
        y = legend_y + index * 28
        lines.append(f'<rect x="{legend_x}" y="{y}" width="18" height="18" fill="{rules.MICRO_COLORS[state]}" stroke="#222" stroke-width="0.5"/>')
        lines.append(f'<text x="{legend_x + 28}" y="{y + 13}" font-family="Arial" font-size="11" fill="#222">{labels[state]}</text>')

    lines.append(f'<text x="{legend_x}" y="{legend_y + 200}" font-family="Arial" font-size="10" fill="#555">Buildings: {len(city_data["buildings"])}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 216}" font-family="Arial" font-size="10" fill="#555">Trees: {len(city_data["trees"])}</text>')
    lines.append("</svg>")

    with path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))
    return path


def main():
    macro_grid = load_macro_grid()
    city_data = generate_level2_data(macro_grid)
    json_path = export_building_json(city_data)
    building_csv_path = export_building_csv(city_data)
    tree_csv_path = export_tree_csv(city_data)
    svg_path = export_micro_svg(city_data)

    print("Generated level-2 meso CA data.")
    print(f"Buildings: {len(city_data['buildings'])}")
    print(f"Trees: {len(city_data['trees'])}")
    print(f"JSON saved to: {json_path}")
    print(f"Building CSV saved to: {building_csv_path}")
    print(f"Tree CSV saved to: {tree_csv_path}")
    print(f"Micro SVG saved to: {svg_path}")


if __name__ == "__main__":
    main()
