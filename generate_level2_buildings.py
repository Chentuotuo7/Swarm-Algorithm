import csv
import json
import math
import random
import sys
from pathlib import Path

from shapely.geometry import LineString, Point as ShapelyPoint, Polygon
from shapely.ops import polygonize, unary_union


SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ca_level2_rules as rules
import generate_city_grid as base
from blender_generator import agent_road_network


OUTPUT_DIR = SCRIPT_DIR / "output"
SOURCE_MACRO_JSON = OUTPUT_DIR / f"city_grid_{base.GRID_SIZE}x{base.GRID_SIZE}_scheme2.json"
BUILDING_JSON = OUTPUT_DIR / "city_buildings_scheme2.json"
BUILDING_CSV = OUTPUT_DIR / "city_buildings_scheme2.csv"
TREE_CSV = OUTPUT_DIR / "city_trees_scheme2.csv"
MICRO_GRID_SIZE = rules.MICRO_GRID_SIZE
MICRO_GRID_LABEL = f"{base.GRID_SIZE * MICRO_GRID_SIZE}x{base.GRID_SIZE * MICRO_GRID_SIZE}"
MICRO_SVG = OUTPUT_DIR / f"meso_ca_level2_{MICRO_GRID_LABEL}_scheme2.svg"
ROAD_VALIDATION_SVG = OUTPUT_DIR / f"road_parcel_validation_{MICRO_GRID_LABEL}.svg"
FLOOR_HEIGHT = 0.32
BUILDING_FOOTPRINT_SCALE = 0.86
TOWER_FOOTPRINT_SCALE = 1.35
TREE_BASE_SCALE = 0.10
MAX_CELL_FOOTPRINT_SCALE = 0.96
WORLD_SCALE = agent_road_network.MICRO_ROAD_WORLD_SCALE
WORLD_AREA_SCALE = WORLD_SCALE * WORLD_SCALE
PARCEL_MIN_AREA = 0.035 * WORLD_AREA_SCALE
PARCEL_MIN_COMPACTNESS = 0.018
PARCEL_BUILDING_SCALE = 0.78
PARCEL_TOWER_SCALE = 0.66
PARCEL_TREE_DENSITY = 6.0
LARGE_OPEN_PARCEL_AREA = 6.0 * WORLD_AREA_SCALE
MAX_PARCEL_SUBSTRATE_CELLS = 48
MAX_LARGE_PARCEL_SPLIT_ITERATIONS = 8
MAX_LARGE_PARCEL_SPLITTERS_PER_ITERATION = 8
MIN_SPLITTER_SEGMENTS = 2
MIN_SPLITTER_LINE_SPACING = 4
EDGE_GREENBELT_DISTANCE_CELLS = 2
EDGE_GREENBELT_MAX_SUBSTRATE_CELLS = 40
EDGE_GREENBELT_ELONGATION = 2.5
MIN_MERGE_SUBSTRATE_CELLS = 3
MIN_BUILDING_SUBSTRATE_CELLS = 16
MIN_TOWER_SUBSTRATE_CELLS = 12
MIN_TOWER_BUILDING_CLUSTER_CELLS = 7
PARCEL_CA_ITERATIONS = rules.MICRO_CA_ITERATIONS
PARCEL_RANDOM_SEED = rules.MICRO_RANDOM_SEED + 17000
PARCEL_MICRO_BUILDING_SCALE = 0.58
PARCEL_MICRO_PATH_EDGE_BIAS = 0.18
PARCEL_MICRO_COURTYARD_EDGE_BIAS = 0.14
PARCEL_TOWER_PROBABILITY_BY_STATE = {
    2: 0.45,
    3: 0.85,
    4: 1.0,
}


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


def sample_scaled_terrain_height(centered_x, centered_y, world_scale=WORLD_SCALE, grid_size=base.GRID_SIZE):
    """Sample the source terrain height from scaled centered world coordinates."""

    source_x = centered_x / world_scale + grid_size / 2
    source_y = centered_y / world_scale + grid_size / 2
    return base.get_height(source_x, source_y, grid_size)


def polygon_center(points):
    return {
        "x": round(sum(point["x"] for point in points) / len(points), 4),
        "y": round(sum(point["y"] for point in points) / len(points), 4),
    }


def polygon_edge_lengths(points):
    lengths = []
    for start, end in zip(points, points[1:] + points[:1]):
        lengths.append(math.hypot(end["x"] - start["x"], end["y"] - start["y"]))
    return lengths


def scale_polygon(points, scale):
    center = polygon_center(points)
    safe_scale = min(scale, MAX_CELL_FOOTPRINT_SCALE)
    return [
        {
            "x": round(center["x"] + (point["x"] - center["x"]) * safe_scale, 4),
            "y": round(center["y"] + (point["y"] - center["y"]) * safe_scale, 4),
        }
        for point in points
    ]


def get_warped_vertex(warped_vertices, gx, gy):
    vertex = warped_vertices[f"{gx},{gy}"]
    return {"x": vertex["x"], "y": vertex["y"]}


def get_warped_cell_geometry(warped_vertices, global_x, global_y):
    corners = [
        get_warped_vertex(warped_vertices, global_x, global_y),
        get_warped_vertex(warped_vertices, global_x + 1, global_y),
        get_warped_vertex(warped_vertices, global_x + 1, global_y + 1),
        get_warped_vertex(warped_vertices, global_x, global_y + 1),
    ]
    center = polygon_center(corners)
    center["z"] = round(sample_scaled_terrain_height(center["x"], center["y"]), 4)
    return {"corners": corners, "center": center}


def fallback_width_depth_from_polygon(points, scale=1.0):
    if len(points) != 4:
        xs = [point["x"] for point in points]
        ys = [point["y"] for point in points]
        return round((max(xs) - min(xs)) * scale, 4), round((max(ys) - min(ys)) * scale, 4)
    bottom, right, top, left = polygon_edge_lengths(points[:4])
    width = ((bottom + top) / 2) * scale
    depth = ((right + left) / 2) * scale
    return round(width, 4), round(depth, 4)


def point_to_macro_cell(point, macro_lookup):
    macro_x = int(max(0, min(base.GRID_SIZE - 1, math.floor(point["x"] + base.GRID_SIZE / 2))))
    macro_y = int(max(0, min(base.GRID_SIZE - 1, math.floor(point["y"] + base.GRID_SIZE / 2))))
    return macro_lookup[(macro_x, macro_y)]


def geom_length(geometry):
    if geometry.is_empty:
        return 0.0
    return float(getattr(geometry, "length", 0.0))


def road_segment_line(segment, warped_vertices):
    (start_x, start_y), (end_x, end_y) = segment
    start = warped_vertices[f"{start_x},{start_y}"]
    end = warped_vertices[f"{end_x},{end_y}"]
    return LineString([(start["x"], start["y"]), (end["x"], end["y"])])


def build_road_lines(road_result):
    return [
        (road_segment_line(segment, road_result["warped_vertices"]), road_type)
        for segment, road_type in road_result["road_segments"].items()
    ]


def build_polygonize_boundary_lines(road_result, macro_grid):
    total_grid_size = int(macro_grid["metadata"]["grid_size"]) * MICRO_GRID_SIZE
    boundary_segments = []
    for gx in range(total_grid_size):
        boundary_segments.append(((gx, 0), (gx + 1, 0)))
        boundary_segments.append(((gx, total_grid_size), (gx + 1, total_grid_size)))
    for gy in range(total_grid_size):
        boundary_segments.append(((0, gy), (0, gy + 1)))
        boundary_segments.append(((total_grid_size, gy), (total_grid_size, gy + 1)))
    return [
        road_segment_line(agent_road_network.segment_key(start, end), road_result["warped_vertices"])
        for start, end in boundary_segments
    ]


def polygon_to_points(polygon):
    coordinates = list(polygon.exterior.coords)[:-1]
    return [{"x": round(float(x), 4), "y": round(float(y), 4)} for x, y in coordinates]


def polygon_compactness(polygon):
    perimeter = polygon.length
    if perimeter <= 0:
        return 0.0
    return float(4 * math.pi * polygon.area / (perimeter * perimeter))


def calculate_road_adjacency(polygon, road_lines):
    boundary = polygon.boundary
    road_lengths = {"main_road": 0.0, "block_splitter": 0.0, "secondary_road": 0.0, "alley": 0.0}
    for line, road_type in road_lines:
        road_lengths[road_type] = road_lengths.get(road_type, 0.0) + geom_length(boundary.intersection(line))
    secondary_length = road_lengths.get("block_splitter", 0.0) + road_lengths.get("secondary_road", 0.0)
    if road_lengths.get("main_road", 0.0) >= max(secondary_length, road_lengths.get("alley", 0.0)):
        dominant_road = "main_road"
    elif secondary_length >= road_lengths.get("alley", 0.0):
        dominant_road = "secondary_road"
    else:
        dominant_road = "alley"
    return dominant_road, round(sum(road_lengths.values()), 4)


