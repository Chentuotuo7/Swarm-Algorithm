import math
import random


MICRO_GRID_SIZE = 4
MICRO_CA_ITERATIONS = 5
MICRO_RANDOM_SEED = 128

MICRO_EMPTY = 0
MICRO_BUILDING = 1
MICRO_COURTYARD = 2
MICRO_PATH = 3
MICRO_TREE = 4
MICRO_TOWER = 5

MICRO_COLORS = {
    MICRO_EMPTY: "#e8e2d3",
    MICRO_BUILDING: "#bfc4d0",
    MICRO_COURTYARD: "#efe8c8",
    MICRO_PATH: "#d8d0bd",
    MICRO_TREE: "#7c9a72",
    MICRO_TOWER: "#d7b06a",
}

MACRO_PARAMS = {
    0: {
        "name": "forest",
        "building_coverage": 0.0,
        "tree_probability": 0.62,
        "path_probability": 0.08,
        "height_range": (0, 0),
        "tower_probability": 0.0,
    },
    1: {
        "name": "low",
        "building_coverage": 0.30,
        "tree_probability": 0.20,
        "path_probability": 0.22,
        "height_range": (1, 3),
        "tower_probability": 0.0,
    },
    2: {
        "name": "medium",
        "building_coverage": 0.54,
        "tree_probability": 0.08,
        "path_probability": 0.14,
        "height_range": (2, 4),
        "tower_probability": 0.035,
    },
    3: {
        "name": "high",
        "building_coverage": 0.72,
        "tree_probability": 0.03,
        "path_probability": 0.08,
        "height_range": (3, 6),
        "tower_probability": 0.065,
    },
    4: {
        "name": "tower_candidate",
        "building_coverage": 0.64,
        "tree_probability": 0.03,
        "path_probability": 0.12,
        "height_range": (3, 6),
        "tower_probability": 1.0,
    },
    5: {
        "name": "plaza",
        "building_coverage": 0.04,
        "tree_probability": 0.14,
        "path_probability": 0.62,
        "height_range": (0, 1),
        "tower_probability": 0.0,
    },
}


def stable_noise(x, y, seed=MICRO_RANDOM_SEED):
    value = math.sin(x * 12.9898 + y * 78.233 + seed * 11.137) * 43758.5453
    return value - math.floor(value)


def get_micro_neighbors(mx, my, micro_grid_size=MICRO_GRID_SIZE):
    neighbors = []

    for ny in range(my - 1, my + 2):
        for nx in range(mx - 1, mx + 2):
            if nx == mx and ny == my:
                continue
            if 0 <= nx < micro_grid_size and 0 <= ny < micro_grid_size:
                neighbors.append((nx, ny))

    return neighbors


def count_micro_states(states, mx, my, micro_grid_size=MICRO_GRID_SIZE):
    counts = {
        MICRO_EMPTY: 0,
        MICRO_BUILDING: 0,
        MICRO_COURTYARD: 0,
        MICRO_PATH: 0,
        MICRO_TREE: 0,
        MICRO_TOWER: 0,
    }

    for nx, ny in get_micro_neighbors(mx, my, micro_grid_size):
        counts[states[ny][nx]] += 1

    return counts


def is_near_locked_path(mx, my, locked_path_cells):
    if not locked_path_cells:
        return False
    for ny in range(my - 1, my + 2):
        for nx in range(mx - 1, mx + 2):
            if nx == mx and ny == my:
                continue
            if (nx, ny) in locked_path_cells:
                return True
    return False


def get_micro_center_score(mx, my, micro_grid_size=MICRO_GRID_SIZE):
    center = (micro_grid_size - 1) / 2
    distance = math.hypot(mx - center, my - center)
    max_distance = math.hypot(center, center)
    return 1.0 - min(1.0, distance / max_distance)


def get_micro_edge_score(mx, my, micro_grid_size=MICRO_GRID_SIZE):
    edge_distance = min(mx, my, micro_grid_size - 1 - mx, micro_grid_size - 1 - my)
    return 1.0 - min(1.0, edge_distance / (micro_grid_size * 0.45))


def create_path_bias(macro_cell, rng, micro_grid_size=MICRO_GRID_SIZE):
    macro_state = macro_cell["state"]
    if macro_state in (0, 5):
        return set()

    path_cells = set()
    orientation = "vertical" if rng.random() < 0.5 else "horizontal"
    index = rng.randint(1, micro_grid_size - 2)

    for step in range(micro_grid_size):
        drift = -1 if rng.random() < 0.18 else (1 if rng.random() > 0.82 else 0)
        path_index = max(1, min(micro_grid_size - 2, index + drift))
        if orientation == "vertical":
            path_cells.add((path_index, step))
        else:
            path_cells.add((step, path_index))

    return path_cells


