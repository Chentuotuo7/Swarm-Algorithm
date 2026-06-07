# Initial Result: Scheme2 + ScaleA + MergeB

This folder contains the current successful preliminary result.

## Structure

- `scripts/`
  - Source scripts needed to reproduce the current result.
  - Level 1 macro CA uses `generate_city_grid_scheme2.py`.
  - Level 2 meso CA rules are separated in `ca_level2_rules.py`.
  - Final building merge result uses `generate_level2_buildings_scaleA_mergeB.py`.
  - Blender preview uses `generate_level2_preview_blender_scaleA_mergeB.py`.

- `data/`
  - Level 1 macro grid data.
  - Final level 2 building bounding boxes.
  - Final tree point data.

- `visuals/`
  - Level 1 macro CA color grid SVG.
  - Level 2 meso CA 180x180 color grid SVG.

- `blender/`
  - Final Blender preview file.

## Current Result Settings

- Macro grid: `30x30`
- Level 2 subdivision per macro cell: `6x6`
- Height scheme: `ScaleA`
  - `FLOOR_HEIGHT = 0.14`
- Merge scheme: `MergeB`
  - Adjacent building micro-cells are merged into rectangular blocks such as `2x2`, `3x1`, and `2x3`.
- Towers remain independent blocks.

## Final Output Files

- `data/city_grid_30x30_scheme2.json`
- `data/city_grid_30x30_scheme2.csv`
- `data/city_buildings_scheme2_scaleA_mergeB.json`
- `data/city_buildings_scheme2_scaleA_mergeB.csv`
- `data/city_trees_scheme2_scaleA_mergeB.csv`
- `visuals/macro_ca_level1_30x30_scheme2.svg`
- `visuals/meso_ca_level2_180x180_scheme2_scaleA_mergeB.svg`
- `blender/city_level2_scheme2_scaleA_mergeB.blend`
