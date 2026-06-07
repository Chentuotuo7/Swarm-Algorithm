from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_level2_preview_blender as preview


OUTPUT_DIR = SCRIPT_DIR / "output"


def main():
    preview.BUILDING_JSON = OUTPUT_DIR / "city_buildings_scheme2_scaleA.json"
    preview.BLEND_OUTPUT = OUTPUT_DIR / "city_level2_scheme2_scaleA.blend"
    preview.main()


if __name__ == "__main__":
    main()
