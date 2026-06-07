import csv
import json
import math
import random
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_city_grid as base


GRID_SIZE = base.GRID_SIZE
OUTPUT_DIR = Path(__file__).parent / "output"
SCHEME_NAME = "scheme2"

RANDOM_SEED = 84
CA_ITERATIONS = 7
SMOOTHING_ITERATIONS = 2
SEED_COUNTS = {
    "main_core": 1,
    "sub_core": 7,
    "medium": 26,
    "low": 50,
    "edge_forest": 36,
    "inner_forest": 28,
    "plaza": 12,
}


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def hash_noise(x, y, seed=RANDOM_SEED):
    value = math.sin(x * 12.9898 + y * 78.233 + seed * 37.719) * 43758.5453
    return value - math.floor(value)


def smooth_noise(x, y, seed=RANDOM_SEED):
    total = 0.0
    weight_total = 0.0

    for dy in range(-1, 2):
        for dx in range(-1, 2):
            weight = 2.0 if dx == 0 and dy == 0 else 1.0
            total += hash_noise(x + dx, y + dy, seed) * weight
            weight_total += weight

    coarse_x = math.floor(x / 3)
    coarse_y = math.floor(y / 3)
    coarse = hash_noise(coarse_x, coarse_y, seed + 11)
    fine = total / weight_total
    return round(clamp(0.62 * fine + 0.38 * coarse), 3)


def calculate_potentials(cell, grid_size=GRID_SIZE):
    center_score = base.get_center_score(cell["x"], cell["y"], grid_size)
    edge_score = base.get_edge_score(cell["x"], cell["y"], grid_size)
    noise_value = smooth_noise(cell["x"], cell["y"])
    accessibility = cell["accessibility"]

    density_potential = clamp(
        accessibility * 0.45
        + center_score * 0.30
        + noise_value * 0.25
    )
    green_potential = clamp(
        (1.0 - accessibility) * 0.32
        + edge_score * 0.28
        + noise_value * 0.40
    )
    open_space_potential = clamp(
        noise_value * 0.48
        + (1.0 - abs(density_potential - 0.58)) * 0.32
        + green_potential * 0.20
    )

    cell["center_score"] = round(center_score, 3)
    cell["noise_value"] = noise_value
    cell["density_potential"] = round(density_potential, 3)
    cell["green_potential"] = round(green_potential, 3)
    cell["open_space_potential"] = round(open_space_potential, 3)


def generate_base_cells(grid_size=GRID_SIZE):
    height_map = base.generate_height_map(grid_size)
    access_guides = base.generate_access_guides(grid_size)
    cells = []

    for y in range(grid_size):
        for x in range(grid_size):
            height = height_map[y][x]
            slope = base.calculate_slope(height_map, x, y, grid_size)
            access_attributes = base.get_access_attributes(x, y, access_guides, grid_size)
            buildable = slope <= base.SLOPE_BUILDABLE_LIMIT
            cell = {
                "x": x,
                "y": y,
                "height": height,
                "slope": slope,
                "buildable": buildable,
                "distance_to_road": access_attributes["distance_to_road"],
                "accessibility": access_attributes["accessibility"],
                "state": base.STATE_FOREST,
                "density": "none",
                "type": "forest",
                "is_tower": False,
            }
            calculate_potentials(cell, grid_size)
            cells.append(cell)

    return cells


def select_ranked(cells, available, count, score_func, rng, min_distance=0, selected_points=None):
    selected_points = selected_points or []
    scored = []

    for index in available:
        cell = cells[index]
        if min_distance:
            too_close = any(
                math.hypot(cell["x"] - px, cell["y"] - py) < min_distance
                for px, py in selected_points
            )
            if too_close:
                continue
        scored.append((score_func(cell) + rng.uniform(-0.08, 0.08), index))

    scored.sort(reverse=True)
    selected = [index for _, index in scored[:count]]

    for index in selected:
        available.remove(index)

    return selected


