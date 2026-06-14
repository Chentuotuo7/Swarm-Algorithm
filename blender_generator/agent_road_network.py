"""Agent-based medieval road network generation for Blender city data.

The generator follows the two-stage shape from 1.md:
1. grow an integer-grid road topology with main-road and alley agents;
2. solidify it into a graph and spatially distort the graph for review output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable


Direction = str
Point = tuple[int, int]
Segment = tuple[Point, Point]
MICRO_ROAD_WORLD_SCALE = 1.8

DIRECTION_VECTORS: dict[Direction, Point] = {
    "UP": (0, 1),
    "DOWN": (0, -1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

PERPENDICULAR_DIRECTIONS: dict[Direction, tuple[Direction, Direction]] = {
    "UP": ("LEFT", "RIGHT"),
    "DOWN": ("LEFT", "RIGHT"),
    "LEFT": ("UP", "DOWN"),
    "RIGHT": ("UP", "DOWN"),
}


@dataclass(frozen=True)
class Bounds:
    min_x: int = -22
    max_x: int = 22
    min_y: int = -22
    max_y: int = 22


@dataclass(frozen=True)
class MainRoadConfig:
    count: int = 8
    min_life: int = 70
    max_life: int = 150
    straight_probability: float = 0.9
    turn_probability: float = 0.1
    penetration_probability: float = 0.5


@dataclass(frozen=True)
class AlleyConfig:
    min_life: int = 12
    max_life: int = 42
    turn_probability: float = 0.35
    spawn_probability_from_main_road: float = 0.28
    random_death_probability: float = 0.05


@dataclass(frozen=True)
class EdgeConnectorConfig:
    contacts_per_side: int = 6


@dataclass(frozen=True)
class NoiseConfig:
    scale: float = 0.08
    strength: float = 2.5


@dataclass(frozen=True)
class HistoricCenterConfig:
    center_x: float = 0.0
    center_y: float = 0.0
    radius: float = 18.0
    strength: float = 0.25


@dataclass(frozen=True)
class WorldScaleConfig:
    scale: float = 1.8


@dataclass(frozen=True)
class RoadGenerationConfig:
    seed: int = 42
    bounds: Bounds = field(default_factory=Bounds)
    main_road: MainRoadConfig = field(default_factory=MainRoadConfig)
    alley: AlleyConfig = field(default_factory=AlleyConfig)
    edge_connector: EdgeConnectorConfig = field(default_factory=EdgeConnectorConfig)
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    historic_center: HistoricCenterConfig = field(default_factory=HistoricCenterConfig)
    world: WorldScaleConfig = field(default_factory=WorldScaleConfig)


@dataclass
class RoadAgent:
    id: str
    type: str
    position: Point
    direction: Direction
    life: int
    max_life: int
    path: list[Point]
    alive: bool = True


def point_key(point: Point) -> str:
    return f"{point[0]},{point[1]}"


def segment_key(start: Point, end: Point) -> Segment:
    return tuple(sorted((start, end)))  # type: ignore[return-value]


def add_points(start: Point, direction: Direction) -> Point:
    dx, dy = DIRECTION_VECTORS[direction]
    return start[0] + dx, start[1] + dy


def in_bounds(point: Point, bounds: Bounds) -> bool:
    return (
        bounds.min_x <= point[0] <= bounds.max_x
        and bounds.min_y <= point[1] <= bounds.max_y
    )


def choose_perpendicular(direction: Direction, rng: random.Random) -> Direction:
    return rng.choice(PERPENDICULAR_DIRECTIONS[direction])


def maybe_turn(direction: Direction, probability: float, rng: random.Random) -> Direction:
    if rng.random() < probability:
        return choose_perpendicular(direction, rng)
    return direction


def create_initial_main_agents(config: RoadGenerationConfig, rng: random.Random) -> list[RoadAgent]:
    center_x = round((config.bounds.min_x + config.bounds.max_x) / 2)
    center_y = round((config.bounds.min_y + config.bounds.max_y) / 2)
    directions: list[Direction] = ["UP", "RIGHT", "DOWN", "LEFT"]
    agents: list[RoadAgent] = []

    for index in range(config.main_road.count):
        direction = directions[index % len(directions)]
        life = rng.randint(config.main_road.min_life, config.main_road.max_life)
        start = (center_x, center_y)
        agents.append(
            RoadAgent(
                id=f"main_{index + 1}",
                type="main_road",
                position=start,
                direction=direction,
                life=life,
                max_life=life,
                path=[start],
            )
        )

    return agents


def step_main_agent(
    agent: RoadAgent,
    occupancy: set[str],
    segments: dict[Segment, str],
    config: RoadGenerationConfig,
    rng: random.Random,
) -> None:
    if not agent.alive:
        return

    agent.direction = maybe_turn(agent.direction, config.main_road.turn_probability, rng)
    next_point = add_points(agent.position, agent.direction)
    if not in_bounds(next_point, config.bounds):
        agent.alive = False
        return

    occupied = point_key(next_point) in occupancy
    if occupied and rng.random() >= config.main_road.penetration_probability:
        agent.alive = False
        return

    segments.setdefault(segment_key(agent.position, next_point), "main_road")
    occupancy.add(point_key(next_point))
    agent.position = next_point
    agent.path.append(next_point)
    agent.life -= 1
    if agent.life <= 0:
        agent.alive = False


def run_main_agents(
    agents: list[RoadAgent],
    occupancy: set[str],
    segments: dict[Segment, str],
    config: RoadGenerationConfig,
    rng: random.Random,
) -> None:
    for agent in agents:
        occupancy.add(point_key(agent.position))

    while any(agent.alive for agent in agents):
        for agent in agents:
            step_main_agent(agent, occupancy, segments, config, rng)


def spawn_alley_agents(
    main_agents: list[RoadAgent],
    occupancy: set[str],
    config: RoadGenerationConfig,
    rng: random.Random,
) -> list[RoadAgent]:
    agents: list[RoadAgent] = []
    next_id = 1

    for main_agent in main_agents:
        for start, end in zip(main_agent.path, main_agent.path[1:]):
            if rng.random() >= config.alley.spawn_probability_from_main_road:
                continue
            direction = direction_between(start, end)
            if direction is None:
                continue
            alley_direction = choose_perpendicular(direction, rng)
            life = rng.randint(config.alley.min_life, config.alley.max_life)
            agents.append(
                RoadAgent(
                    id=f"alley_{next_id}",
                    type="alley",
                    position=end,
                    direction=alley_direction,
                    life=life,
                    max_life=life,
                    path=[end],
                )
            )
            occupancy.add(point_key(end))
            next_id += 1

    return agents


def step_alley_agent(
    agent: RoadAgent,
    occupancy: set[str],
    segments: dict[Segment, str],
    config: RoadGenerationConfig,
    rng: random.Random,
) -> None:
    if not agent.alive:
        return

    if rng.random() < config.alley.random_death_probability:
        agent.alive = False
        return

    agent.direction = maybe_turn(agent.direction, config.alley.turn_probability, rng)
    next_point = add_points(agent.position, agent.direction)
    if not in_bounds(next_point, config.bounds):
        agent.alive = False
        return

    if point_key(next_point) in occupancy:
        segments.setdefault(segment_key(agent.position, next_point), "alley")
        agent.path.append(next_point)
        agent.alive = False
        return

    segments.setdefault(segment_key(agent.position, next_point), "alley")
    occupancy.add(point_key(next_point))
    agent.position = next_point
    agent.path.append(next_point)
    agent.life -= 1
    if agent.life <= 0:
        agent.alive = False


def run_alley_agents(
    agents: list[RoadAgent],
    occupancy: set[str],
    segments: dict[Segment, str],
    config: RoadGenerationConfig,
    rng: random.Random,
) -> None:
    while any(agent.alive for agent in agents):
        for agent in agents:
            step_alley_agent(agent, occupancy, segments, config, rng)


def direction_between(start: Point, end: Point) -> Direction | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    for direction, vector in DIRECTION_VECTORS.items():
        if vector == (dx, dy):
            return direction
    return None


def build_adjacency(segments: dict[Segment, str]) -> dict[Point, dict[Point, str]]:
    adjacency: dict[Point, dict[Point, str]] = {}
    for (start, end), road_type in segments.items():
        adjacency.setdefault(start, {})[end] = road_type
        adjacency.setdefault(end, {})[start] = road_type
    return adjacency


def build_segment_points(segments: dict[Segment, str]) -> set[Point]:
    points: set[Point] = set()
    for start, end in segments:
        points.add(start)
        points.add(end)
    return points


def add_path_segments(segments: dict[Segment, str], path: list[Point], road_type: str) -> int:
    added = 0
    for start, end in zip(path, path[1:]):
        key = segment_key(start, end)
        if key not in segments:
            added += 1
        segments.setdefault(key, road_type)
    return added


def manhattan_path(start: Point, target: Point, horizontal_first: bool) -> list[Point]:
    path = [start]
    x, y = start
    tx, ty = target

    def step_x() -> None:
        nonlocal x
        while x != tx:
            x += 1 if tx > x else -1
            path.append((x, y))

    def step_y() -> None:
        nonlocal y
        while y != ty:
            y += 1 if ty > y else -1
            path.append((x, y))

    if horizontal_first:
        step_x()
        step_y()
    else:
        step_y()
        step_x()
    return path


def boundary_contact_points(segments: dict[Segment, str], bounds: Bounds) -> dict[str, set[Point]]:
    contacts = {"left": set(), "right": set(), "bottom": set(), "top": set()}
    for point in build_segment_points(segments):
        x, y = point
        if x == bounds.min_x:
            contacts["left"].add(point)
        if x == bounds.max_x:
            contacts["right"].add(point)
        if y == bounds.min_y:
            contacts["bottom"].add(point)
        if y == bounds.max_y:
            contacts["top"].add(point)
    return contacts


def boundary_contact_counts(segments: dict[Segment, str], bounds: Bounds) -> dict[str, int]:
    return {side: len(points) for side, points in boundary_contact_points(segments, bounds).items()}


def evenly_spaced_values(min_value: int, max_value: int, count: int) -> list[int]:
    if count <= 1:
        return [round((min_value + max_value) / 2)]
    span = max_value - min_value
    return [round(min_value + span * (index + 1) / (count + 1)) for index in range(count)]


def choose_connector_source(points: set[Point], target: Point, center: Point) -> Point:
    return min(
        points,
        key=lambda point: (
            abs(point[0] - target[0]) + abs(point[1] - target[1]),
            abs(point[0] - center[0]) + abs(point[1] - center[1]),
        ),
    )


def add_boundary_connectors(segments: dict[Segment, str], config: RoadGenerationConfig) -> int:
    target_count = config.edge_connector.contacts_per_side
    if target_count <= 0:
        return 0

    center = (
        round((config.bounds.min_x + config.bounds.max_x) / 2),
        round((config.bounds.min_y + config.bounds.max_y) / 2),
    )
    added = 0
    targets: list[tuple[str, Point]] = []
    for y in evenly_spaced_values(config.bounds.min_y, config.bounds.max_y, target_count):
        targets.append(("left", (config.bounds.min_x, y)))
        targets.append(("right", (config.bounds.max_x, y)))
    for x in evenly_spaced_values(config.bounds.min_x, config.bounds.max_x, target_count):
        targets.append(("bottom", (x, config.bounds.min_y)))
        targets.append(("top", (x, config.bounds.max_y)))

    for side, target in targets:
        points = build_segment_points(segments)
        if not points:
            break
        existing = boundary_contact_points(segments, config.bounds)[side]
        if target in existing:
            continue
        source = choose_connector_source(points, target, center)
        horizontal_first = side in {"bottom", "top"}
        added += add_path_segments(
            segments,
            manhattan_path(source, target, horizontal_first=horizontal_first),
            "main_road",
        )
    return added


def add_boundary_frame(segments: dict[Segment, str], bounds: Bounds) -> int:
    added = 0
    for x in range(bounds.min_x, bounds.max_x):
        added += add_path_segments(segments, [(x, bounds.min_y), (x + 1, bounds.min_y)], "main_road")
        added += add_path_segments(segments, [(x, bounds.max_y), (x + 1, bounds.max_y)], "main_road")
    for y in range(bounds.min_y, bounds.max_y):
        added += add_path_segments(segments, [(bounds.min_x, y), (bounds.min_x, y + 1)], "main_road")
        added += add_path_segments(segments, [(bounds.max_x, y), (bounds.max_x, y + 1)], "main_road")
    return added


def remove_boundary_parallel_segments(segments: dict[Segment, str], bounds: Bounds) -> int:
    removed = 0
    for segment in list(segments):
        (x1, y1), (x2, y2) = segment
        is_outer_horizontal = y1 == y2 and y1 in (bounds.min_y, bounds.max_y)
        is_outer_vertical = x1 == x2 and x1 in (bounds.min_x, bounds.max_x)
        if is_outer_horizontal or is_outer_vertical:
            del segments[segment]
            removed += 1
    return removed


def is_bend(point: Point, neighbors: Iterable[Point]) -> bool:
    neighbor_list = list(neighbors)
    if len(neighbor_list) != 2:
        return False
    first, second = neighbor_list
    return first[0] != second[0] and first[1] != second[1]


def classify_node(point: Point, adjacency: dict[Point, dict[Point, str]]) -> str:
    degree = len(adjacency.get(point, {}))
    if degree <= 1:
        return "dead_end"
    if degree >= 3:
        return "intersection"
    if is_bend(point, adjacency[point]):
        return "bend"
    return "normal"


def detect_key_nodes(adjacency: dict[Point, dict[Point, str]]) -> set[Point]:
    key_nodes: set[Point] = set()
    for point, neighbors in adjacency.items():
        degree = len(neighbors)
        if degree != 2 or is_bend(point, neighbors):
            key_nodes.add(point)
    if not key_nodes:
        key_nodes.update(adjacency)
    return key_nodes


def dominant_type(types: list[str]) -> str:
    if "main_road" in types:
        return "main_road"
    if "block_splitter" in types:
        return "block_splitter"
    if "secondary_road" in types:
        return "secondary_road"
    return "alley"


def road_hierarchy(road_type: str) -> int:
    if road_type == "main_road":
        return 1
    if road_type in {"block_splitter", "secondary_road"}:
        return 2
    return 3


def road_width(road_type: str) -> float:
    if road_type == "main_road":
        return 0.22
    if road_type in {"block_splitter", "secondary_road"}:
        return 0.12
    return 0.07


def trace_edges(adjacency: dict[Point, dict[Point, str]], key_nodes: set[Point]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    visited_segments: set[Segment] = set()
    edge_id = 1

    for source in sorted(key_nodes):
        for next_point, road_type in sorted(adjacency.get(source, {}).items()):
            first_segment = segment_key(source, next_point)
            if first_segment in visited_segments:
                continue

            path = [source, next_point]
            types = [road_type]
            visited_segments.add(first_segment)
            previous = source
            current = next_point

            while current not in key_nodes:
                candidates = [
                    neighbor for neighbor in adjacency[current]
                    if neighbor != previous
                ]
                if not candidates:
                    break
                following = candidates[0]
                current_segment = segment_key(current, following)
                if current_segment in visited_segments:
                    break
                types.append(adjacency[current][following])
                visited_segments.add(current_segment)
                path.append(following)
                previous, current = current, following

            if source == current or current not in key_nodes:
                continue

            edge_type = dominant_type(types)
            edges.append(
                {
                    "id": f"edge_{edge_id}",
                    "source": point_key(source),
                    "target": point_key(current),
                    "type": edge_type,
                    "hierarchy": road_hierarchy(edge_type),
                    "width": road_width(edge_type),
                    "points": [{"x": x, "y": y} for x, y in path],
                }
            )
            edge_id += 1

    return edges


def solidify_graph(segments: dict[Segment, str]) -> dict[str, Any]:
    adjacency = build_adjacency(segments)
    key_nodes = detect_key_nodes(adjacency)
    edges = trace_edges(adjacency, key_nodes)
    nodes = [
        {
            "id": point_key(point),
            "x": float(point[0]),
            "y": float(point[1]),
            "originalX": point[0],
            "originalY": point[1],
            "type": classify_node(point, adjacency),
        }
        for point in sorted(key_nodes)
    ]
    return {"nodes": nodes, "edges": edges}


def smooth_noise(x: float, y: float, seed: int = 42) -> float:
    x0 = math.floor(x)
    y0 = math.floor(y)
    tx = x - x0
    ty = y - y0

    def fade(value: float) -> float:
        return value * value * value * (value * (value * 6 - 15) + 10)

    def lattice(ix: int, iy: int) -> float:
        value = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453123
        return (value - math.floor(value)) * 2 - 1

    sx = fade(tx)
    sy = fade(ty)
    n00 = lattice(x0, y0)
    n10 = lattice(x0 + 1, y0)
    n01 = lattice(x0, y0 + 1)
    n11 = lattice(x0 + 1, y0 + 1)
    nx0 = n00 + (n10 - n00) * sx
    nx1 = n01 + (n11 - n01) * sx
    return nx0 + (nx1 - nx0) * sy


def distort_point(x: float, y: float, config: RoadGenerationConfig) -> tuple[float, float]:
    nx = smooth_noise(x * config.noise.scale, y * config.noise.scale, config.seed)
    ny = smooth_noise(x * config.noise.scale + 1000, y * config.noise.scale + 1000, config.seed)
    distorted_x = x + nx * config.noise.strength
    distorted_y = y + ny * config.noise.strength

    center = config.historic_center
    dx = center.center_x - distorted_x
    dy = center.center_y - distorted_y
    distance = math.hypot(dx, dy)
    if distance > 0:
        influence = 1 - max(0.0, min(1.0, distance / center.radius))
        force = influence * center.strength
        distorted_x += (dx / distance) * force * distance
        distorted_y += (dy / distance) * force * distance

    return round(distorted_x * config.world.scale, 4), round(distorted_y * config.world.scale, 4)


def distort_graph(graph: dict[str, Any], config: RoadGenerationConfig) -> dict[str, Any]:
    distorted = json.loads(json.dumps(graph))
    for node in distorted["nodes"]:
        node["x"], node["y"] = distort_point(
            float(node["originalX"]),
            float(node["originalY"]),
            config,
        )
    for edge in distorted["edges"]:
        edge["points"] = [
            dict(zip(("x", "y"), distort_point(float(point["x"]), float(point["y"]), config)))
            for point in edge.get("points", [])
        ]
    return distorted


def generate_raw_topology(config: RoadGenerationConfig) -> dict[str, Any]:
    rng = random.Random(config.seed)
    occupancy: set[str] = set()
    segments: dict[Segment, str] = {}
    main_agents = create_initial_main_agents(config, rng)
    run_main_agents(main_agents, occupancy, segments, config, rng)
    alley_agents = spawn_alley_agents(main_agents, occupancy, config, rng)
    run_alley_agents(alley_agents, occupancy, segments, config, rng)
    edge_connector_segments = add_boundary_connectors(segments, config)
    boundary_parallel_segments_removed = remove_boundary_parallel_segments(segments, config.bounds)
    occupancy.update(point_key(point) for point in build_segment_points(segments))
    return {
        "occupancy": occupancy,
        "segments": segments,
        "main_agents": main_agents,
        "alley_agents": alley_agents,
        "boundary_frame_segments": 0,
        "boundary_parallel_segments_removed": boundary_parallel_segments_removed,
        "edge_connector_segments": edge_connector_segments,
    }


def generate_medieval_road_network(config: RoadGenerationConfig | None = None) -> dict[str, Any]:
    config = config or RoadGenerationConfig()
    raw = generate_raw_topology(config)
    graph = solidify_graph(raw["segments"])
    distorted = distort_graph(graph, config)
    distorted["metadata"] = {
        "config": config_to_dict(config),
        "raw_point_count": len(raw["occupancy"]),
        "raw_segment_count": len(raw["segments"]),
        "main_agent_count": len(raw["main_agents"]),
        "alley_agent_count": len(raw["alley_agents"]),
    }
    return {
        "raw": raw,
        "graph": graph,
        "distorted_graph": distorted,
    }


def generate_micro_road_network(
    macro_grid: dict[str, Any],
    micro_grid_size: int,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate road topology on global micro-grid boundary vertices."""

    macro_grid_size = int(macro_grid.get("metadata", {}).get("grid_size", 15))
    total_grid_size = macro_grid_size * micro_grid_size
    config = RoadGenerationConfig(
        seed=seed,
        bounds=Bounds(
            min_x=0,
            max_x=total_grid_size,
            min_y=0,
            max_y=total_grid_size,
        ),
        main_road=MainRoadConfig(count=14, min_life=90, max_life=180, turn_probability=0.07),
        alley=AlleyConfig(min_life=14, max_life=48, spawn_probability_from_main_road=0.30),
        edge_connector=EdgeConnectorConfig(contacts_per_side=6),
        noise=NoiseConfig(scale=0.08, strength=1.4),
        historic_center=HistoricCenterConfig(
            center_x=total_grid_size / 2,
            center_y=total_grid_size / 2,
            radius=max(8.0, total_grid_size * 0.42),
            strength=0.14,
        ),
        world=WorldScaleConfig(scale=MICRO_ROAD_WORLD_SCALE),
    )
    raw = generate_raw_topology(config)
    grid_graph = solidify_graph(raw["segments"])
    warped_vertices = generate_warped_vertices(
        macro_grid_size=macro_grid_size,
        micro_grid_size=micro_grid_size,
        config=config,
    )
    world_graph = micro_graph_to_world_graph(
        grid_graph,
        macro_grid_size=macro_grid_size,
        micro_grid_size=micro_grid_size,
        config=config,
        distort=True,
        warped_vertices=warped_vertices,
    )
    world_graph["metadata"] = {
        "source": "micro_grid",
        "macro_grid_size": macro_grid_size,
        "micro_grid_size": micro_grid_size,
        "total_grid_size": total_grid_size,
        "topology_space": "micro_grid_boundaries",
        "config": config_to_dict(config),
        "raw_point_count": len(raw["occupancy"]),
        "raw_segment_count": len(raw["segments"]),
        "main_agent_count": len(raw["main_agents"]),
        "alley_agent_count": len(raw["alley_agents"]),
        "boundary_frame_segments": raw["boundary_frame_segments"],
        "boundary_parallel_segments_removed": raw["boundary_parallel_segments_removed"],
        "edge_connector_segments": raw["edge_connector_segments"],
        "boundary_contacts": boundary_contact_counts(raw["segments"], config.bounds),
    }
    return {
        "raw": raw,
        "graph": micro_graph_to_world_graph(
            grid_graph,
            macro_grid_size=macro_grid_size,
            micro_grid_size=micro_grid_size,
            config=config,
            distort=False,
        ),
        "grid_graph": grid_graph,
        "distorted_graph": world_graph,
        "warped_vertices": warped_vertices,
        "road_cells": derive_road_cells_from_segments(raw["segments"], total_grid_size),
        "road_segments": raw["segments"],
        "config": config,
    }