def initialize_micro_states(macro_cell, micro_grid_size=MICRO_GRID_SIZE, locked_path_cells=None):
    locked_path_cells = locked_path_cells or set()
    rng = random.Random(MICRO_RANDOM_SEED + macro_cell["x"] * 1009 + macro_cell["y"] * 917)
    macro_state = macro_cell["state"]
    params = MACRO_PARAMS[macro_state]
    states = [[MICRO_EMPTY for _ in range(micro_grid_size)] for _ in range(micro_grid_size)]
    path_bias = create_path_bias(macro_cell, rng, micro_grid_size)

    for my in range(micro_grid_size):
        for mx in range(micro_grid_size):
            if (mx, my) in locked_path_cells:
                states[my][mx] = MICRO_PATH
                continue

            if macro_state == 0:
                states[my][mx] = MICRO_TREE if rng.random() < params["tree_probability"] else MICRO_EMPTY
                continue

            if (mx, my) in path_bias:
                states[my][mx] = MICRO_PATH
                continue

            center_score = get_micro_center_score(mx, my, micro_grid_size)
            edge_score = get_micro_edge_score(mx, my, micro_grid_size)
            noise = stable_noise(
                macro_cell["x"] * micro_grid_size + mx,
                macro_cell["y"] * micro_grid_size + my,
            )

            building_probability = (
                params["building_coverage"]
                + center_score * 0.12
                + (noise - 0.5) * 0.18
                - edge_score * 0.10
            )
            if is_near_locked_path(mx, my, locked_path_cells) and macro_state in (1, 2, 3, 4):
                building_probability += 0.18

            if macro_state == 5:
                building_probability *= 0.35

            roll = rng.random()
            if roll < params["tree_probability"]:
                states[my][mx] = MICRO_TREE
            elif roll < params["tree_probability"] + params["path_probability"]:
                states[my][mx] = MICRO_PATH
            elif roll < params["tree_probability"] + params["path_probability"] + building_probability:
                states[my][mx] = MICRO_BUILDING
            else:
                states[my][mx] = MICRO_EMPTY

    return states


def choose_next_micro_state(
    current_state,
    counts,
    macro_cell,
    mx,
    my,
    rng,
    micro_grid_size=MICRO_GRID_SIZE,
    locked_path_cells=None,
):
    locked_path_cells = locked_path_cells or set()
    if (mx, my) in locked_path_cells:
        return MICRO_PATH

    macro_state = macro_cell["state"]
    params = MACRO_PARAMS[macro_state]
    building_neighbors = counts[MICRO_BUILDING] + counts[MICRO_TOWER]
    tree_neighbors = counts[MICRO_TREE]
    path_neighbors = counts[MICRO_PATH]

    if macro_state == 0:
        if current_state == MICRO_TREE and tree_neighbors >= 2:
            return MICRO_TREE
        return MICRO_TREE if rng.random() < params["tree_probability"] else MICRO_EMPTY

    if macro_state == 5:
        if current_state == MICRO_BUILDING and building_neighbors <= 1:
            return MICRO_PATH
        if current_state == MICRO_TREE:
            return MICRO_TREE if rng.random() < 0.78 else MICRO_EMPTY
        return MICRO_PATH if rng.random() < 0.55 else MICRO_EMPTY

    edge_score = get_micro_edge_score(mx, my, micro_grid_size)
    growth_bonus = {
        1: 0.20,
        2: 0.38,
        3: 0.56,
        4: 0.42,
    }.get(macro_state, 0.28)
    if is_near_locked_path(mx, my, locked_path_cells) and macro_state in (1, 2, 3, 4):
        growth_bonus += 0.18

    if current_state == MICRO_BUILDING:
        if building_neighbors >= 7:
            return MICRO_COURTYARD
        if building_neighbors <= 1 and rng.random() < (0.55 if macro_state == 1 else 0.32):
            return MICRO_EMPTY if rng.random() < 0.55 else MICRO_PATH
        return MICRO_BUILDING

    if current_state == MICRO_EMPTY:
        if building_neighbors >= 6:
            return MICRO_COURTYARD
        if 2 <= building_neighbors <= 4 and rng.random() < growth_bonus:
            return MICRO_BUILDING
        if path_neighbors >= 3 and rng.random() < 0.42:
            return MICRO_PATH
        if tree_neighbors >= 3 and macro_state in (1, 2) and rng.random() < 0.24:
            return MICRO_TREE

    if current_state == MICRO_PATH:
        if path_neighbors >= 2 or edge_score > 0.85:
            return MICRO_PATH
        if building_neighbors >= 4 and rng.random() < growth_bonus * 0.45:
            return MICRO_BUILDING
        return MICRO_PATH if rng.random() < 0.62 else MICRO_EMPTY

    if current_state == MICRO_TREE:
        if macro_state in (1, 2) and tree_neighbors >= 2 and rng.random() < 0.76:
            return MICRO_TREE
        if building_neighbors >= 5 and rng.random() < 0.50:
            return MICRO_COURTYARD
        return MICRO_TREE if rng.random() < 0.62 else MICRO_EMPTY

    if current_state == MICRO_COURTYARD:
        return MICRO_COURTYARD if building_neighbors >= 4 else MICRO_EMPTY

    return current_state