def generate_initial_states(cells, grid_size=GRID_SIZE):
    rng = random.Random(RANDOM_SEED)
    states = [[base.STATE_FOREST for _ in range(grid_size)] for _ in range(grid_size)]
    available = {index for index, cell in enumerate(cells) if cell["buildable"]}

    main_core = select_ranked(
        cells,
        available,
        SEED_COUNTS["main_core"],
        lambda cell: cell["density_potential"] * 1.4 + cell["center_score"],
        rng,
    )
    core_points = [(cells[index]["x"], cells[index]["y"]) for index in main_core]

    sub_cores = select_ranked(
        cells,
        available,
        SEED_COUNTS["sub_core"],
        lambda cell: cell["density_potential"] * 1.2 + cell["noise_value"] * 0.55,
        rng,
        min_distance=5.0,
        selected_points=core_points,
    )
    core_points.extend((cells[index]["x"], cells[index]["y"]) for index in sub_cores)

    medium = select_ranked(
        cells,
        available,
        SEED_COUNTS["medium"],
        lambda cell: cell["density_potential"] + nearest_core_score(cell, core_points) * 0.45,
        rng,
    )
    low = select_ranked(
        cells,
        available,
        SEED_COUNTS["low"],
        lambda cell: 1.0 - abs(cell["density_potential"] - 0.48) + cell["green_potential"] * 0.18,
        rng,
    )
    edge_forest = select_ranked(
        cells,
        available,
        SEED_COUNTS["edge_forest"],
        lambda cell: base.get_edge_score(cell["x"], cell["y"], grid_size) + cell["green_potential"],
        rng,
    )
    inner_forest = select_ranked(
        cells,
        available,
        SEED_COUNTS["inner_forest"],
        lambda cell: internal_green_score(cell, grid_size),
        rng,
        min_distance=2.0,
        selected_points=[(cells[index]["x"], cells[index]["y"]) for index in edge_forest],
    )
    plaza = select_ranked(
        cells,
        available,
        SEED_COUNTS["plaza"],
        lambda cell: cell["open_space_potential"] + nearest_core_score(cell, core_points) * 0.28,
        rng,
        min_distance=3.0,
    )

    for index in main_core + sub_cores:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = base.STATE_HIGH
    for index in medium:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = base.STATE_MEDIUM
    for index in low:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = base.STATE_LOW
    for index in edge_forest + inner_forest:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = base.STATE_FOREST
    for index in plaza:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = base.STATE_PLAZA

    return states


def nearest_core_score(cell, core_points):
    if not core_points:
        return 0.0

    nearest = min(
        math.hypot(cell["x"] - core_x, cell["y"] - core_y)
        for core_x, core_y in core_points
    )
    return clamp(1.0 - nearest / 10.0)


def internal_green_score(cell, grid_size=GRID_SIZE):
    edge_score = base.get_edge_score(cell["x"], cell["y"], grid_size)
    not_edge = 1.0 - edge_score
    density_window = 1.0 - abs(cell["density_potential"] - 0.48)
    return cell["green_potential"] * 1.2 + not_edge * 0.65 + density_window * 0.35


def choose_next_state(cell, neighbor_counts, current_state, rng, grid_size=GRID_SIZE):
    if not cell["buildable"]:
        return base.STATE_FOREST

    high_neighbors = neighbor_counts[base.STATE_HIGH] + neighbor_counts[base.STATE_TOWER]
    medium_neighbors = neighbor_counts[base.STATE_MEDIUM]
    low_neighbors = neighbor_counts[base.STATE_LOW]
    forest_neighbors = neighbor_counts[base.STATE_FOREST]
    plaza_neighbors = neighbor_counts[base.STATE_PLAZA]
    urban_neighbors = high_neighbors + medium_neighbors + low_neighbors

    density = cell["density_potential"]
    green = cell["green_potential"]
    open_space = cell["open_space_potential"]

    if current_state == base.STATE_HIGH and density > 0.55 and green < 0.78 and rng.random() < 0.72:
        return base.STATE_HIGH
    if current_state == base.STATE_MEDIUM and high_neighbors >= 1 and density > 0.58 and rng.random() < 0.34:
        return base.STATE_HIGH
    if high_neighbors >= 6 and open_space > 0.45 and rng.random() < 0.42:
        return base.STATE_PLAZA
    if urban_neighbors >= 5 and open_space > 0.72 and plaza_neighbors < 2 and rng.random() < 0.12:
        return base.STATE_PLAZA
    if green > 0.70 and high_neighbors < 1 and urban_neighbors < 5 and rng.random() < 0.30:
        return base.STATE_FOREST
    if forest_neighbors >= 3 and green > 0.58 and high_neighbors < 1 and rng.random() < 0.26:
        return base.STATE_FOREST
    if high_neighbors >= 1 and density > 0.68 and rng.random() < 0.60:
        return base.STATE_HIGH
    if high_neighbors >= 2 and density > 0.58 and rng.random() < 0.62:
        return base.STATE_HIGH
    if high_neighbors + medium_neighbors >= 2 and density > 0.42 and rng.random() < 0.70:
        return base.STATE_MEDIUM

    scores = {
        base.STATE_FOREST: 0.42 + forest_neighbors * 0.20 + green * 1.35 - high_neighbors * 0.12,
        base.STATE_LOW: 0.95 + low_neighbors * 0.34 + forest_neighbors * 0.10 + (1.0 - abs(density - 0.45)) * 0.95,
        base.STATE_MEDIUM: 0.62 + medium_neighbors * 0.46 + high_neighbors * 0.26 + density * 1.24,
        base.STATE_HIGH: 0.30 + high_neighbors * 0.66 + medium_neighbors * 0.40 + density * 1.75,
        base.STATE_PLAZA: -0.70 + open_space * 0.82 + high_neighbors * 0.12 + medium_neighbors * 0.08 - plaza_neighbors * 0.72,
    }

    if density < 0.56:
        scores[base.STATE_HIGH] -= 0.35
    if green > 0.64:
        scores[base.STATE_HIGH] -= 0.45
        scores[base.STATE_FOREST] += 0.28
    if plaza_neighbors >= 2:
        scores[base.STATE_PLAZA] -= 1.1

    for state in scores:
        scores[state] += rng.uniform(-0.18, 0.18)

    return max(scores, key=scores.get)