def create_parcel_from_polygon(parcel_id, polygon, macro_lookup, road_lines, merged_from=None):
    center = polygon.representative_point()
    center_point = {"x": round(center.x, 4), "y": round(center.y, 4)}
    macro_cell = point_to_macro_cell(center_point, macro_lookup)
    dominant_road, road_boundary_length = calculate_road_adjacency(polygon, road_lines)
    return {
        "id": parcel_id,
        "polygon": polygon_to_points(polygon),
        "_shape": polygon,
        "center": center_point,
        "area": round(float(polygon.area), 4),
        "perimeter": round(float(polygon.length), 4),
        "compactness": round(polygon_compactness(polygon), 4),
        "road_adjacency": dominant_road,
        "road_boundary_length": road_boundary_length,
        "touches_city_edge": False,
        "edge_distance_cells": None,
        "edge_greenbelt": False,
        "macro_x": macro_cell["x"],
        "macro_y": macro_cell["y"],
        "macro_state": macro_cell["state"],
        "density": macro_cell["density"],
        "merged_from": merged_from or [parcel_id],
        "_macro_cell": macro_cell,
    }


def create_substrate_cells(road_result, macro_grid):
    total_grid_size = int(macro_grid["metadata"]["grid_size"]) * MICRO_GRID_SIZE
    road_cells = road_result["road_cells"]
    cells = []
    for global_y in range(total_grid_size):
        for global_x in range(total_grid_size):
            cell_geometry = get_warped_cell_geometry(road_result["warped_vertices"], global_x, global_y)
            center = cell_geometry["center"]
            macro_x = global_x // MICRO_GRID_SIZE
            macro_y = global_y // MICRO_GRID_SIZE
            micro_x = global_x % MICRO_GRID_SIZE
            micro_y = global_y % MICRO_GRID_SIZE
            is_road_reserved = (global_x, global_y) in road_cells
            cells.append(
                {
                    "id": f"{global_x},{global_y}",
                    "macro_x": macro_x,
                    "macro_y": macro_y,
                    "micro_x": micro_x,
                    "micro_y": micro_y,
                    "global_x": global_x,
                    "global_y": global_y,
                    "x": center["x"],
                    "y": center["y"],
                    "z": center["z"],
                    "state": rules.MICRO_PATH if is_road_reserved else rules.MICRO_EMPTY,
                    "is_road_reserved": is_road_reserved,
                    "is_road_adjacent": is_road_reserved,
                    "parcel_id": None,
                    "corners": cell_geometry["corners"],
                    "_shape": Polygon([(point["x"], point["y"]) for point in cell_geometry["corners"]]),
                }
            )
    return cells


def assign_substrate_to_parcels(parcels, substrate_cells):
    for parcel in parcels:
        parcel["substrate_cell_ids"] = []
        parcel["_substrate_cell_ids"] = []
    for cell in substrate_cells:
        cell["parcel_id"] = None
        point = ShapelyPoint(cell["x"], cell["y"])
        for parcel in parcels:
            if parcel["_shape"].covers(point):
                cell["parcel_id"] = parcel["id"]
                parcel["_substrate_cell_ids"].append(cell["id"])
                parcel["substrate_cell_ids"].append(cell["id"])
                break
    for parcel in parcels:
        count = len(parcel["_substrate_cell_ids"])
        parcel["substrate_cell_count"] = count
        parcel["substrate_area_estimate"] = round(count / (MICRO_GRID_SIZE * MICRO_GRID_SIZE), 4)
        parcel["buildable_width_hint"] = round(math.sqrt(count) / MICRO_GRID_SIZE, 4) if count else 0.0


def annotate_edge_context(parcels, total_grid_size):
    for parcel in parcels:
        bounds = substrate_bounds_for_parcel(parcel)
        if bounds is None:
            parcel["touches_city_edge"] = False
            parcel["edge_distance_cells"] = None
            parcel["edge_greenbelt"] = False
            continue
        min_x, max_x, min_y, max_y = bounds
        edge_distance = min(min_x, min_y, total_grid_size - 1 - max_x, total_grid_size - 1 - max_y)
        span_x = max_x - min_x + 1
        span_y = max_y - min_y + 1
        short_span = max(1, min(span_x, span_y))
        elongation = max(span_x, span_y) / short_span
        count = parcel.get("substrate_cell_count", 0)
        edge_greenbelt = (
            edge_distance <= EDGE_GREENBELT_DISTANCE_CELLS
            and (
                count <= EDGE_GREENBELT_MAX_SUBSTRATE_CELLS
                or elongation >= EDGE_GREENBELT_ELONGATION
            )
        )
        parcel["touches_city_edge"] = edge_distance == 0
        parcel["edge_distance_cells"] = edge_distance
        parcel["edge_greenbelt"] = edge_greenbelt


def reindex_parcels(parcels):
    for index, parcel in enumerate(parcels, start=1):
        old_id = parcel["id"]
        parcel["id"] = index
        if not parcel.get("merged_from"):
            parcel["merged_from"] = [old_id]


def merge_small_parcels(parcels, substrate_cells, macro_lookup, road_lines, total_grid_size):
    merged_count = 0
    while True:
        assign_substrate_to_parcels(parcels, substrate_cells)
        small = [
            parcel for parcel in parcels
            if parcel["substrate_cell_count"] < MIN_MERGE_SUBSTRATE_CELLS
        ]
        if not small:
            break
        source = min(small, key=lambda parcel: (parcel["substrate_cell_count"], parcel["area"]))
        best_target = None
        best_score = None
        for candidate in parcels:
            if candidate is source:
                continue
            shared_length = geom_length(source["_shape"].boundary.intersection(candidate["_shape"].boundary))
            if shared_length <= 0.006:
                continue
            same_macro = (
                source["macro_state"] == candidate["macro_state"]
                and source["density"] == candidate["density"]
            )
            score = (
                1 if same_macro else 0,
                shared_length,
                candidate.get("substrate_cell_count", 0),
                candidate["area"],
            )
            if best_score is None or score > best_score:
                best_score = score
                best_target = candidate
        if best_target is None:
            source["force_non_buildable"] = True
            source["buildability_reason"] = "too_small_unmerged"
            break
        merged_shape = unary_union([source["_shape"], best_target["_shape"]])
        if merged_shape.geom_type != "Polygon":
            source["force_non_buildable"] = True
            source["buildability_reason"] = "too_small_multipolygon_merge_skipped"
            break
        merged_from = sorted(set(source.get("merged_from", [source["id"]]) + best_target.get("merged_from", [best_target["id"]])))
        updated = create_parcel_from_polygon(best_target["id"], merged_shape, macro_lookup, road_lines, merged_from=merged_from)
        best_target.clear()
        best_target.update(updated)
        parcels.remove(source)
        merged_count += 1
    reindex_parcels(parcels)
    assign_substrate_to_parcels(parcels, substrate_cells)
    annotate_edge_context(parcels, total_grid_size)
    return merged_count


def apply_buildability(parcels):
    buildable_count = 0
    for parcel in parcels:
        reason = parcel.get("buildability_reason")
        buildable = False
        if parcel.get("force_non_buildable"):
            reason = reason or "forced_non_buildable"
        elif parcel.get("edge_greenbelt"):
            reason = "edge_greenbelt"
        elif parcel["area"] > LARGE_OPEN_PARCEL_AREA:
            reason = "large_open_parcel"
        elif parcel["substrate_cell_count"] < MIN_BUILDING_SUBSTRATE_CELLS:
            reason = "substrate_count_below_building_threshold"
        elif parcel["compactness"] < PARCEL_MIN_COMPACTNESS:
            reason = "compactness_below_threshold"
        else:
            buildable = True
            reason = "buildable"
            buildable_count += 1
        parcel["buildable"] = buildable
        parcel["tower_eligible"] = (
            buildable
            and parcel["substrate_cell_count"] >= MIN_TOWER_SUBSTRATE_CELLS
            and parcel["area"] <= LARGE_OPEN_PARCEL_AREA
        )
        parcel["buildability_reason"] = reason
    return buildable_count


def extract_road_parcels(road_result, macro_grid):
    macro_lookup = {
        (int(cell["x"]), int(cell["y"])): cell
        for cell in macro_grid["cells"]
    }
    road_lines = build_road_lines(road_result)
    polygonize_lines = [line for line, _ in road_lines] + build_polygonize_boundary_lines(road_result, macro_grid)
    merged_lines = unary_union(polygonize_lines)
    raw_polygons = list(polygonize(merged_lines))
    parcels = []

    for polygon in raw_polygons:
        if polygon.area < PARCEL_MIN_AREA:
            continue
        if polygon_compactness(polygon) < PARCEL_MIN_COMPACTNESS:
            continue
        parcels.append(create_parcel_from_polygon(len(parcels) + 1, polygon, macro_lookup, road_lines))

    return parcels


