from pathlib import Path

import generate_level2_buildings as level2


OUTPUT_DIR = Path(__file__).parent / "output"


def main():
    level2.FLOOR_HEIGHT = 0.14

    macro_grid = level2.load_macro_grid()
    city_data = level2.generate_level2_data(macro_grid)
    city_data["metadata"]["scale_scheme"] = "scaleA"
    city_data["metadata"]["description"] = (
        f"Level-2 meso CA output using scale scheme A: keep {level2.MICRO_GRID_SIZE}x{level2.MICRO_GRID_SIZE} micro buildings "
        "unmerged, reduce floor height to 0.14 Blender units."
    )

    json_path = level2.export_building_json(
        city_data,
        OUTPUT_DIR / "city_buildings_scheme2_scaleA.json",
    )
    building_csv_path = level2.export_building_csv(
        city_data,
        OUTPUT_DIR / "city_buildings_scheme2_scaleA.csv",
    )
    tree_csv_path = level2.export_tree_csv(
        city_data,
        OUTPUT_DIR / "city_trees_scheme2_scaleA.csv",
    )
    svg_path = level2.export_micro_svg(
        city_data,
        OUTPUT_DIR / f"meso_ca_level2_{level2.MICRO_GRID_LABEL}_scheme2_scaleA.svg",
    )

    print("Generated level-2 scale scheme A data.")
    print(f"Buildings: {len(city_data['buildings'])}")
    print(f"Trees: {len(city_data['trees'])}")
    print(f"JSON saved to: {json_path}")
    print(f"Building CSV saved to: {building_csv_path}")
    print(f"Tree CSV saved to: {tree_csv_path}")
    print(f"Micro SVG saved to: {svg_path}")


if __name__ == "__main__":
    main()