def rebuild_micro_road_result(
    road_result: dict[str, Any],
    macro_grid: dict[str, Any],
    micro_grid_size: int,
    added_segments: dict[Segment, str] | None = None,
) -> dict[str, Any]:
    """Rebuild graph-facing road output after structural segments are added."""

    macro_grid_size = int(macro_grid.get("metadata", {}).get("grid_size", 15))
    total_grid_size = macro_grid_size * micro_grid_size
    config = road_result["config"]
    segments = dict(road_result["road_segments"])
    if added_segments:
        for segment, road_type in added_segments.items():
            segments.setdefault(segment, road_type)
    boundary_parallel_segments_removed = remove_boundary_parallel_segments(segments, config.bounds)

    grid_graph = solidify_graph(segments)
    world_graph = micro_graph_to_world_graph(
        grid_graph,
        macro_grid_size=macro_grid_size,
        micro_grid_size=micro_grid_size,
        config=config,
        distort=True,
        warped_vertices=road_result["warped_vertices"],
    )
    previous_metadata = dict(road_result["distorted_graph"].get("metadata", {}))
    previous_metadata["raw_segment_count"] = len(segments)
    previous_metadata["boundary_contacts"] = boundary_contact_counts(segments, config.bounds)
    previous_metadata["boundary_parallel_segments_removed"] = (
        previous_metadata.get("boundary_parallel_segments_removed", 0)
        + boundary_parallel_segments_removed
    )
    world_graph["metadata"] = previous_metadata

    return {
        **road_result,
        "raw": {**road_result["raw"], "segments": segments, "occupancy": set(point_key(point) for point in build_segment_points(segments))},
        "graph": micro_graph_to_world_graph(
            grid_graph,
            macro_grid_size=macro_grid_size,
            micro_grid_size=micro_grid_size,
            config=config,
            distort=False,
        ),
        "grid_graph": grid_graph,
        "distorted_graph": world_graph,
        "road_cells": derive_road_cells_from_segments(segments, total_grid_size),
        "road_segments": segments,
    }