def substrate_bounds_for_parcel(parcel):
    coordinates = []
    for cell_id in parcel.get("_substrate_cell_ids", []):
        gx, gy = cell_id.split(",", 1)
        coordinates.append((int(gx), int(gy)))
    if not coordinates:
        return None
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    return min(xs), max(xs), min(ys), max(ys)


def segment_inside_parcel(segment, warped_vertices, polygon):
    line = road_segment_line(segment, warped_vertices)
    if polygon.covers(line.interpolate(0.5, normalized=True)):
        return True
    return geom_length(line.intersection(polygon)) >= line.length * 0.55


def longest_contiguous_segments(segments):
    if not segments:
        return []
    runs = []
    current = [segments[0]]
    previous = segments[0]
    for segment in segments[1:]:
        if previous[1] == segment[0]:
            current.append(segment)
        else:
            runs.append(current)
            current = [segment]
        previous = segment
    runs.append(current)
    return max(runs, key=len)


def face_aware_splitter_segments(parcel, axis, coordinate, bounds, road_segments, warped_vertices):
    min_x, max_x, min_y, max_y = bounds
    candidates = []
    if axis == "vertical":
        coordinate = max(min_x + 1, min(max_x, coordinate))
        for gy in range(min_y, max_y + 1):
            candidates.append(agent_road_network.segment_key((coordinate, gy), (coordinate, gy + 1)))
    else:
        coordinate = max(min_y + 1, min(max_y, coordinate))
        for gx in range(min_x, max_x + 1):
            candidates.append(agent_road_network.segment_key((gx, coordinate), (gx + 1, coordinate)))

    inside = [
        segment for segment in candidates
        if segment not in road_segments
        and segment_inside_parcel(segment, warped_vertices, parcel["_shape"])
    ]
    inside = longest_contiguous_segments(inside)
    if len(inside) < MIN_SPLITTER_SEGMENTS:
        return {}
    return {segment: "block_splitter" for segment in inside}


def ranges_overlap(first_min, first_max, second_min, second_max):
    return max(first_min, second_min) <= min(first_max, second_max)


def too_close_to_existing_splitter(axis, coordinate, bounds, road_segments):
    min_x, max_x, min_y, max_y = bounds
    for (start, end), road_type in road_segments.items():
        if road_type not in {"block_splitter", "secondary_road"}:
            continue
        if axis == "vertical" and start[0] == end[0]:
            if abs(start[0] - coordinate) < MIN_SPLITTER_LINE_SPACING and ranges_overlap(
                min_y,
                max_y + 1,
                min(start[1], end[1]),
                max(start[1], end[1]),
            ):
                return True
        elif axis == "horizontal" and start[1] == end[1]:
            if abs(start[1] - coordinate) < MIN_SPLITTER_LINE_SPACING and ranges_overlap(
                min_x,
                max_x + 1,
                min(start[0], end[0]),
                max(start[0], end[0]),
            ):
                return True
    return False


def propose_large_parcel_splitters(parcels, road_segments, total_grid_size, warped_vertices):
    added = {}
    used_lines = set()
    large_parcels = [
        parcel for parcel in parcels
        if parcel.get("substrate_cell_count", 0) > MAX_PARCEL_SUBSTRATE_CELLS
    ]
    large_parcels.sort(key=lambda parcel: parcel["substrate_cell_count"], reverse=True)

    for parcel in large_parcels[:MAX_LARGE_PARCEL_SPLITTERS_PER_ITERATION]:
        bounds = substrate_bounds_for_parcel(parcel)
        if bounds is None:
            continue
        min_x, max_x, min_y, max_y = bounds
        span_x = max_x - min_x + 1
        span_y = max_y - min_y + 1
        line_options = []
        if span_x > 1:
            line_options.append(("vertical", round((min_x + max_x + 1) / 2), span_x))
        if span_y > 1:
            line_options.append(("horizontal", round((min_y + max_y + 1) / 2), span_y))
        if parcel["substrate_cell_count"] > MAX_PARCEL_SUBSTRATE_CELLS * 3:
            if span_x >= span_y and span_x > 16:
                line_options.append(("vertical", round(min_x + span_x / 3), span_x))
                line_options.append(("vertical", round(min_x + span_x * 2 / 3), span_x))
            elif span_y > 16:
                line_options.append(("horizontal", round(min_y + span_y / 3), span_y))
                line_options.append(("horizontal", round(min_y + span_y * 2 / 3), span_y))
        line_options.sort(key=lambda option: option[2], reverse=True)

        for axis, coordinate, _span in line_options:
            if len(used_lines) >= MAX_LARGE_PARCEL_SPLITTERS_PER_ITERATION:
                break
            coordinate = max(1, min(total_grid_size - 1, coordinate))
            line_key = (axis, coordinate, parcel["id"])
            if line_key in used_lines:
                continue
            if too_close_to_existing_splitter(axis, coordinate, bounds, road_segments):
                continue
            used_lines.add(line_key)
            candidates = face_aware_splitter_segments(
                parcel,
                axis,
                coordinate,
                bounds,
                road_segments,
                warped_vertices,
            )
            new_segments = {
                segment: road_type
                for segment, road_type in candidates.items()
                if segment not in road_segments and segment not in added
            }
            if len(new_segments) < 2:
                continue
            added.update(new_segments)

    return added


def split_large_road_parcels(road_result, macro_grid):
    total_grid_size = int(macro_grid["metadata"]["grid_size"]) * MICRO_GRID_SIZE
    split_iterations = 0
    split_segments = 0
    max_before = 0
    max_after = 0

    for iteration in range(MAX_LARGE_PARCEL_SPLIT_ITERATIONS + 1):
        substrate_cells = create_substrate_cells(road_result, macro_grid)
        parcels = extract_road_parcels(road_result, macro_grid)
        assign_substrate_to_parcels(parcels, substrate_cells)
        annotate_edge_context(parcels, total_grid_size)
        current_max = max((parcel.get("substrate_cell_count", 0) for parcel in parcels), default=0)
        if iteration == 0:
            max_before = current_max
        max_after = current_max
        if current_max <= MAX_PARCEL_SUBSTRATE_CELLS or iteration >= MAX_LARGE_PARCEL_SPLIT_ITERATIONS:
            break

        added_segments = propose_large_parcel_splitters(
            parcels,
            road_result["road_segments"],
            total_grid_size,
            road_result["warped_vertices"],
        )
        if not added_segments:
            break
        road_result = agent_road_network.rebuild_micro_road_result(
            road_result,
            macro_grid,
            MICRO_GRID_SIZE,
            added_segments=added_segments,
        )
        split_iterations += 1
        split_segments += len(added_segments)

    road_result["distorted_graph"].setdefault("metadata", {}).update(
        {
            "large_parcel_split_iterations": split_iterations,
            "large_parcel_split_segments": split_segments,
            "max_parcel_substrate_cells_before_split": max_before,
            "max_parcel_substrate_cells_after_split": max_after,
            "max_parcel_substrate_cells_target": MAX_PARCEL_SUBSTRATE_CELLS,
        }
    )
    return road_result


def build_parcel_adjacency(parcels):
    adjacency = {parcel["id"]: set() for parcel in parcels}
    for index, parcel in enumerate(parcels):
        shape = parcel["_shape"]
        for other in parcels[index + 1:]:
            shared = shape.boundary.intersection(other["_shape"].boundary)
            if geom_length(shared) > 0.006:
                adjacency[parcel["id"]].add(other["id"])
                adjacency[other["id"]].add(parcel["id"])
    return adjacency


def parcel_center_score(parcel):
    center = parcel["center"]
    distance = math.hypot(center["x"], center["y"])
    max_distance = math.hypot(base.GRID_SIZE / 2, base.GRID_SIZE / 2)
    return 1.0 - min(1.0, distance / max_distance)