def evolve_micro_states(macro_cell, states, micro_grid_size=MICRO_GRID_SIZE, locked_path_cells=None):
    locked_path_cells = locked_path_cells or set()
    rng = random.Random(MICRO_RANDOM_SEED + 3000 + macro_cell["x"] * 101 + macro_cell["y"] * 103)

    for _ in range(MICRO_CA_ITERATIONS):
        next_states = [[MICRO_EMPTY for _ in range(micro_grid_size)] for _ in range(micro_grid_size)]
        for my in range(micro_grid_size):
            for mx in range(micro_grid_size):
                counts = count_micro_states(states, mx, my, micro_grid_size)
                next_states[my][mx] = choose_next_micro_state(
                    states[my][mx],
                    counts,
                    macro_cell,
                    mx,
                    my,
                    rng,
                    micro_grid_size,
                    locked_path_cells,
                )
        states = next_states

    return states


def place_tower_if_needed(macro_cell, states, micro_grid_size=MICRO_GRID_SIZE, locked_path_cells=None):
    locked_path_cells = locked_path_cells or set()
    rng = random.Random(MICRO_RANDOM_SEED + 9000 + macro_cell["x"] * 313 + macro_cell["y"] * 317)
    macro_state = macro_cell["state"]
    params = MACRO_PARAMS[macro_state]

    if macro_state == 4:
        should_place_tower = True
    elif macro_state in (2, 3):
        should_place_tower = rng.random() < params["tower_probability"]
    else:
        should_place_tower = False

    if not should_place_tower:
        return states

    candidates = []
    for my in range(1, micro_grid_size - 1):
        for mx in range(1, micro_grid_size - 1):
            if (mx, my) in locked_path_cells:
                continue
            counts = count_micro_states(states, mx, my, micro_grid_size)
            building_neighbors = counts[MICRO_BUILDING] + counts[MICRO_TOWER]
            if states[my][mx] in (MICRO_BUILDING, MICRO_EMPTY, MICRO_PATH) and building_neighbors >= 2:
                score = get_micro_center_score(mx, my, micro_grid_size) + building_neighbors * 0.18
                candidates.append((score, mx, my))

    if not candidates:
        return states

    candidates.sort(reverse=True)
    _, tower_x, tower_y = candidates[0]
    states[tower_y][tower_x] = MICRO_TOWER
    return states


def generate_micro_layout(macro_cell, micro_grid_size=MICRO_GRID_SIZE, locked_path_cells=None):
    locked_path_cells = locked_path_cells or set()
    states = initialize_micro_states(macro_cell, micro_grid_size, locked_path_cells)
    states = evolve_micro_states(macro_cell, states, micro_grid_size, locked_path_cells)
    states = place_tower_if_needed(macro_cell, states, micro_grid_size, locked_path_cells)
    return states


def get_floor_count(macro_cell, micro_state, mx, my, micro_grid_size=MICRO_GRID_SIZE):
    rng = random.Random(
        MICRO_RANDOM_SEED
        + macro_cell["x"] * 100003
        + macro_cell["y"] * 1009
        + mx * 97
        + my * 53
    )

    if micro_state == MICRO_TOWER:
        return rng.randint(10, 20)

    params = MACRO_PARAMS[macro_cell["state"]]
    min_floor, max_floor = params["height_range"]
    if max_floor <= 0:
        return 0

    floor_count = rng.randint(min_floor, max_floor)
    center_bonus = 1 if get_micro_center_score(mx, my, micro_grid_size) > 0.72 and macro_cell["state"] in (3, 4) else 0
    return max(1, floor_count + center_bonus)