def key_to_point(key: str) -> Point:
    x, y = key.split(",", 1)
    return int(x), int(y)


def derive_road_cells_from_segments(
    segments: dict[Segment, str],
    total_grid_size: int,
) -> set[Point]:
    """Reserve micro cells adjacent to boundary-aligned road segments.

    The agent graph lives on grid vertices/edges. Buildings and trees still live
    in grid cells, so this converts each road edge into neighboring path cells
    without moving the road centerline off the cell boundary.
    """

    road_cells: set[Point] = set()

    def add_cell(mx: int, my: int) -> None:
        if 0 <= mx < total_grid_size and 0 <= my < total_grid_size:
            road_cells.add((mx, my))

    for start, end in segments:
        x1, y1 = start
        x2, y2 = end
        if y1 == y2:
            mx = min(x1, x2)
            add_cell(mx, y1 - 1)
            add_cell(mx, y1)
        elif x1 == x2:
            my = min(y1, y2)
            add_cell(x1 - 1, my)
            add_cell(x1, my)

    return road_cells


def generate_warped_vertices(
    macro_grid_size: int,
    micro_grid_size: int,
    config: RoadGenerationConfig,
) -> dict[str, dict[str, float]]:
    total_grid_size = macro_grid_size * micro_grid_size
    vertices: dict[str, dict[str, float]] = {}
    for gy in range(total_grid_size + 1):
        for gx in range(total_grid_size + 1):
            x, y = micro_point_to_world(
                (gx, gy),
                macro_grid_size=macro_grid_size,
                micro_grid_size=micro_grid_size,
                config=config,
                distort=True,
            )
            vertices[point_key((gx, gy))] = {"x": x, "y": y}
    return vertices