def initialize_parcel_states(parcels):
    states = {}
    for parcel in parcels:
        macro_cell = parcel["_macro_cell"]
        macro_state = macro_cell["state"]
        params = rules.MACRO_PARAMS[macro_state]
        rng = random.Random(PARCEL_RANDOM_SEED + parcel["id"] * 1009)
        area = parcel["area"]
        center_bonus = parcel_center_score(parcel) * 0.16
        road_bonus = 0.12 if parcel["road_adjacency"] == "main_road" else 0.07 if parcel["road_adjacency"] == "secondary_road" else 0.04
        area_bonus = min(0.18, max(0.0, area - 0.12) * 0.18)
        noise = rules.stable_noise(parcel["center"]["x"], parcel["center"]["y"], seed=PARCEL_RANDOM_SEED)

        if parcel.get("edge_greenbelt", False):
            roll = rng.random()
            if roll < 0.68:
                states[parcel["id"]] = rules.MICRO_TREE
            elif roll < 0.90:
                states[parcel["id"]] = rules.MICRO_COURTYARD
            else:
                states[parcel["id"]] = rules.MICRO_EMPTY
            continue
        if not parcel.get("buildable", False):
            if macro_state == 0 or parcel["substrate_cell_count"] < MIN_MERGE_SUBSTRATE_CELLS:
                states[parcel["id"]] = rules.MICRO_TREE if rng.random() < 0.45 else rules.MICRO_EMPTY
            else:
                states[parcel["id"]] = rules.MICRO_COURTYARD if rng.random() < 0.62 else rules.MICRO_TREE
            continue
        if area > LARGE_OPEN_PARCEL_AREA:
            states[parcel["id"]] = rules.MICRO_TREE if macro_state == 0 else rules.MICRO_COURTYARD
            continue
        if macro_state == 0:
            states[parcel["id"]] = rules.MICRO_TREE if rng.random() < 0.70 else rules.MICRO_EMPTY
            continue
        if macro_state == 5:
            states[parcel["id"]] = rules.MICRO_COURTYARD if rng.random() < 0.72 else rules.MICRO_TREE
            continue
        if macro_state == 4 and parcel.get("tower_eligible", False):
            states[parcel["id"]] = rules.MICRO_TOWER
            continue

        tree_probability = min(0.18, params["tree_probability"] * 0.45)
        courtyard_probability = min(0.18, params["path_probability"] * 0.35)
        building_probability = params["building_coverage"] + center_bonus + road_bonus + area_bonus + (noise - 0.5) * 0.10
        building_probability = min(0.78, max(0.46, building_probability))
        roll = rng.random()
        if roll < tree_probability:
            state = rules.MICRO_TREE
        elif roll < tree_probability + courtyard_probability:
            state = rules.MICRO_COURTYARD
        elif roll < tree_probability + courtyard_probability + building_probability:
            state = rules.MICRO_BUILDING
        else:
            state = rules.MICRO_EMPTY
        if macro_state in (2, 3) and parcel.get("tower_eligible", False) and rng.random() < params["tower_probability"]:
            state = rules.MICRO_TOWER
        states[parcel["id"]] = state
    return states


def evolve_parcel_states(parcels, adjacency, states):
    rng = random.Random(PARCEL_RANDOM_SEED + 3000)
    for _ in range(PARCEL_CA_ITERATIONS):
        next_states = {}
        for parcel in parcels:
            parcel_id = parcel["id"]
            current = states[parcel_id]
            neighbor_states = [states[neighbor_id] for neighbor_id in adjacency[parcel_id]]
            building_neighbors = sum(1 for state in neighbor_states if state in (rules.MICRO_BUILDING, rules.MICRO_TOWER))
            tree_neighbors = sum(1 for state in neighbor_states if state == rules.MICRO_TREE)
            courtyard_neighbors = sum(1 for state in neighbor_states if state == rules.MICRO_COURTYARD)
            macro_state = parcel["macro_state"]

            if parcel.get("edge_greenbelt", False):
                if current == rules.MICRO_TREE:
                    next_states[parcel_id] = rules.MICRO_TREE
                elif tree_neighbors >= 1 or rng.random() < 0.66:
                    next_states[parcel_id] = rules.MICRO_TREE
                elif courtyard_neighbors >= 1 or rng.random() < 0.72:
                    next_states[parcel_id] = rules.MICRO_COURTYARD
                else:
                    next_states[parcel_id] = rules.MICRO_EMPTY
            elif not parcel.get("buildable", False):
                next_states[parcel_id] = rules.MICRO_TREE if macro_state == 0 else rules.MICRO_COURTYARD
            elif parcel["area"] > LARGE_OPEN_PARCEL_AREA:
                next_states[parcel_id] = rules.MICRO_TREE if macro_state == 0 else rules.MICRO_COURTYARD
            elif current == rules.MICRO_TOWER:
                next_states[parcel_id] = rules.MICRO_TOWER if parcel.get("tower_eligible", False) else rules.MICRO_BUILDING
            elif macro_state == 0:
                next_states[parcel_id] = rules.MICRO_TREE if tree_neighbors >= 1 or rng.random() < 0.58 else rules.MICRO_EMPTY
            elif current == rules.MICRO_BUILDING:
                next_states[parcel_id] = rules.MICRO_COURTYARD if building_neighbors >= 5 and rng.random() < 0.35 else rules.MICRO_BUILDING
            elif current == rules.MICRO_EMPTY:
                if building_neighbors >= 2 and parcel["area"] >= 0.08 and rng.random() < 0.42:
                    next_states[parcel_id] = rules.MICRO_BUILDING
                elif tree_neighbors >= 2 and macro_state in (1, 2) and rng.random() < 0.28:
                    next_states[parcel_id] = rules.MICRO_TREE
                else:
                    next_states[parcel_id] = current
            elif current == rules.MICRO_TREE:
                next_states[parcel_id] = rules.MICRO_TREE if tree_neighbors >= 1 or rng.random() < 0.70 else rules.MICRO_EMPTY
            elif current == rules.MICRO_COURTYARD:
                if building_neighbors >= 3 and courtyard_neighbors <= 1 and rng.random() < 0.24:
                    next_states[parcel_id] = rules.MICRO_BUILDING
                else:
                    next_states[parcel_id] = rules.MICRO_COURTYARD
            else:
                next_states[parcel_id] = current
        states = next_states
    return states


def finalize_parcels(parcels, adjacency):
    states = evolve_parcel_states(parcels, adjacency, initialize_parcel_states(parcels))
    finalized = []
    for parcel in parcels:
        public_parcel = {
            key: value
            for key, value in parcel.items()
            if not key.startswith("_")
        }
        public_parcel["state"] = states[parcel["id"]]
        public_parcel["neighbor_ids"] = sorted(adjacency[parcel["id"]])
        finalized.append(public_parcel)
    return finalized


def build_substrate_lookup(substrate_cells):
    return {
        cell["id"]: cell
        for cell in substrate_cells
    }


def substrate_neighbor_ids(cell, parcel_cell_ids):
    neighbors = []
    global_x = cell["global_x"]
    global_y = cell["global_y"]
    for ny in range(global_y - 1, global_y + 2):
        for nx in range(global_x - 1, global_x + 2):
            if nx == global_x and ny == global_y:
                continue
            neighbor_id = f"{nx},{ny}"
            if neighbor_id in parcel_cell_ids:
                neighbors.append(neighbor_id)
    return neighbors


def parcel_cell_edge_score(cell, bounds):
    min_x, max_x, min_y, max_y = bounds
    edge_distance = min(
        cell["global_x"] - min_x,
        max_x - cell["global_x"],
        cell["global_y"] - min_y,
        max_y - cell["global_y"],
    )
    span = max(max_x - min_x + 1, max_y - min_y + 1, 1)
    return 1.0 - min(1.0, edge_distance / max(1.0, span * 0.30))


def parcel_cell_center_score(cell, bounds):
    min_x, max_x, min_y, max_y = bounds
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    max_distance = max(math.hypot(max_x - center_x, max_y - center_y), 1.0)
    distance = math.hypot(cell["global_x"] - center_x, cell["global_y"] - center_y)
    return 1.0 - min(1.0, distance / max_distance)


def count_neighbor_cell_states(states, neighbor_ids):
    counts = {
        rules.MICRO_EMPTY: 0,
        rules.MICRO_BUILDING: 0,
        rules.MICRO_COURTYARD: 0,
        rules.MICRO_PATH: 0,
        rules.MICRO_TREE: 0,
        rules.MICRO_TOWER: 0,
    }
    for neighbor_id in neighbor_ids:
        counts[states.get(neighbor_id, rules.MICRO_EMPTY)] += 1
    return counts


