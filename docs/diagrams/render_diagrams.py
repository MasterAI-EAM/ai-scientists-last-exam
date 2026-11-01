"""Rebuild source and export all three native draw.io pages with one CLI binary."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ("01-framework", "02-contribution", "03-real-loop")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drawio", help="Path to draw.io Desktop CLI")
    parser.add_argument("--width", type=int, default=2400)
    args = parser.parse_args()
    binary = args.drawio or shutil.which("drawio") or shutil.which("draw.io")
    if not binary and Path("/Applications/draw.io.app/Contents/MacOS/draw.io").is_file():
        binary = "/Applications/draw.io.app/Contents/MacOS/draw.io"
    if not binary:
        raise SystemExit("Install draw.io Desktop or pass --drawio /path/to/binary")
    subprocess.run([sys.executable, str(ROOT / "build_diagrams.py")], check=True)
    source = str(ROOT / "aisle_framework.drawio")
    for page_number, name in enumerate(PAGES, 1):
        base = [binary, "-x", "--theme", "light", "--page-index", str(page_number), "-b", "25"]
        subprocess.run(
            base
            + ["-f", "png", "--width", str(args.width), "-o", str(ROOT / f"{name}.png"), source],
            check=True,
            timeout=90,
        )
        subprocess.run(
            base
            + ["-f", "svg", "-e", "--embed-svg-images", "-o", str(ROOT / f"{name}.svg"), source],
            check=True,
            timeout=90,
        )
        print(f"Exported page {page_number}: {name}", flush=True)
    shutil.copyfile(ROOT / "01-framework.svg", ROOT / "aisle_framework.svg")
    subprocess.run(
        [
            binary,
            "-x",
            "-f",
            "pdf",
            "-e",
            "-a",
            "--crop",
            "--theme",
            "light",
            "-b",
            "25",
            "-o",
            str(ROOT / "aisle_framework.pdf"),
            source,
        ],
        check=True,
        timeout=90,
    )


if __name__ == "__main__":
    main()