def micro_point_to_world(
    point: dict[str, Any] | Point,
    macro_grid_size: int,
    micro_grid_size: int,
    config: RoadGenerationConfig | None = None,
    distort: bool = False,
) -> tuple[float, float]:
    if isinstance(point, dict):
        x = float(point["x"])
        y = float(point["y"])
    else:
        x = float(point[0])
        y = float(point[1])

    world_scale = config.world.scale if config is not None else 1.0
    world_x = (x / micro_grid_size - macro_grid_size / 2) * world_scale
    world_y = (y / micro_grid_size - macro_grid_size / 2) * world_scale
    if not distort or config is None:
        return round(world_x, 4), round(world_y, 4)

    x, y = distort_micro_point(x, y, config)
    world_x = (x / micro_grid_size - macro_grid_size / 2) * world_scale
    world_y = (y / micro_grid_size - macro_grid_size / 2) * world_scale
    return round(world_x, 4), round(world_y, 4)


def distort_micro_point(x: float, y: float, config: RoadGenerationConfig) -> tuple[float, float]:
    """Distort micro-grid graph points after topology solidification.

    Agent growth remains integer-grid and orthogonal. This function implements
    the second 1.md phase: continuous noise displacement plus radial historic
    center compression, without changing graph connectivity.
    """

    nx = smooth_noise(x * config.noise.scale, y * config.noise.scale, config.seed)
    ny = smooth_noise(x * config.noise.scale + 1000, y * config.noise.scale + 1000, config.seed)
    distorted_x = x + nx * config.noise.strength
    distorted_y = y + ny * config.noise.strength

    center = config.historic_center
    dx = center.center_x - distorted_x
    dy = center.center_y - distorted_y
    distance = math.hypot(dx, dy)
    if distance > 0:
        influence = 1 - max(0.0, min(1.0, distance / center.radius))
        force = influence * center.strength
        distorted_x += (dx / distance) * force * distance
        distorted_y += (dy / distance) * force * distance

    return distorted_x, distorted_y