def choose_initial_parcel_micro_state(parcel, cell, bounds, rng):
    if cell.get("is_road_reserved"):
        return rules.MICRO_PATH

    macro_state = parcel["macro_state"]
    params = rules.MACRO_PARAMS[macro_state]
    count = parcel.get("substrate_cell_count", 0)
    edge_score = parcel_cell_edge_score(cell, bounds)
    center_score = parcel_cell_center_score(cell, bounds)
    noise = rules.stable_noise(cell["global_x"], cell["global_y"], seed=PARCEL_RANDOM_SEED + parcel["id"] * 17)

    if parcel.get("edge_greenbelt", False):
        tree_probability = 0.58 + edge_score * 0.24
        courtyard_probability = 0.10
        roll = rng.random()
        if roll < tree_probability:
            return rules.MICRO_TREE
        if roll < tree_probability + courtyard_probability:
            return rules.MICRO_COURTYARD
        return rules.MICRO_EMPTY

    if not parcel.get("buildable", False) or count < MIN_BUILDING_SUBSTRATE_CELLS:
        if macro_state == 0:
            return rules.MICRO_TREE if rng.random() < 0.66 else rules.MICRO_EMPTY
        return rules.MICRO_COURTYARD if rng.random() < 0.54 else (rules.MICRO_TREE if rng.random() < 0.46 else rules.MICRO_EMPTY)

    if macro_state == 0:
        return rules.MICRO_TREE if rng.random() < params["tree_probability"] else rules.MICRO_EMPTY

    if macro_state == 5:
        roll = rng.random()
        if roll < 0.52:
            return rules.MICRO_PATH
        if roll < 0.76:
            return rules.MICRO_COURTYARD
        return rules.MICRO_TREE if roll < 0.90 else rules.MICRO_EMPTY

    road_bonus = 0.05 if parcel["road_adjacency"] == "main_road" else 0.03 if parcel["road_adjacency"] == "secondary_road" else 0.0
    building_probability = (
        params["building_coverage"] * PARCEL_MICRO_BUILDING_SCALE
        + center_score * 0.08
        + road_bonus
        + (noise - 0.5) * 0.10
        - edge_score * 0.11
    )
    building_probability = max(0.10, min(0.46, building_probability))
    path_probability = min(0.24, params["path_probability"] + edge_score * PARCEL_MICRO_PATH_EDGE_BIAS)
    tree_probability = min(0.24, params["tree_probability"] + (0.08 if macro_state in (1, 2) else 0.02))
    courtyard_probability = min(0.22, 0.06 + edge_score * PARCEL_MICRO_COURTYARD_EDGE_BIAS)

    roll = rng.random()
    if roll < tree_probability:
        return rules.MICRO_TREE
    if roll < tree_probability + path_probability:
        return rules.MICRO_PATH
    if roll < tree_probability + path_probability + courtyard_probability:
        return rules.MICRO_COURTYARD
    if roll < tree_probability + path_probability + courtyard_probability + building_probability:
        return rules.MICRO_BUILDING
    return rules.MICRO_EMPTY


def initialize_parcel_micro_states(parcel, parcel_cells, bounds):
    rng = random.Random(PARCEL_RANDOM_SEED + parcel["id"] * 65537)
    return {
        cell["id"]: choose_initial_parcel_micro_state(parcel, cell, bounds, rng)
        for cell in parcel_cells
    }


def evolve_parcel_micro_states(parcel, parcel_cells, bounds, states):
    rng = random.Random(PARCEL_RANDOM_SEED + 5000 + parcel["id"] * 131)
    parcel_cell_ids = set(states)
    neighbor_map = {
        cell["id"]: substrate_neighbor_ids(cell, parcel_cell_ids)
        for cell in parcel_cells
    }
    macro_state = parcel["macro_state"]
    params = rules.MACRO_PARAMS[macro_state]
    macro_cell = {
        "state": macro_state,
        "density": parcel["density"],
        "x": parcel["macro_x"],
        "y": parcel["macro_y"],
    }

    for _ in range(PARCEL_CA_ITERATIONS):
        next_states = {}
        for cell in parcel_cells:
            cell_id = cell["id"]
            current = states[cell_id]
            if cell.get("is_road_reserved"):
                next_states[cell_id] = rules.MICRO_PATH
                continue

            counts = count_neighbor_cell_states(states, neighbor_map[cell_id])
            building_neighbors = counts[rules.MICRO_BUILDING] + counts[rules.MICRO_TOWER]
            tree_neighbors = counts[rules.MICRO_TREE]
            path_neighbors = counts[rules.MICRO_PATH]
            courtyard_neighbors = counts[rules.MICRO_COURTYARD]
            edge_score = parcel_cell_edge_score(cell, bounds)

            if parcel.get("edge_greenbelt", False):
                if current == rules.MICRO_TREE or tree_neighbors >= 2 or rng.random() < 0.58:
                    next_states[cell_id] = rules.MICRO_TREE
                elif courtyard_neighbors >= 1 or rng.random() < 0.50:
                    next_states[cell_id] = rules.MICRO_COURTYARD
                else:
                    next_states[cell_id] = rules.MICRO_EMPTY
            elif not parcel.get("buildable", False) or parcel.get("substrate_cell_count", 0) < MIN_BUILDING_SUBSTRATE_CELLS:
                if macro_state == 0:
                    next_states[cell_id] = rules.MICRO_TREE if tree_neighbors >= 1 or rng.random() < 0.56 else rules.MICRO_EMPTY
                else:
                    next_states[cell_id] = rules.MICRO_COURTYARD if rng.random() < 0.58 else (rules.MICRO_TREE if rng.random() < 0.35 else rules.MICRO_EMPTY)
            else:
                next_states[cell_id] = rules.choose_next_micro_state(
                    current,
                    counts,
                    macro_cell,
                    cell["micro_x"],
                    cell["micro_y"],
                    rng,
                    MICRO_GRID_SIZE,
                    locked_path_cells=set(),
                )
        states = next_states
    return states


def place_parcel_tower_if_needed(parcel, parcel_cells, bounds, states):
    macro_state = parcel["macro_state"]
    if not parcel.get("tower_eligible", False):
        return states
    building_cell_count = sum(1 for state in states.values() if state == rules.MICRO_BUILDING)
    if building_cell_count < MIN_TOWER_BUILDING_CLUSTER_CELLS:
        return states
    rng = random.Random(PARCEL_RANDOM_SEED + 9000 + parcel["id"] * 977)
    should_place_tower = rng.random() < PARCEL_TOWER_PROBABILITY_BY_STATE.get(macro_state, 0.0)
    if not should_place_tower:
        return states

    parcel_cell_ids = set(states)
    candidates = []
    for cell in parcel_cells:
        if cell.get("is_road_reserved"):
            continue
        counts = count_neighbor_cell_states(states, substrate_neighbor_ids(cell, parcel_cell_ids))
        building_neighbors = counts[rules.MICRO_BUILDING] + counts[rules.MICRO_TOWER]
        if states[cell["id"]] == rules.MICRO_BUILDING and building_neighbors >= 3:
            score = parcel_cell_center_score(cell, bounds) + building_neighbors * 0.12
            candidates.append((score, cell["id"]))
    if candidates:
        _, tower_cell_id = max(candidates)
        states[tower_cell_id] = rules.MICRO_TOWER
    return states


def dominant_parcel_state(parcel_cells):
    counts = {}
    for cell in parcel_cells:
        state = cell.get("state", rules.MICRO_EMPTY)
        counts[state] = counts.get(state, 0) + 1
    if not counts:
        return rules.MICRO_EMPTY
    if counts.get(rules.MICRO_BUILDING, 0) or counts.get(rules.MICRO_TOWER, 0):
        return rules.MICRO_BUILDING
    return max(counts, key=counts.get)


def apply_parcel_bounded_micro_ca(parcels, substrate_cells):
    substrate_lookup = build_substrate_lookup(substrate_cells)
    state_counts = {
        rules.MICRO_EMPTY: 0,
        rules.MICRO_BUILDING: 0,
        rules.MICRO_COURTYARD: 0,
        rules.MICRO_PATH: 0,
        rules.MICRO_TREE: 0,
        rules.MICRO_TOWER: 0,
    }

    for parcel in parcels:
        parcel_cells = [
            substrate_lookup[cell_id]
            for cell_id in parcel.get("_substrate_cell_ids", [])
            if cell_id in substrate_lookup
        ]
        bounds = substrate_bounds_for_parcel(parcel)
        if not parcel_cells or bounds is None:
            parcel["state"] = rules.MICRO_EMPTY
            continue
        states = initialize_parcel_micro_states(parcel, parcel_cells, bounds)
        states = evolve_parcel_micro_states(parcel, parcel_cells, bounds, states)
        states = place_parcel_tower_if_needed(parcel, parcel_cells, bounds, states)
        for cell in parcel_cells:
            cell_state = states[cell["id"]]
            cell["state"] = cell_state
            cell["parcel_id"] = parcel["id"]
            cell["is_road_adjacent"] = cell.get("is_road_reserved") or any(
                substrate_lookup.get(neighbor_id, {}).get("is_road_reserved", False)
                for neighbor_id in substrate_neighbor_ids(cell, set(substrate_lookup))
            )
            state_counts[cell_state] = state_counts.get(cell_state, 0) + 1
        parcel["state"] = dominant_parcel_state(parcel_cells)

    for cell in substrate_cells:
        if cell.get("parcel_id") is None:
            cell["state"] = rules.MICRO_PATH if cell.get("is_road_reserved") else rules.MICRO_EMPTY
        state_counts[cell["state"]] = state_counts.get(cell["state"], 0)
    return state_counts


def serialize_parcels(parcels):
    serialized = []
    for parcel in parcels:
        item = {
            key: value
            for key, value in parcel.items()
            if not key.startswith("_")
        }
        item["polygon"] = [
            {"x": round(point["x"] + base.GRID_SIZE / 2, 4), "y": round(point["y"] + base.GRID_SIZE / 2, 4)}
            for point in parcel["polygon"]
        ]
        item["center"] = {
            "x": round(parcel["center"]["x"] + base.GRID_SIZE / 2, 4),
            "y": round(parcel["center"]["y"] + base.GRID_SIZE / 2, 4),
        }
        return_neighbors = item.get("neighbor_ids", [])
        item["neighbor_ids"] = list(return_neighbors)
        serialized.append(item)
    return serialized


