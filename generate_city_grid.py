import csv
import json
import math
import random
from pathlib import Path


GRID_SIZE = 15
CELL_SIZE = 1.0
SLOPE_BUILDABLE_LIMIT = 0.45
CA_RANDOM_SEED = 42
CA_ITERATIONS = 7
SMOOTHING_ITERATIONS = 2
SEED_COUNTS = {
    "high": 8,
    "medium": 24,
    "low": 45,
    "forest": 40,
    "plaza": 3,
}
BASE_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
OUTPUT_DIR = BASE_DIR / "output"

STATE_FOREST = 0
STATE_LOW = 1
STATE_MEDIUM = 2
STATE_HIGH = 3
STATE_TOWER = 4
STATE_PLAZA = 5

STATE_OUTPUT = {
    STATE_FOREST: {"density": "none", "type": "forest", "is_tower": False},
    STATE_LOW: {"density": "low", "type": "residential_low", "is_tower": False},
    STATE_MEDIUM: {"density": "medium", "type": "residential_medium", "is_tower": False},
    STATE_HIGH: {"density": "high", "type": "urban_high", "is_tower": False},
    STATE_TOWER: {"density": "high", "type": "tower_candidate", "is_tower": True},
    STATE_PLAZA: {"density": "none", "type": "plaza", "is_tower": False},
}

STATE_COLORS = {
    STATE_FOREST: "#7c9a72",
    STATE_LOW: "#d6d3bd",
    STATE_MEDIUM: "#bfc4d0",
    STATE_HIGH: "#8f9bb3",
    STATE_TOWER: "#d7b06a",
    STATE_PLAZA: "#eee6cf",
}


def get_height(x, y, grid_size=GRID_SIZE):
    """Generate a simple deterministic terrain height for the first version."""
    cx = (grid_size - 1) / 2
    cy = (grid_size - 1) / 2
    dx = (x - cx) / grid_size
    dy = (y - cy) / grid_size

    hill = 2.0 * math.exp(-7.0 * (dx * dx + dy * dy))
    wave = 0.25 * math.sin(x * 0.25) + 0.2 * math.cos(y * 0.22)
    return round(hill + wave, 3)


def generate_access_guides(grid_size=GRID_SIZE):
    """Generate hidden accessibility guides without creating visible roads."""
    center = grid_size / 2

    main_guide = {
        "id": 1,
        "level": "primary",
        "points": [
            [1.5, grid_size - 4.0],
            [7.0, grid_size - 7.5],
            [center - 2.0, center + 1.5],
            [center + 4.0, center - 2.0],
            [grid_size - 2.0, 4.5],
        ],
    }

    secondary_guides = [
        {
            "id": 2,
            "level": "secondary",
            "points": [
                [center - 2.0, center + 1.5],
                [center - 7.5, center + 5.5],
                [4.5, center + 5.0],
            ],
        },
        {
            "id": 3,
            "level": "secondary",
            "points": [
                [center + 4.0, center - 2.0],
                [center + 7.5, center + 2.5],
                [grid_size - 4.0, center + 6.5],
            ],
        },
        {
            "id": 4,
            "level": "secondary",
            "points": [
                [7.0, grid_size - 7.5],
                [9.5, center + 1.0],
                [8.0, 5.0],
            ],
        },
    ]

    return [main_guide] + secondary_guides


def get_distance_to_segment(px, py, ax, ay, bx, by):
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    segment_length_sq = abx * abx + aby * aby

    if segment_length_sq == 0:
        return math.hypot(px - ax, py - ay)

    t = max(0.0, min(1.0, (apx * abx + apy * aby) / segment_length_sq))
    closest_x = ax + t * abx
    closest_y = ay + t * aby
    return math.hypot(px - closest_x, py - closest_y)


def get_distance_to_polyline(px, py, points):
    distances = []

    for index in range(len(points) - 1):
        ax, ay = points[index]
        bx, by = points[index + 1]
        distances.append(get_distance_to_segment(px, py, ax, ay, bx, by))

    return min(distances) if distances else math.inf