def evolve_states(cells, states, grid_size=GRID_SIZE):
    rng = random.Random(RANDOM_SEED + 100)

    for _ in range(CA_ITERATIONS):
        next_states = [[base.STATE_FOREST for _ in range(grid_size)] for _ in range(grid_size)]

        for y in range(grid_size):
            for x in range(grid_size):
                cell = cells[base.get_cell_index(x, y, grid_size)]
                neighbor_counts = base.count_neighbor_states(states, x, y, grid_size)
                next_states[y][x] = choose_next_state(cell, neighbor_counts, states[y][x], rng, grid_size)

        states = next_states

    return states


def smooth_states(cells, states, grid_size=GRID_SIZE):
    for _ in range(SMOOTHING_ITERATIONS):
        next_states = [row[:] for row in states]

        for y in range(grid_size):
            for x in range(grid_size):
                cell = cells[base.get_cell_index(x, y, grid_size)]
                neighbor_counts = base.count_neighbor_states(states, x, y, grid_size)
                state = states[y][x]
                urban_neighbors = (
                    neighbor_counts[base.STATE_LOW]
                    + neighbor_counts[base.STATE_MEDIUM]
                    + neighbor_counts[base.STATE_HIGH]
                    + neighbor_counts[base.STATE_TOWER]
                )

                if not cell["buildable"]:
                    next_states[y][x] = base.STATE_FOREST
                elif state == base.STATE_FOREST and urban_neighbors >= 6:
                    next_states[y][x] = base.STATE_LOW if cell["green_potential"] < 0.62 else base.STATE_PLAZA
                elif state == base.STATE_PLAZA and neighbor_counts[base.STATE_PLAZA] >= 3:
                    next_states[y][x] = base.STATE_LOW
                elif state == base.STATE_HIGH and urban_neighbors <= 2:
                    next_states[y][x] = base.STATE_MEDIUM

        states = next_states

    return states


def apply_green_patches(cells, states, grid_size=GRID_SIZE):
    for cell in cells:
        x = cell["x"]
        y = cell["y"]
        state = states[y][x]
        if state in (base.STATE_HIGH, base.STATE_TOWER, base.STATE_PLAZA):
            continue

        edge_score = base.get_edge_score(x, y, grid_size)
        if cell["green_potential"] > 0.68 and cell["density_potential"] < 0.62:
            states[y][x] = base.STATE_FOREST
        elif edge_score > 0.82 and cell["accessibility"] < 0.48:
            states[y][x] = base.STATE_FOREST

    return states


def apply_towers(cells, states, grid_size=GRID_SIZE, max_towers=8):
    candidates = []

    for y in range(grid_size):
        for x in range(grid_size):
            if states[y][x] != base.STATE_HIGH:
                continue

            cell = cells[base.get_cell_index(x, y, grid_size)]
            neighbor_counts = base.count_neighbor_states(states, x, y, grid_size)
            score = (
                cell["density_potential"] * 1.1
                + cell["accessibility"] * 0.55
                + neighbor_counts[base.STATE_HIGH] * 0.18
                + neighbor_counts[base.STATE_MEDIUM] * 0.08
            )
            candidates.append((score, x, y))

    candidates.sort(reverse=True)
    tower_positions = []

    for _, x, y in candidates:
        if len(tower_positions) >= max_towers:
            break
        if all(math.hypot(x - tx, y - ty) >= 4.0 for tx, ty in tower_positions):
            tower_positions.append((x, y))
            states[y][x] = base.STATE_TOWER

    return states


def apply_outputs(cells, states):
    for cell in cells:
        state = states[cell["y"]][cell["x"]]
        output = base.STATE_OUTPUT[state]
        cell["state"] = state
        cell["density"] = output["density"]
        cell["type"] = output["type"]
        cell["is_tower"] = output["is_tower"]