def serialize_substrate_cells(substrate_cells):
    serialized = []
    for cell in substrate_cells:
        item = {
            key: value
            for key, value in cell.items()
            if not key.startswith("_")
        }
        item["x"] = round(cell["x"] + base.GRID_SIZE / 2, 4)
        item["y"] = round(cell["y"] + base.GRID_SIZE / 2, 4)
        item["corners"] = [
            {"x": round(point["x"] + base.GRID_SIZE / 2, 4), "y": round(point["y"] + base.GRID_SIZE / 2, 4)}
            for point in cell["corners"]
        ]
        serialized.append(item)
    return serialized


def create_parcel_building_record(building_id, parcel):
    is_tower = parcel["state"] == rules.MICRO_TOWER
    macro_cell = {
        "state": parcel["macro_state"],
        "density": parcel["density"],
        "x": parcel["macro_x"],
        "y": parcel["macro_y"],
    }
    params = rules.MACRO_PARAMS[parcel["macro_state"]]
    rng = random.Random(PARCEL_RANDOM_SEED + parcel["id"] * 313)
    if is_tower:
        floor_count = rng.randint(8, 14)
        footprint_scale = PARCEL_TOWER_SCALE
        roof = "flat"
        building_type = "tower"
    else:
        min_floor, max_floor = params["height_range"]
        floor_count = max(1, rng.randint(max(1, min_floor), max(1, max_floor)))
        footprint_scale = PARCEL_BUILDING_SCALE
        roof = "flat" if len(parcel["polygon"]) != 4 else roof_for_building(macro_cell, rules.MICRO_BUILDING, parcel["id"], 0)
        building_type = "house"
    footprint = scale_polygon(parcel["polygon"], footprint_scale)
    center = polygon_center(footprint)
    world_x = center["x"] + base.GRID_SIZE / 2
    world_y = center["y"] + base.GRID_SIZE / 2
    center_z = sample_scaled_terrain_height(center["x"], center["y"])
    width, depth = fallback_width_depth_from_polygon(footprint)
    return {
        "id": building_id,
        "x": round(world_x, 4),
        "y": round(world_y, 4),
        "z": round(center_z, 4),
        "width": width,
        "depth": depth,
        "height": round(floor_count * FLOOR_HEIGHT, 4),
        "floor_count": floor_count,
        "density": parcel["density"],
        "type": building_type,
        "roof": roof,
        "is_tower": is_tower,
        "macro_x": parcel["macro_x"],
        "macro_y": parcel["macro_y"],
        "parcel_id": parcel["id"],
        "footprint_cells_x": 1,
        "footprint_cells_y": 1,
        "source_cell_count": 1,
        "footprint": [
            {"x": round(point["x"] + base.GRID_SIZE / 2, 4), "y": round(point["y"] + base.GRID_SIZE / 2, 4)}
            for point in footprint
        ],
    }


def create_parcel_tree_records(parcel):
    tree_count = max(1, min(5, round(parcel["area"] * PARCEL_TREE_DENSITY)))
    center = polygon_center(parcel["polygon"])
    records = []
    for index in range(tree_count):
        noise_x = (rules.stable_noise(parcel["id"], index, seed=907) - 0.5) * 0.12
        noise_y = (rules.stable_noise(parcel["id"], index, seed=911) - 0.5) * 0.12
        world_x = center["x"] + noise_x + base.GRID_SIZE / 2
        world_y = center["y"] + noise_y + base.GRID_SIZE / 2
        world_z = sample_scaled_terrain_height(center["x"] + noise_x, center["y"] + noise_y)
        scale = TREE_BASE_SCALE * (0.90 + min(1.4, math.sqrt(max(parcel["area"], 0.01))) * 0.45)
        records.append(
            {
                "x": round(world_x, 4),
                "y": round(world_y, 4),
                "z": round(world_z, 4),
                "scale": round(scale, 4),
                "macro_x": parcel["macro_x"],
                "macro_y": parcel["macro_y"],
                "parcel_id": parcel["id"],
            }
        )
    return records


def roof_for_building(macro_cell, micro_state, mx, my):
    if micro_state == rules.MICRO_TOWER:
        return "flat"

    value = rules.stable_noise(
        macro_cell["x"] * MICRO_GRID_SIZE + mx,
        macro_cell["y"] * MICRO_GRID_SIZE + my,
        seed=611,
    )
    return "gable" if value < 0.72 else "hip"


def create_building_record(building_id, macro_cell, mx, my, micro_state, cell_geometry):
    floor_count = rules.get_floor_count(macro_cell, micro_state, mx, my)
    is_tower = micro_state == rules.MICRO_TOWER
    footprint_scale = TOWER_FOOTPRINT_SCALE if is_tower else BUILDING_FOOTPRINT_SCALE
    footprint = scale_polygon(cell_geometry["corners"], footprint_scale)
    center = polygon_center(footprint)
    center_z = sample_scaled_terrain_height(center["x"], center["y"])
    width, depth = fallback_width_depth_from_polygon(footprint)
    building_type = "tower" if is_tower else "house"

    return {
        "id": building_id,
        "x": round(center["x"] + base.GRID_SIZE / 2, 4),
        "y": round(center["y"] + base.GRID_SIZE / 2, 4),
        "z": round(center_z, 4),
        "width": width,
        "depth": depth,
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
        "footprint_cells_x": 1,
        "footprint_cells_y": 1,
        "source_cell_count": 1,
        "footprint": [
            {"x": round(point["x"] + base.GRID_SIZE / 2, 4), "y": round(point["y"] + base.GRID_SIZE / 2, 4)}
            for point in footprint
        ],
    }


def create_tree_record(macro_cell, mx, my, cell_geometry):
    center = cell_geometry["center"]
    world_x = center["x"] + base.GRID_SIZE / 2
    world_y = center["y"] + base.GRID_SIZE / 2
    world_z = sample_scaled_terrain_height(center["x"], center["y"])
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
    building_id = 1
    road_result = agent_road_network.generate_micro_road_network(
        macro_grid,
        MICRO_GRID_SIZE,
    )
    road_result = split_large_road_parcels(road_result, macro_grid)
    macro_lookup = {
        (int(cell["x"]), int(cell["y"])): cell
        for cell in macro_grid["cells"]
    }
    road_lines = build_road_lines(road_result)
    substrate_cells = create_substrate_cells(road_result, macro_grid)
    raw_parcels = extract_road_parcels(road_result, macro_grid)
    assign_substrate_to_parcels(raw_parcels, substrate_cells)
    total_grid_size = int(macro_grid["metadata"]["grid_size"]) * MICRO_GRID_SIZE
    annotate_edge_context(raw_parcels, total_grid_size)
    merged_small_parcels = merge_small_parcels(raw_parcels, substrate_cells, macro_lookup, road_lines, total_grid_size)
    buildable_parcels = apply_buildability(raw_parcels)
    parcel_adjacency = build_parcel_adjacency(raw_parcels)
    for parcel in raw_parcels:
        parcel["neighbor_ids"] = sorted(parcel_adjacency[parcel["id"]])
    micro_state_counts = apply_parcel_bounded_micro_ca(raw_parcels, substrate_cells)
    edge_greenbelt_parcels = sum(1 for parcel in raw_parcels if parcel.get("edge_greenbelt"))
    road_type_counts = {}
    for road_type in road_result["road_segments"].values():
        road_type_counts[road_type] = road_type_counts.get(road_type, 0) + 1

    for cell in substrate_cells:
        if cell.get("parcel_id") is None:
            continue
        macro_cell = macro_lookup[(cell["macro_x"], cell["macro_y"])]
        if cell["state"] in (rules.MICRO_BUILDING, rules.MICRO_TOWER):
            building = create_building_record(
                building_id,
                macro_cell,
                cell["micro_x"],
                cell["micro_y"],
                cell["state"],
                {"corners": cell["corners"], "center": cell},
            )
            building["parcel_id"] = cell["parcel_id"]
            buildings.append(building)
            building_id += 1
        elif cell["state"] == rules.MICRO_TREE:
            tree = create_tree_record(macro_cell, cell["micro_x"], cell["micro_y"], {"center": cell})
            tree["parcel_id"] = cell["parcel_id"]
            trees.append(tree)

    return {
        "metadata": {
            "source_macro_file": str(SOURCE_MACRO_JSON),
            "macro_scheme": macro_grid["metadata"].get("scheme", "scheme2"),
            "micro_grid_size": MICRO_GRID_SIZE,
            "world_scale": road_result["distorted_graph"]["metadata"].get("config", {}).get("world", {}).get("scale", 1.0),
            "spatial_cell_model": "road_locked_parcel_masked_micro_ca",
            "height_model": "shared_scaled_terrain_sampler",
            "substrate_grid_size": base.GRID_SIZE * MICRO_GRID_SIZE,
            "substrate_role": "parcel_bounded_ca_cells",
            "comfortable_building_min_substrate_cells": MIN_BUILDING_SUBSTRATE_CELLS,
            "max_parcel_substrate_cells_target": MAX_PARCEL_SUBSTRATE_CELLS,
            "max_large_parcel_split_iterations": MAX_LARGE_PARCEL_SPLIT_ITERATIONS,
            "max_large_parcel_splitters_per_iteration": MAX_LARGE_PARCEL_SPLITTERS_PER_ITERATION,
            "min_splitter_line_spacing": MIN_SPLITTER_LINE_SPACING,
            "merged_small_parcels": merged_small_parcels,
            "buildable_parcels": buildable_parcels,
            "edge_greenbelt_parcels": edge_greenbelt_parcels,
            "parcel_ca_iterations": PARCEL_CA_ITERATIONS,
            "parcel_random_seed": PARCEL_RANDOM_SEED,
            "building_cell_count": micro_state_counts.get(rules.MICRO_BUILDING, 0) + micro_state_counts.get(rules.MICRO_TOWER, 0),
            "tree_cell_count": micro_state_counts.get(rules.MICRO_TREE, 0),
            "courtyard_cell_count": micro_state_counts.get(rules.MICRO_COURTYARD, 0),
            "path_cell_count": micro_state_counts.get(rules.MICRO_PATH, 0),
            "empty_cell_count": micro_state_counts.get(rules.MICRO_EMPTY, 0),
            "road_random_seed": 42,
            "road_boundary_contacts": road_result["distorted_graph"]["metadata"].get("boundary_contacts", {}),
            "road_type_counts": road_type_counts,
            "large_parcel_split_iterations": road_result["distorted_graph"]["metadata"].get("large_parcel_split_iterations", 0),
            "large_parcel_split_segments": road_result["distorted_graph"]["metadata"].get("large_parcel_split_segments", 0),
            "max_parcel_substrate_cells_before_split": road_result["distorted_graph"]["metadata"].get("max_parcel_substrate_cells_before_split", 0),
            "max_parcel_substrate_cells_after_split": road_result["distorted_graph"]["metadata"].get("max_parcel_substrate_cells_after_split", 0),
            "floor_height": FLOOR_HEIGHT,
            "description": "Road-first parcel-bounded micro CA output: roads polygonize parcels, then warped substrate cells inside each parcel generate buildings, paths, trees, and courtyards.",
        },
        "buildings": buildings,
        "trees": trees,
        "micro_cells": serialize_substrate_cells(substrate_cells),
        "parcels": serialize_parcels(raw_parcels),
        "road_graph": road_result["distorted_graph"],
        "road_grid_segments": serialize_road_segments(
            road_result["road_segments"],
            road_result["warped_vertices"],
        ),
    }