def micro_graph_to_world_graph(
    graph: dict[str, Any],
    macro_grid_size: int,
    micro_grid_size: int,
    config: RoadGenerationConfig | None = None,
    distort: bool = False,
    warped_vertices: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    converted = json.loads(json.dumps(graph))
    id_map: dict[str, tuple[float, float]] = {}
    for node in converted["nodes"]:
        node["gridX"] = node["originalX"]
        node["gridY"] = node["originalY"]
        if distort and warped_vertices is not None:
            warped = warped_vertices[point_key((int(node["gridX"]), int(node["gridY"])))]
            node["x"], node["y"] = warped["x"], warped["y"]
        else:
            node["x"], node["y"] = micro_point_to_world(
                node,
                macro_grid_size=macro_grid_size,
                micro_grid_size=micro_grid_size,
                config=config,
                distort=distort,
            )
        id_map[node["id"]] = (node["x"], node["y"])

    for edge in converted["edges"]:
        edge["points"] = []
        for point in edge.get("points", []):
            if distort and warped_vertices is not None:
                warped = warped_vertices[point_key((int(point["x"]), int(point["y"])))]
                edge["points"].append({"x": warped["x"], "y": warped["y"]})
            else:
                edge["points"].append(
                    dict(
                        zip(
                            ("x", "y"),
                            micro_point_to_world(
                                point,
                                macro_grid_size=macro_grid_size,
                                micro_grid_size=micro_grid_size,
                                config=config,
                                distort=distort,
                            ),
                        )
                    )
                )
        if not edge["points"]:
            edge["points"] = [
                {"x": id_map[edge["source"]][0], "y": id_map[edge["source"]][1]},
                {"x": id_map[edge["target"]][0], "y": id_map[edge["target"]][1]},
            ]
    return converted


def config_to_dict(config: RoadGenerationConfig) -> dict[str, Any]:
    return asdict(config)


def write_graph_json(graph: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(graph, file, ensure_ascii=False, indent=2)
        file.write("\n")


def road_graph_to_blender_roads(
    graph: dict[str, Any],
    z_lookup: Any | None = None,
    start_id: int = 1,
) -> list[dict[str, Any]]:
    roads: list[dict[str, Any]] = []
    level_by_type = {
        "main_road": "primary",
        "block_splitter": "secondary",
        "secondary_road": "secondary",
        "alley": "alley",
    }
    for index, edge in enumerate(graph["edges"], start=start_id):
        points = []
        for point in edge.get("points", []):
            x = float(point["x"])
            y = float(point["y"])
            z = float(z_lookup(x, y)) if z_lookup is not None else 0.0
            points.append([round(x, 4), round(y, 4), round(z + 0.018, 4)])
        if len(points) < 2:
            continue
        roads.append(
            {
                "id": index,
                "level": level_by_type.get(edge.get("type"), "alley"),
                "width": edge.get("width", 0.07),
                "points": points,
            }
        )
    return roads


def write_debug_svg(
    graph: dict[str, Any],
    output_path: Path,
    title: str,
    raw_segments: dict[Segment, str] | None = None,
    world_scale: float = 1.0,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width = 900
    height = 900
    margin = 48

    points: list[tuple[float, float]] = []
    if raw_segments is not None:
        for start, end in raw_segments:
            points.extend(
                [
                    (float(start[0]) * world_scale, float(start[1]) * world_scale),
                    (float(end[0]) * world_scale, float(end[1]) * world_scale),
                ]
            )
    else:
        points.extend((float(node["x"]), float(node["y"])) for node in graph["nodes"])
        for edge in graph["edges"]:
            points.extend((float(point["x"]), float(point["y"])) for point in edge.get("points", []))

    min_x = min((point[0] for point in points), default=-1.0)
    max_x = max((point[0] for point in points), default=1.0)
    min_y = min((point[1] for point in points), default=-1.0)
    max_y = max((point[1] for point in points), default=1.0)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    scale = min((width - margin * 2) / span_x, (height - margin * 2) / span_y)

    def project(x: float, y: float) -> tuple[float, float]:
        px = margin + (x - min_x) * scale
        py = height - margin - (y - min_y) * scale
        return px, py

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f5ef"/>',
        f'<text x="24" y="28" font-family="Arial" font-size="16" font-weight="700" fill="#222">{title}</text>',
    ]

    if raw_segments is not None:
        for (start, end), road_type in raw_segments.items():
            x1, y1 = project(float(start[0]) * world_scale, float(start[1]) * world_scale)
            x2, y2 = project(float(end[0]) * world_scale, float(end[1]) * world_scale)
            color = "#665847" if road_type == "main_road" else "#9a8a73"
            stroke_width = 3 if road_type == "main_road" else 1.5
            lines.append(
                f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round"/>'
            )
    else:
        for edge in graph["edges"]:
            edge_points = edge.get("points") or []
            if len(edge_points) < 2:
                source = next(node for node in graph["nodes"] if node["id"] == edge["source"])
                target = next(node for node in graph["nodes"] if node["id"] == edge["target"])
                edge_points = [source, target]
            projected = [project(float(point["x"]), float(point["y"])) for point in edge_points]
            path_data = " ".join(
                ("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}"
                for index, (x, y) in enumerate(projected)
            )
            color = "#665847" if edge.get("type") == "main_road" else "#9a8a73"
            stroke_width = 3 if edge.get("type") == "main_road" else 1.5
            lines.append(
                f'<path d="{path_data}" fill="none" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round"/>'
            )

        for node in graph["nodes"]:
            x, y = project(float(node["x"]), float(node["y"]))
            node_type = node.get("type")
            radius = 3.6 if node_type == "intersection" else (2.8 if node_type == "dead_end" else 2.0)
            color = "#b25d3d" if node_type == "intersection" else ("#3f6f8f" if node_type == "dead_end" else "#333")
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{color}" opacity="0.9"/>')

    lines.append("</svg>")
    with output_path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))
        file.write("\n")


def write_debug_artifacts(result: dict[str, Any], output_dir: Path) -> None:
    write_graph_json(result["distorted_graph"], output_dir / "road_graph_agent.json")
    write_debug_svg(
        result["graph"],
        output_dir / "road_graph_agent_raw.svg",
        "Agent Road Network - Raw Grid",
        raw_segments=result["raw"]["segments"],
        world_scale=result["distorted_graph"]["metadata"]["config"]["world"]["scale"],
    )
    write_debug_svg(result["graph"], output_dir / "road_graph_agent_graph.svg", "Agent Road Network - Graph")
    write_debug_svg(
        result["distorted_graph"],
        output_dir / "road_graph_agent_distorted.svg",
        "Agent Road Network - Distorted",
    )


def validate_generation(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    raw_segments = result["raw"]["segments"]
    for start, end in raw_segments:
        if not all(isinstance(value, int) for value in (*start, *end)):
            errors.append("raw segment contains non-integer coordinate")
        if start[0] != end[0] and start[1] != end[1]:
            errors.append("raw segment is not orthogonal")

    graph = result["graph"]
    node_ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            errors.append(f"edge {edge['id']} references a missing node")

    node_types = {node["type"] for node in graph["nodes"]}
    if "intersection" not in node_types:
        errors.append("graph has no intersections")
    if "dead_end" not in node_types:
        errors.append("graph has no dead ends")

    edge_types = {edge["type"] for edge in graph["edges"]}
    if "main_road" not in edge_types or "alley" not in edge_types:
        errors.append("graph must include main-road and alley edges")

    distorted = result["distorted_graph"]
    if len(graph["nodes"]) != len(distorted["nodes"]):
        errors.append("distortion changed node count")
    if len(graph["edges"]) != len(distorted["edges"]):
        errors.append("distortion changed edge count")
    for before, after in zip(graph["edges"], distorted["edges"]):
        if before["source"] != after["source"] or before["target"] != after["target"]:
            errors.append(f"distortion changed edge connectivity for {before['id']}")
    if not any(
        not float(node["x"]).is_integer() or not float(node["y"]).is_integer()
        for node in distorted["nodes"]
    ):
        errors.append("distortion did not create any non-integer node coordinates")

    return sorted(set(errors))


def build_config_for_macro_grid(
    macro_grid: dict[str, Any] | None,
    selected_macro_keys: set[tuple[Any, Any]] | None = None,
    seed: int = 42,
) -> RoadGenerationConfig:
    if macro_grid is None or not macro_grid.get("cells"):
        return RoadGenerationConfig(seed=seed)

    if selected_macro_keys:
        cells = [
            cell for cell in macro_grid["cells"]
            if (cell.get("x"), cell.get("y")) in selected_macro_keys
        ]
    else:
        cells = macro_grid["cells"]
    if not cells:
        cells = macro_grid["cells"]

    padding = 7
    grid_size = float(macro_grid.get("metadata", {}).get("grid_size", 15))
    grid_offset = grid_size / 2
    min_x = math.floor(min(float(cell["x"]) for cell in cells) - grid_offset - padding)
    max_x = math.ceil(max(float(cell["x"]) for cell in cells) - grid_offset + 1 + padding)
    min_y = math.floor(min(float(cell["y"]) for cell in cells) - grid_offset - padding)
    max_y = math.ceil(max(float(cell["y"]) for cell in cells) - grid_offset + 1 + padding)
    span = max(max_x - min_x, max_y - min_y, 4)
    radius = max(8.0, span * 0.7)
    main_count = 8 if span >= 24 else 6
    return RoadGenerationConfig(
        seed=seed,
        bounds=Bounds(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y),
        main_road=MainRoadConfig(count=main_count, min_life=70, max_life=150),
        alley=AlleyConfig(min_life=12, max_life=42, spawn_probability_from_main_road=0.28),
        historic_center=HistoricCenterConfig(radius=radius),
        world=WorldScaleConfig(scale=1.8),
    )


if __name__ == "__main__":
    generation = generate_medieval_road_network()
    issues = validate_generation(generation)
    if issues:
        raise SystemExit("\n".join(issues))
    write_debug_artifacts(generation, Path("output"))
    print(
        "Generated agent road network: "
        f"{len(generation['distorted_graph']['nodes'])} nodes, "
        f"{len(generation['distorted_graph']['edges'])} edges."
    )
