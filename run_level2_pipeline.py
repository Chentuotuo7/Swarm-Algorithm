import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent if "__file__" in globals() else Path.cwd()
BLENDER_EXE = Path(r"D:\software\Blender4.1\blender-4.1.1-windows-x64\blender.exe")


def run_python_step(script_name):
    script_path = SCRIPT_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(SCRIPT_DIR),
        check=True,
    )
    return result.returncode


def run_blender_step(script_name):
    if not BLENDER_EXE.exists():
        print(f"Blender executable not found: {BLENDER_EXE}")
        return 1

    script_path = SCRIPT_DIR / script_name
    result = subprocess.run(
        [str(BLENDER_EXE), "--background", "--python", str(script_path)],
        cwd=str(SCRIPT_DIR),
        check=True,
    )
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Run level-2 meso CA generation pipeline.")
    parser.add_argument(
        "--skip-blender",
        action="store_true",
        help="Generate JSON/CSV/SVG only and skip Blender preview.",
    )
    args = parser.parse_args()

    print("Step 1/2: Generate level-2 building and tree data.")
    run_python_step("generate_level2_buildings.py")

    if args.skip_blender:
        print("Step 2/2: Blender preview skipped.")
    else:
        print("Step 2/2: Generate Blender preview.")
        run_blender_step("generate_level2_preview_blender.py")

    print("Level-2 pipeline completed.")


if __name__ == "__main__":
    main()