def serialize_road_segments(road_segments, warped_vertices=None):
    serialized = []
    for index, ((start_x, start_y), (end_x, end_y)) in enumerate(sorted(road_segments), start=1):
        item = {
            "id": index,
            "type": road_segments[((start_x, start_y), (end_x, end_y))],
            "start": {"x": start_x, "y": start_y},
            "end": {"x": end_x, "y": end_y},
        }
        if warped_vertices is not None:
            start = warped_vertices[f"{start_x},{start_y}"]
            end = warped_vertices[f"{end_x},{end_y}"]
            item["warped_start"] = {
                "x": round(start["x"] + base.GRID_SIZE / 2, 4),
                "y": round(start["y"] + base.GRID_SIZE / 2, 4),
            }
            item["warped_end"] = {
                "x": round(end["x"] + base.GRID_SIZE / 2, 4),
                "y": round(end["y"] + base.GRID_SIZE / 2, 4),
            }
        serialized.append(item)
    return serialized


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
        "parcel_id",
        "footprint_cells_x",
        "footprint_cells_y",
        "source_cell_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(city_data["buildings"])
    return path


def export_tree_csv(city_data, path=TREE_CSV):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["x", "y", "z", "scale", "macro_x", "macro_y", "micro_x", "micro_y", "parcel_id"]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(city_data["trees"])
    return path


def export_micro_svg(city_data, path=MICRO_SVG):
    path.parent.mkdir(parents=True, exist_ok=True)
    margin = 28
    legend_width = 210
    drawing_size = 720
    width = margin * 2 + drawing_size + legend_width
    height = margin * 2 + drawing_size
    labels = {
        rules.MICRO_EMPTY: "0 empty",
        rules.MICRO_BUILDING: "1 building",
        rules.MICRO_COURTYARD: "2 courtyard",
        rules.MICRO_PATH: "3 path",
        rules.MICRO_TREE: "4 tree",
        rules.MICRO_TOWER: "5 tower",
    }

    substrate_cells = city_data.get("micro_cells", [])
    cells = substrate_cells
    svg_points = []
    for substrate_cell in substrate_cells:
        svg_points.extend((point["x"], point["y"]) for point in substrate_cell.get("corners", []))
    for cell in cells:
        points_key = "polygon" if "polygon" in cell else "corners"
        svg_points.extend((point["x"], point["y"]) for point in cell.get(points_key, []))
    for segment in city_data.get("road_grid_segments", []):
        if "warped_start" in segment and "warped_end" in segment:
            svg_points.append((segment["warped_start"]["x"], segment["warped_start"]["y"]))
            svg_points.append((segment["warped_end"]["x"], segment["warped_end"]["y"]))

    min_x = min((point[0] for point in svg_points), default=0.0)
    max_x = max((point[0] for point in svg_points), default=float(base.GRID_SIZE))
    min_y = min((point[1] for point in svg_points), default=0.0)
    max_y = max((point[1] for point in svg_points), default=float(base.GRID_SIZE))
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    scale = min(drawing_size / span_x, drawing_size / span_y)

    def project(point):
        return (
            margin + (point["x"] - min_x) * scale,
            margin + drawing_size - (point["y"] - min_y) * scale,
        )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f7f5ef"/>',
        f'<text x="18" y="14" font-family="Arial" font-size="12" font-weight="700" fill="#222">Road-polygonized parcel-bounded micro CA - {len(substrate_cells)} cells</text>',
    ]

    for substrate_cell in substrate_cells:
        corners = substrate_cell.get("corners")
        if not corners:
            continue
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in corners))
        stroke = "#b7b0a2" if substrate_cell.get("is_road_reserved") else "#d8d2c5"
        lines.append(
            f'<polygon points="{points}" fill="none" stroke="{stroke}" stroke-width="0.18"/>'
        )

    for cell in cells:
        state = cell["state"]
        polygon = cell.get("polygon") or cell.get("corners")
        if not polygon:
            continue
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in polygon))
        lines.append(
            f'<polygon points="{points}" fill="{rules.MICRO_COLORS[state]}" stroke="#4b4b4b" stroke-width="0.45"/>'
        )

    for segment in city_data.get("road_grid_segments", []):
        start = segment.get("warped_start")
        end = segment.get("warped_end")
        if start is None or end is None:
            continue
        x1, y1 = project(start)
        x2, y2 = project(end)
        if segment["type"] == "main_road":
            color = "#4f4031"
            stroke_width = 2.2
        elif segment["type"] in {"block_splitter", "secondary_road"}:
            color = "#735f3c"
            stroke_width = 1.65
        else:
            color = "#796a57"
            stroke_width = 1.25
        lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="square"/>'
        )

    legend_x = margin + drawing_size + 30
    legend_y = margin + 26
    lines.append(f'<text x="{legend_x}" y="{legend_y - 12}" font-family="Arial" font-size="12" font-weight="700" fill="#222">Legend</text>')

    for index, state in enumerate([0, 1, 2, 3, 4, 5]):
        y = legend_y + index * 28
        lines.append(f'<rect x="{legend_x}" y="{y}" width="18" height="18" fill="{rules.MICRO_COLORS[state]}" stroke="#222" stroke-width="0.5"/>')
        lines.append(f'<text x="{legend_x + 28}" y="{y + 13}" font-family="Arial" font-size="11" fill="#222">{labels[state]}</text>')

    lines.append(f'<text x="{legend_x}" y="{legend_y + 200}" font-family="Arial" font-size="10" fill="#555">Buildings: {len(city_data["buildings"])}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 216}" font-family="Arial" font-size="10" fill="#555">Trees: {len(city_data["trees"])}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 232}" font-family="Arial" font-size="10" fill="#555">Parcels: {len(city_data.get("parcels", []))}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 248}" font-family="Arial" font-size="10" fill="#555">Substrate cells: {len(substrate_cells)}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 264}" font-family="Arial" font-size="10" fill="#555">Buildable parcels: {city_data.get("metadata", {}).get("buildable_parcels", 0)}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 280}" font-family="Arial" font-size="10" fill="#555">Merged small parcels: {city_data.get("metadata", {}).get("merged_small_parcels", 0)}</text>')
    lines.append(f'<text x="{legend_x}" y="{legend_y + 296}" font-family="Arial" font-size="10" fill="#555">Road edges: {len(city_data.get("road_grid_segments", []))}</text>')
    lines.append("</svg>")

    with path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))
    return path


