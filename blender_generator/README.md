# Blender City Generator

This folder contains the Blender-side preview generator for Swarm-Algorithm output.

## Convert A-line Output

Run this from the repository root:

```bash
python3 blender_generator/prepare_city_data.py
```

Default inputs:

- `output/city_buildings_scheme2_scaleA_mergeB.json`
- `output/city_trees_scheme2_scaleA_mergeB.csv`

Default output:

- `blender_generator/city_data.json`

To use different A-line outputs:

```bash
python3 blender_generator/prepare_city_data.py \
  --buildings output/city_buildings_scheme2_scaleA.json \
  --trees output/city_trees_scheme2_scaleA.csv \
  --output blender_generator/city_data.json
```

To create a smaller A-line preview copy without overwriting the full dataset:

```bash
python3 blender_generator/prepare_city_data.py \
  --max-macro-cells 8 \
  --output blender_generator/city_data_preview_small.json
```

`--max-macro-cells` keeps whole macro cells so local building groupings remain visible. `--max-buildings` and `--max-trees` are still available for even sampling across the full A-line output. Coordinates are centered to the A-line macro grid by default; use `--no-recenter` only if you need the raw source coordinates.

By default, each macro cell is capped for review clarity: low density keeps 2-4 buildings, medium keeps 4-6, high keeps 6-8, and tower cells keep 1 tower plus 2-4 podium houses. Selection prioritizes towers, larger footprints, and buildings near the macro-cell boundary. Use `--no-macro-building-cap` to keep the raw A-line density.

Building heights are normalized for Blender review: ordinary houses are shown as 2-3 floors and towers as 6 floors, while source heights are kept as `source_height` and `source_floor_count`.

## Generate Blender Scene

After conversion, run:

```bash
blender --python blender_generator/city_generator.py
```

To preview the smaller copy:

```bash
blender --python blender_generator/city_generator.py -- --city-data blender_generator/city_data_preview_small.json
```

The generator reads `blender_generator/city_data.json`, clears the scene, creates buildings, roofs, towers, windows, trees, foundations, materials, camera, lighting, and render settings.