def get_access_attributes(x, y, access_guides, grid_size=GRID_SIZE):
    cell_center_x = x + 0.5
    cell_center_y = y + 0.5
    nearest_distance = math.inf

    for guide in access_guides:
        centerline_distance = get_distance_to_polyline(
            cell_center_x,
            cell_center_y,
            guide["points"],
        )
        nearest_distance = min(nearest_distance, centerline_distance)

    center = (grid_size - 1) / 2
    center_distance = math.hypot(cell_center_x - center, cell_center_y - center)
    max_center_distance = math.hypot(center, center)
    center_score = 1.0 - min(1.0, center_distance / max_center_distance)
    guide_score = max(0.0, 1.0 - nearest_distance / (grid_size * 0.45))
    accessibility = 0.65 * guide_score + 0.35 * center_score

    return {
        "distance_to_road": round(nearest_distance, 3),
        "accessibility": round(accessibility, 3),
    }


def calculate_slope(height_map, x, y, grid_size=GRID_SIZE):
    current = height_map[y][x]
    neighbor_diffs = []

    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        if 0 <= nx < grid_size and 0 <= ny < grid_size:
            neighbor_diffs.append(abs(current - height_map[ny][nx]))

    if not neighbor_diffs:
        return 0.0

    return round(max(neighbor_diffs), 3)


def generate_height_map(grid_size=GRID_SIZE):
    return [
        [get_height(x, y, grid_size) for x in range(grid_size)]
        for y in range(grid_size)
    ]


def get_cell_index(x, y, grid_size=GRID_SIZE):
    return y * grid_size + x


def get_neighbors(x, y, grid_size=GRID_SIZE):
    neighbors = []

    for ny in range(y - 1, y + 2):
        for nx in range(x - 1, x + 2):
            if nx == x and ny == y:
                continue
            if 0 <= nx < grid_size and 0 <= ny < grid_size:
                neighbors.append((nx, ny))

    return neighbors


def get_center_score(x, y, grid_size=GRID_SIZE):
    center = (grid_size - 1) / 2
    distance = math.hypot((x + 0.5) - center, (y + 0.5) - center)
    max_distance = math.hypot(center, center)
    return 1.0 - min(1.0, distance / max_distance)


def get_edge_score(x, y, grid_size=GRID_SIZE):
    edge_distance = min(x, y, grid_size - 1 - x, grid_size - 1 - y)
    return 1.0 - min(1.0, edge_distance / (grid_size * 0.32))


def select_seed_cells(cells, available, count, score_func, rng):
    scored_cells = []

    for index in available:
        cell = cells[index]
        jitter = rng.uniform(-0.08, 0.08)
        scored_cells.append((score_func(cell) + jitter, index))

    scored_cells.sort(reverse=True)
    selected = [index for _, index in scored_cells[:count]]

    for index in selected:
        available.remove(index)

    return selected


def generate_initial_macro_states(cells, grid_size=GRID_SIZE, seed=CA_RANDOM_SEED):
    rng = random.Random(seed)
    states = [[STATE_FOREST for _ in range(grid_size)] for _ in range(grid_size)]
    available = {index for index, cell in enumerate(cells) if cell["buildable"]}

    high_seeds = select_seed_cells(
        cells,
        available,
        SEED_COUNTS["high"],
        lambda cell: cell["accessibility"] * 1.4 + get_center_score(cell["x"], cell["y"], grid_size),
        rng,
    )
    medium_seeds = select_seed_cells(
        cells,
        available,
        SEED_COUNTS["medium"],
        lambda cell: cell["accessibility"] + get_center_score(cell["x"], cell["y"], grid_size) * 0.65,
        rng,
    )
    low_seeds = select_seed_cells(
        cells,
        available,
        SEED_COUNTS["low"],
        lambda cell: 1.0 - abs(cell["accessibility"] - 0.5) + rng.uniform(-0.08, 0.08),
        rng,
    )
    forest_seeds = select_seed_cells(
        cells,
        available,
        SEED_COUNTS["forest"],
        lambda cell: get_edge_score(cell["x"], cell["y"], grid_size) + (1.0 - cell["accessibility"]),
        rng,
    )

    plaza_candidates = []
    high_points = [(cells[index]["x"], cells[index]["y"]) for index in high_seeds]
    for index in available:
        cell = cells[index]
        nearest_high = min(
            math.hypot(cell["x"] - high_x, cell["y"] - high_y)
            for high_x, high_y in high_points
        )
        if nearest_high <= 5:
            plaza_candidates.append((cell["accessibility"] - nearest_high * 0.05, index))

    plaza_candidates.sort(reverse=True)
    plaza_seeds = [index for _, index in plaza_candidates[:SEED_COUNTS["plaza"]]]
    for index in plaza_seeds:
        available.remove(index)

    for index in high_seeds:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = STATE_HIGH
    for index in medium_seeds:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = STATE_MEDIUM
    for index in low_seeds:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = STATE_LOW
    for index in forest_seeds:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = STATE_FOREST
    for index in plaza_seeds:
        cell = cells[index]
        states[cell["y"]][cell["x"]] = STATE_PLAZA

    return states