def parcel_metric_summary(city_data):
    parcels = city_data.get("parcels", [])
    counts = [parcel.get("substrate_cell_count", 0) for parcel in parcels]
    state_counts = {
        "empty": sum(1 for parcel in parcels if parcel.get("state") == rules.MICRO_EMPTY),
        "building": sum(1 for parcel in parcels if parcel.get("state") == rules.MICRO_BUILDING),
        "courtyard": sum(1 for parcel in parcels if parcel.get("state") == rules.MICRO_COURTYARD),
        "tree": sum(1 for parcel in parcels if parcel.get("state") == rules.MICRO_TREE),
        "tower": sum(1 for parcel in parcels if parcel.get("state") == rules.MICRO_TOWER),
    }
    buildable_counts = [
        parcel.get("substrate_cell_count", 0)
        for parcel in parcels
        if parcel.get("buildable")
    ]
    return {
        "parcel_count": len(parcels),
        "buildable_count": sum(1 for parcel in parcels if parcel.get("buildable")),
        "small_count": sum(1 for count in counts if count < MIN_BUILDING_SUBSTRATE_CELLS),
        "large_count": sum(1 for count in counts if count > MAX_PARCEL_SUBSTRATE_CELLS),
        "greenbelt_count": sum(1 for parcel in parcels if parcel.get("edge_greenbelt")),
        "state_counts": state_counts,
        "max_cells": max(counts, default=0),
        "median_cells": sorted(counts)[len(counts) // 2] if counts else 0,
        "buildable_min": min(buildable_counts, default=0),
        "buildable_max": max(buildable_counts, default=0),
        "buildable_median": sorted(buildable_counts)[len(buildable_counts) // 2] if buildable_counts else 0,
    }


def export_road_validation_svg(city_data, path=ROAD_VALIDATION_SVG):
    path.parent.mkdir(parents=True, exist_ok=True)
    margin = 28
    legend_width = 260
    drawing_size = 760
    width = margin * 2 + drawing_size + legend_width
    height = margin * 2 + drawing_size

    substrate_cells = city_data.get("micro_cells", [])
    parcels = city_data.get("parcels", [])
    svg_points = []
    for substrate_cell in substrate_cells:
        svg_points.extend((point["x"], point["y"]) for point in substrate_cell.get("corners", []))
    for parcel in parcels:
        svg_points.extend((point["x"], point["y"]) for point in parcel.get("polygon", []))
    for segment in city_data.get("road_grid_segments", []):
        if "warped_start" in segment and "warped_end" in segment:
            svg_points.append((segment["warped_start"]["x"], segment["warped_start"]["y"]))
            svg_points.append((segment["warped_end"]["x"], segment["warped_end"]["y"]))

    min_x = min((point[0] for point in svg_points), default=0.0)
    max_x = max((point[0] for point in svg_points), default=float(base.GRID_SIZE))
    min_y = min((point[1] for point in svg_points), default=0.0)
    max_y = max((point[1] for point in svg_points), default=float(base.GRID_SIZE))
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    scale = min(drawing_size / span_x, drawing_size / span_y)

    def project(point):
        return (
            margin + (point["x"] - min_x) * scale,
            margin + drawing_size - (point["y"] - min_y) * scale,
        )

    metrics = parcel_metric_summary(city_data)
    metadata = city_data.get("metadata", {})
    contacts = metadata.get("road_boundary_contacts", {})
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8f6ef"/>',
        f'<text x="18" y="16" font-family="Arial" font-size="12" font-weight="700" fill="#222">Road / parcel validation - {metrics["parcel_count"]} parcels</text>',
    ]

    for substrate_cell in substrate_cells:
        corners = substrate_cell.get("corners")
        if not corners:
            continue
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in corners))
        lines.append(f'<polygon points="{points}" fill="none" stroke="#dfd8cb" stroke-width="0.16"/>')

    for parcel in parcels:
        polygon = parcel.get("polygon")
        if not polygon:
            continue
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in polygon))
        count = parcel.get("substrate_cell_count", 0)
        if count > MAX_PARCEL_SUBSTRATE_CELLS:
            fill = "#e9b8a8"
            stroke = "#9a3d2f"
            stroke_width = "1.0"
        elif parcel.get("edge_greenbelt"):
            fill = "#9fc48e"
            stroke = "#4f7d45"
            stroke_width = "0.75"
        elif count < MIN_BUILDING_SUBSTRATE_CELLS:
            fill = "#d8ddd2"
            stroke = "#71776c"
            stroke_width = "0.55"
        elif parcel.get("buildable"):
            fill = "#f1e6c8"
            stroke = "#75684e"
            stroke_width = "0.65"
        else:
            fill = "#e7eadb"
            stroke = "#7f836f"
            stroke_width = "0.55"
        lines.append(
            f'<polygon points="{points}" fill="{fill}" fill-opacity="0.72" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        )

    for segment in city_data.get("road_grid_segments", []):
        start = segment.get("warped_start")
        end = segment.get("warped_end")
        if start is None or end is None:
            continue
        x1, y1 = project(start)
        x2, y2 = project(end)
        if segment["type"] == "main_road":
            color = "#2f2922"
            stroke_width = 1.7
        elif segment["type"] in {"block_splitter", "secondary_road"}:
            color = "#80643a"
            stroke_width = 1.25
        else:
            color = "#6f6657"
            stroke_width = 0.9
        lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="square"/>'
        )

    legend_x = margin + drawing_size + 28
    legend_y = margin + 24
    legend_items = [
        ("#9fc48e", "edge greenbelt / trees"),
        ("#f1e6c8", "buildable parcel"),
        ("#e7eadb", "courtyard / empty parcel"),
        ("#d8ddd2", "small non-building parcel"),
        ("#e9b8a8", "large parcel above target"),
        ("#80643a", "secondary splitter road"),
    ]
    lines.append(f'<text x="{legend_x}" y="{legend_y - 10}" font-family="Arial" font-size="12" font-weight="700" fill="#222">Road validation</text>')
    for index, (color, label) in enumerate(legend_items):
        y = legend_y + index * 26
        lines.append(f'<rect x="{legend_x}" y="{y}" width="18" height="18" fill="{color}" stroke="#333" stroke-width="0.5"/>')
        lines.append(f'<text x="{legend_x + 28}" y="{y + 13}" font-family="Arial" font-size="11" fill="#222">{label}</text>')

    stats = [
        f'Parcels: {metrics["parcel_count"]}',
        f'Buildable: {metrics["buildable_count"]}',
        f'Greenbelt: {metrics["greenbelt_count"]}',
        f'Small parcels: {metrics["small_count"]}',
        f'Large parcels: {metrics["large_count"]}',
        f'Tree parcels: {metrics["state_counts"]["tree"]}',
        f'Courtyard parcels: {metrics["state_counts"]["courtyard"]}',
        f'Empty parcels: {metrics["state_counts"]["empty"]}',
        f'Max cells: {metrics["max_cells"]}',
        f'Median cells: {metrics["median_cells"]}',
        f'Buildable cells: {metrics["buildable_min"]}/{metrics["buildable_median"]}/{metrics["buildable_max"]}',
        f'Road segments: {len(city_data.get("road_grid_segments", []))}',
        f'Secondary roads: {metadata.get("road_type_counts", {}).get("block_splitter", 0) + metadata.get("road_type_counts", {}).get("secondary_road", 0)}',
        f'Splitter segments: {metadata.get("large_parcel_split_segments", 0)}',
        f'Split iterations: {metadata.get("large_parcel_split_iterations", 0)}',
        f'Boundary L/R/B/T: {contacts.get("left", 0)}/{contacts.get("right", 0)}/{contacts.get("bottom", 0)}/{contacts.get("top", 0)}',
    ]
    for index, stat in enumerate(stats):
        lines.append(f'<text x="{legend_x}" y="{legend_y + 132 + index * 16}" font-family="Arial" font-size="10" fill="#555">{stat}</text>')

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
    road_validation_svg_path = export_road_validation_svg(city_data)
    road_result = agent_road_network.generate_micro_road_network(macro_grid, MICRO_GRID_SIZE)
    agent_road_network.write_debug_artifacts(
        {
            "raw": road_result["raw"],
            "graph": road_result["graph"],
            "distorted_graph": road_result["distorted_graph"],
        },
        OUTPUT_DIR,
    )

    print("Generated level-2 meso CA data.")
    print(f"Buildings: {len(city_data['buildings'])}")
    print(f"Trees: {len(city_data['trees'])}")
    print(f"JSON saved to: {json_path}")
    print(f"Building CSV saved to: {building_csv_path}")
    print(f"Tree CSV saved to: {tree_csv_path}")
    print(f"Micro SVG saved to: {svg_path}")
    print(f"Road validation SVG saved to: {road_validation_svg_path}")


if __name__ == "__main__":
    main()