def generate_city_grid_scheme2(grid_size=GRID_SIZE):
    cells = generate_base_cells(grid_size)
    states = generate_initial_states(cells, grid_size)
    states = evolve_states(cells, states, grid_size)
    states = smooth_states(cells, states, grid_size)
    states = apply_green_patches(cells, states, grid_size)
    states = apply_towers(cells, states, grid_size)
    apply_outputs(cells, states)

    return {
        "metadata": {
            "scheme": SCHEME_NAME,
            "grid_size": grid_size,
            "cell_size": base.CELL_SIZE,
            "slope_buildable_limit": base.SLOPE_BUILDABLE_LIMIT,
            "ca_random_seed": RANDOM_SEED,
            "ca_iterations": CA_ITERATIONS,
            "smoothing_iterations": SMOOTHING_ITERATIONS,
            "seed_counts": SEED_COUNTS,
            "description": "Scheme 2 macro CA with inner forest patches, local plazas, stable noise, and multiple density cores.",
        },
        "macro_states": states,
        "cells": cells,
    }


def export_json(city_grid, output_dir=OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "city_grid_30x30_scheme2.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(city_grid, file, ensure_ascii=False, indent=2)

    return output_path


def export_csv(city_grid, output_dir=OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "city_grid_30x30_scheme2.csv"
    fieldnames = [
        "x",
        "y",
        "height",
        "slope",
        "buildable",
        "distance_to_road",
        "accessibility",
        "center_score",
        "noise_value",
        "density_potential",
        "green_potential",
        "open_space_potential",
        "state",
        "density",
        "type",
        "is_tower",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(city_grid["cells"])

    return output_path


def export_svg(city_grid, output_dir=OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "macro_ca_level1_30x30_scheme2.svg"

    grid_size = city_grid["metadata"]["grid_size"]
    cell_px = 24
    margin = 24
    legend_width = 250
    width = margin * 2 + grid_size * cell_px + legend_width
    height = margin * 2 + grid_size * cell_px
    labels = {
        base.STATE_FOREST: "0 forest / green",
        base.STATE_LOW: "1 low",
        base.STATE_MEDIUM: "2 medium",
        base.STATE_HIGH: "3 high",
        base.STATE_TOWER: "4 tower",
        base.STATE_PLAZA: "5 plaza",
    }

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f5ef"/>',
        '<text x="24" y="18" font-family="Arial" font-size="14" font-weight="700" fill="#222">Macro CA Level 1 - Scheme 2</text>',
    ]

    for cell in city_grid["cells"]:
        x = margin + cell["x"] * cell_px
        y = margin + cell["y"] * cell_px
        state = cell["state"]
        lines.append(
            f'<rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" fill="{base.STATE_COLORS[state]}" stroke="#2b2b2b" stroke-width="0.45"/>'
        )
        lines.append(
            f'<text x="{x + cell_px / 2}" y="{y + cell_px / 2 + 4}" text-anchor="middle" font-family="Arial" font-size="10" fill="#1f1f1f">{state}</text>'
        )

    legend_x = margin + grid_size * cell_px + 34
    legend_y = margin + 28
    lines.append(f'<text x="{legend_x}" y="{legend_y - 14}" font-family="Arial" font-size="13" font-weight="700" fill="#222">Legend</text>')

    for offset, state in enumerate([base.STATE_FOREST, base.STATE_LOW, base.STATE_MEDIUM, base.STATE_HIGH, base.STATE_TOWER, base.STATE_PLAZA]):
        item_y = legend_y + offset * 32
        lines.append(f'<rect x="{legend_x}" y="{item_y}" width="22" height="22" fill="{base.STATE_COLORS[state]}" stroke="#222" stroke-width="0.6"/>')
        lines.append(f'<text x="{legend_x + 34}" y="{item_y + 15}" font-family="Arial" font-size="12" fill="#222">{labels[state]}</text>')

    lines.append(f'<text x="{legend_x}" y="{legend_y + 225}" font-family="Arial" font-size="11" fill="#555">Seed total: {sum(SEED_COUNTS.values())}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 244}" font-family="Arial" font-size="11" fill="#555">Noise + inner green + local plaza</text>')
    lines.append("</svg>")

    with output_path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    return output_path


def save_blender_scene(output_dir=OUTPUT_DIR):
    try:
        import bpy
    except ImportError:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "city_grid_30x30_scheme2.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    return output_path


def main():
    city_grid = generate_city_grid_scheme2(GRID_SIZE)
    json_path = export_json(city_grid)
    csv_path = export_csv(city_grid)
    svg_path = export_svg(city_grid)
    base.create_blender_grid(city_grid)
    blend_path = save_blender_scene()

    print("Generated scheme 2 macro CA grid.")
    print(f"JSON saved to: {json_path}")
    print(f"CSV saved to: {csv_path}")
    print(f"SVG saved to: {svg_path}")
    if blend_path:
        print(f"Blend scene saved to: {blend_path}")


if __name__ == "__main__":
    main()