def count_neighbor_states(states, x, y, grid_size=GRID_SIZE):
    counts = {
        STATE_FOREST: 0,
        STATE_LOW: 0,
        STATE_MEDIUM: 0,
        STATE_HIGH: 0,
        STATE_TOWER: 0,
        STATE_PLAZA: 0,
    }

    for nx, ny in get_neighbors(x, y, grid_size):
        counts[states[ny][nx]] += 1

    return counts


def choose_next_state(cell, neighbor_counts, rng, grid_size=GRID_SIZE):
    if not cell["buildable"]:
        return STATE_FOREST

    x = cell["x"]
    y = cell["y"]
    accessibility = cell["accessibility"]
    center_score = get_center_score(x, y, grid_size)
    edge_score = get_edge_score(x, y, grid_size)

    high_neighbors = neighbor_counts[STATE_HIGH] + neighbor_counts[STATE_TOWER]
    medium_neighbors = neighbor_counts[STATE_MEDIUM]
    low_neighbors = neighbor_counts[STATE_LOW]
    forest_neighbors = neighbor_counts[STATE_FOREST]
    plaza_neighbors = neighbor_counts[STATE_PLAZA]

    if high_neighbors >= 6 and rng.random() < 0.45:
        return STATE_PLAZA
    if high_neighbors >= 2 and accessibility > 0.58 and rng.random() < 0.68:
        return STATE_HIGH
    if high_neighbors + medium_neighbors >= 2 and accessibility > 0.42 and rng.random() < 0.78:
        return STATE_MEDIUM
    if edge_score > 0.84 and accessibility < 0.50 and rng.random() < 0.35:
        return STATE_FOREST
    if accessibility < 0.22 and rng.random() < 0.62:
        return STATE_FOREST
    if forest_neighbors >= 6 and accessibility < 0.34 and rng.random() < 0.48:
        return STATE_FOREST
    if plaza_neighbors >= 2 and rng.random() < 0.25:
        return STATE_LOW

    scores = {
        STATE_FOREST: 0.55 + forest_neighbors * 0.18 + (1.0 - accessibility) * 1.0 + edge_score * 0.55,
        STATE_LOW: 1.0 + low_neighbors * 0.38 + forest_neighbors * 0.12 + (1.0 - abs(accessibility - 0.46)) * 1.0,
        STATE_MEDIUM: 0.75 + medium_neighbors * 0.50 + high_neighbors * 0.30 + accessibility * 1.45 + center_score * 0.45,
        STATE_HIGH: 0.10 + high_neighbors * 0.55 + medium_neighbors * 0.34 + accessibility * 1.55 + center_score * 0.60,
        STATE_PLAZA: -0.35 + high_neighbors * 0.24 + medium_neighbors * 0.10,
    }

    if accessibility < 0.55:
        scores[STATE_HIGH] -= 0.45
    if accessibility < 0.35:
        scores[STATE_MEDIUM] -= 0.35
        scores[STATE_HIGH] -= 0.65
    if edge_score > 0.7:
        scores[STATE_HIGH] -= 0.50
        scores[STATE_FOREST] += 0.35

    for state in scores:
        scores[state] += rng.uniform(-0.16, 0.16)

    return max(scores, key=scores.get)


def evolve_macro_states(cells, states, grid_size=GRID_SIZE, seed=CA_RANDOM_SEED):
    rng = random.Random(seed + 100)

    for _ in range(CA_ITERATIONS):
        next_states = [[STATE_FOREST for _ in range(grid_size)] for _ in range(grid_size)]

        for y in range(grid_size):
            for x in range(grid_size):
                cell = cells[get_cell_index(x, y, grid_size)]
                neighbor_counts = count_neighbor_states(states, x, y, grid_size)
                next_states[y][x] = choose_next_state(cell, neighbor_counts, rng, grid_size)

        states = next_states

    return states


def smooth_macro_states(cells, states, grid_size=GRID_SIZE):
    for _ in range(SMOOTHING_ITERATIONS):
        next_states = [row[:] for row in states]

        for y in range(grid_size):
            for x in range(grid_size):
                cell = cells[get_cell_index(x, y, grid_size)]
                if not cell["buildable"]:
                    next_states[y][x] = STATE_FOREST
                    continue

                current_state = states[y][x]
                neighbor_counts = count_neighbor_states(states, x, y, grid_size)
                urban_neighbors = (
                    neighbor_counts[STATE_LOW]
                    + neighbor_counts[STATE_MEDIUM]
                    + neighbor_counts[STATE_HIGH]
                    + neighbor_counts[STATE_TOWER]
                )

                if current_state == STATE_HIGH and urban_neighbors <= 2:
                    next_states[y][x] = STATE_MEDIUM
                elif current_state == STATE_MEDIUM and urban_neighbors <= 1:
                    next_states[y][x] = STATE_LOW
                elif current_state == STATE_LOW and neighbor_counts[STATE_FOREST] >= 6:
                    next_states[y][x] = STATE_FOREST
                elif current_state == STATE_FOREST and neighbor_counts[STATE_LOW] >= 5:
                    next_states[y][x] = STATE_LOW

        states = next_states

    return states


def apply_forest_boundary(cells, states, grid_size=GRID_SIZE):
    for cell in cells:
        x = cell["x"]
        y = cell["y"]
        state = states[y][x]
        if state in (STATE_HIGH, STATE_TOWER, STATE_PLAZA):
            continue

        edge_score = get_edge_score(x, y, grid_size)
        if edge_score > 0.80 and cell["accessibility"] < 0.50:
            states[y][x] = STATE_FOREST
        elif cell["accessibility"] < 0.25:
            states[y][x] = STATE_FOREST

    return states


def apply_tower_candidates(cells, states, grid_size=GRID_SIZE, max_towers=10):
    candidates = []

    for y in range(grid_size):
        for x in range(grid_size):
            if states[y][x] != STATE_HIGH:
                continue

            cell = cells[get_cell_index(x, y, grid_size)]
            neighbor_counts = count_neighbor_states(states, x, y, grid_size)
            score = (
                cell["accessibility"] * 1.2
                + get_center_score(x, y, grid_size) * 0.8
                + neighbor_counts[STATE_HIGH] * 0.2
                + neighbor_counts[STATE_MEDIUM] * 0.08
            )
            candidates.append((score, x, y))

    candidates.sort(reverse=True)
    tower_positions = []

    for _, x, y in candidates:
        if len(tower_positions) >= max_towers:
            break
        if all(math.hypot(x - tx, y - ty) >= 4.0 for tx, ty in tower_positions):
            tower_positions.append((x, y))
            states[y][x] = STATE_TOWER

    return states


def apply_macro_ca(cells, grid_size=GRID_SIZE):
    states = generate_initial_macro_states(cells, grid_size)
    states = evolve_macro_states(cells, states, grid_size)
    states = smooth_macro_states(cells, states, grid_size)
    states = apply_forest_boundary(cells, states, grid_size)
    states = apply_tower_candidates(cells, states, grid_size)

    for cell in cells:
        state = states[cell["y"]][cell["x"]]
        output = STATE_OUTPUT[state]
        cell["state"] = state
        cell["density"] = output["density"]
        cell["type"] = output["type"]
        cell["is_tower"] = output["is_tower"]

    return states


def generate_city_grid(grid_size=GRID_SIZE):
    height_map = generate_height_map(grid_size)
    access_guides = generate_access_guides(grid_size)
    cells = []

    for y in range(grid_size):
        for x in range(grid_size):
            height = height_map[y][x]
            slope = calculate_slope(height_map, x, y, grid_size)
            access_attributes = get_access_attributes(x, y, access_guides, grid_size)
            buildable = slope <= SLOPE_BUILDABLE_LIMIT

            cells.append(
                {
                    "x": x,
                    "y": y,
                    "height": height,
                    "slope": slope,
                    "buildable": buildable,
                    "distance_to_road": access_attributes["distance_to_road"],
                    "accessibility": access_attributes["accessibility"],
                    "density": "none",
                    "type": "empty" if buildable else "forest",
                    "is_tower": False,
                }
            )

    states = apply_macro_ca(cells, grid_size)

    return {
        "metadata": {
            "grid_size": grid_size,
            "cell_size": CELL_SIZE,
            "slope_buildable_limit": SLOPE_BUILDABLE_LIMIT,
            "ca_random_seed": CA_RANDOM_SEED,
            "ca_iterations": CA_ITERATIONS,
            "smoothing_iterations": SMOOTHING_ITERATIONS,
            "seed_counts": SEED_COUNTS,
            "description": f"Basic {grid_size}x{grid_size} city terrain grid with hidden accessibility field for procedural medieval town generation.",
        },
        "macro_states": states,
        "cells": cells,
    }


def export_grid_json(city_grid, output_dir=OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    grid_size = city_grid["metadata"]["grid_size"]
    output_path = output_dir / f"city_grid_{grid_size}x{grid_size}.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(city_grid, file, ensure_ascii=False, indent=2)

    return output_path


def export_grid_csv(city_grid, output_dir=OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    grid_size = city_grid["metadata"]["grid_size"]
    output_path = output_dir / f"city_grid_{grid_size}x{grid_size}.csv"

    fieldnames = [
        "x",
        "y",
        "height",
        "slope",
        "buildable",
        "distance_to_road",
        "accessibility",
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


def export_macro_state_svg(city_grid, output_dir=OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    grid_size = city_grid["metadata"]["grid_size"]
    output_path = output_dir / f"macro_ca_level1_{grid_size}x{grid_size}.svg"
    cell_px = 24
    margin = 24
    legend_width = 230
    width = margin * 2 + grid_size * cell_px + legend_width
    height = margin * 2 + grid_size * cell_px

    labels = {
        STATE_FOREST: "0 forest",
        STATE_LOW: "1 low",
        STATE_MEDIUM: "2 medium",
        STATE_HIGH: "3 high",
        STATE_TOWER: "4 tower",
        STATE_PLAZA: "5 plaza",
    }

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f5ef"/>',
        f'<text x="24" y="18" font-family="Arial" font-size="14" font-weight="700" fill="#222">Macro CA Level 1 - {grid_size}x{grid_size} land state map</text>',
    ]

    for cell in city_grid["cells"]:
        x = margin + cell["x"] * cell_px
        y = margin + cell["y"] * cell_px
        state = cell["state"]
        fill = STATE_COLORS[state]
        lines.append(
            f'<rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" fill="{fill}" stroke="#2b2b2b" stroke-width="0.45"/>'
        )
        lines.append(
            f'<text x="{x + cell_px / 2}" y="{y + cell_px / 2 + 4}" text-anchor="middle" font-family="Arial" font-size="10" fill="#1f1f1f">{state}</text>'
        )

    legend_x = margin + grid_size * cell_px + 34
    legend_y = margin + 28
    lines.append(
        f'<text x="{legend_x}" y="{legend_y - 14}" font-family="Arial" font-size="13" font-weight="700" fill="#222">Legend</text>'
    )

    for offset, state in enumerate([STATE_FOREST, STATE_LOW, STATE_MEDIUM, STATE_HIGH, STATE_TOWER, STATE_PLAZA]):
        item_y = legend_y + offset * 32
        lines.append(
            f'<rect x="{legend_x}" y="{item_y}" width="22" height="22" fill="{STATE_COLORS[state]}" stroke="#222" stroke-width="0.6"/>'
        )
        lines.append(
            f'<text x="{legend_x + 34}" y="{item_y + 15}" font-family="Arial" font-size="12" fill="#222">{labels[state]}</text>'
        )

    lines.append(
        f'<text x="{legend_x}" y="{legend_y + 225}" font-family="Arial" font-size="11" fill="#555">Seed total: {sum(SEED_COUNTS.values())}</text>'
    )
    lines.append(
        f'<text x="{legend_x}" y="{legend_y + 244}" font-family="Arial" font-size="11" fill="#555">CA: {CA_ITERATIONS} iterations + {SMOOTHING_ITERATIONS} smoothing</text>'
    )
    lines.append("</svg>")

    with output_path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    return output_path


def create_blender_grid(city_grid):
    try:
        import bpy
    except ImportError:
        return

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    state_materials = {
        STATE_FOREST: create_material("state_0_forest", (0.49, 0.60, 0.45, 1.0)),
        STATE_LOW: create_material("state_1_low", (0.84, 0.83, 0.74, 1.0)),
        STATE_MEDIUM: create_material("state_2_medium", (0.75, 0.77, 0.82, 1.0)),
        STATE_HIGH: create_material("state_3_high", (0.56, 0.61, 0.70, 1.0)),
        STATE_TOWER: create_material("state_4_tower", (0.84, 0.69, 0.42, 1.0)),
        STATE_PLAZA: create_material("state_5_plaza", (0.93, 0.90, 0.81, 1.0)),
    }
    line_material = create_material("virtual_grid_line", (0.28, 0.28, 0.3, 1.0))

    grid_size = city_grid["metadata"]["grid_size"]
    offset = grid_size * CELL_SIZE / 2
    vertices = []
    faces = []
    material_indices = []

    for vy in range(grid_size + 1):
        for vx in range(grid_size + 1):
            world_x = vx * CELL_SIZE - offset
            world_y = vy * CELL_SIZE - offset
            z = get_height(vx - 0.5, vy - 0.5, grid_size)
            vertices.append((world_x, world_y, z))

    for cell in city_grid["cells"]:
        x = cell["x"]
        y = cell["y"]
        bottom_left = y * (grid_size + 1) + x
        bottom_right = bottom_left + 1
        top_left = (y + 1) * (grid_size + 1) + x
        top_right = top_left + 1

        faces.append((bottom_left, bottom_right, top_right, top_left))

        material_indices.append(cell["state"])

    mesh = bpy.data.meshes.new(f"terrain_surface_{grid_size}x{grid_size}_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    grid_object = bpy.data.objects.new(f"terrain_surface_{grid_size}x{grid_size}", mesh)
    bpy.context.collection.objects.link(grid_object)
    for state in [STATE_FOREST, STATE_LOW, STATE_MEDIUM, STATE_HIGH, STATE_TOWER, STATE_PLAZA]:
        grid_object.data.materials.append(state_materials[state])

    for polygon, material_index in zip(grid_object.data.polygons, material_indices):
        polygon.material_index = material_index

    create_virtual_grid_lines(vertices, grid_size, line_material)
    setup_blender_camera(grid_size)


def create_virtual_grid_lines(surface_vertices, grid_size, line_material):
    import bpy

    line_vertices = [(x, y, z + 0.015) for x, y, z in surface_vertices]
    edges = []

    for y in range(grid_size + 1):
        for x in range(grid_size):
            start = y * (grid_size + 1) + x
            edges.append((start, start + 1))

    for x in range(grid_size + 1):
        for y in range(grid_size):
            start = y * (grid_size + 1) + x
            edges.append((start, start + grid_size + 1))

    line_mesh = bpy.data.meshes.new(f"virtual_grid_{grid_size}x{grid_size}_lines_mesh")
    line_mesh.from_pydata(line_vertices, edges, [])
    line_mesh.update()

    line_object = bpy.data.objects.new(f"virtual_grid_{grid_size}x{grid_size}_lines", line_mesh)
    bpy.context.collection.objects.link(line_object)
    line_object.data.materials.append(line_material)


def create_material(name, color):
    import bpy

    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    return material


def setup_blender_camera(grid_size):
    import bpy

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 25))
    sun = bpy.context.object
    sun.name = "sun_soft_preview"
    sun.data.energy = 2.2

    bpy.ops.object.camera_add(
        location=(grid_size * 0.45, -grid_size * 0.65, grid_size * 0.55),
        rotation=(math.radians(58), 0, math.radians(38)),
    )
    bpy.context.scene.camera = bpy.context.object


def save_blender_scene(output_dir=OUTPUT_DIR):
    try:
        import bpy
    except ImportError:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"city_grid_{GRID_SIZE}x{GRID_SIZE}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    return output_path


def main():
    city_grid = generate_city_grid(GRID_SIZE)
    json_path = export_grid_json(city_grid)
    csv_path = export_grid_csv(city_grid)
    svg_path = export_macro_state_svg(city_grid)
    create_blender_grid(city_grid)
    blend_path = save_blender_scene()

    print(f"Generated {GRID_SIZE}x{GRID_SIZE} city grid.")
    print(f"JSON saved to: {json_path}")
    print(f"CSV saved to: {csv_path}")
    print(f"Macro CA SVG saved to: {svg_path}")
    if blend_path:
        print(f"Blend scene saved to: {blend_path}")


if __name__ == "__main__":
    main()
