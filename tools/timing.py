"""How long the validator takes, on files this script writes.

    python tools/timing.py

Writes to a temporary folder a FeatureCollection of 10,000 polygons of 30
corners (about 6 MB), one of 40,000 polygons of 10 corners (about 10 MB), and
one polygon of 5,000 positions; validates each three times with
validate_file, the same call the command makes, and prints the best time and
the file's size. The numbers are the machine's own, so the README states
which machine gave its figures.
"""
from __future__ import annotations

import json
import math
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eudr_geojson_validator.validate import validate_file  # noqa: E402


def polygon(lon: float, lat: float, corners: int, radius: float) -> list:
    ring = [[round(lon + radius * math.cos(2 * math.pi * k / corners), 6),
             round(lat + radius * math.sin(2 * math.pi * k / corners), 6)]
            for k in range(corners)]
    return [ring + [ring[0]]]


def collection(n: int, corners: int, radius: float = 0.0008) -> dict:
    side = math.ceil(math.sqrt(n))
    features = []
    for i in range(n):
        lon = -7.5 + 0.004 * (i % side)              # a grid of plots in Côte d'Ivoire
        lat = 5.5 + 0.004 * (i // side)
        features.append({"type": "Feature",
                         "properties": {"ProducerCountry": "CI", "ProductionPlace": f"plot {i}"},
                         "geometry": {"type": "Polygon",
                                      "coordinates": polygon(lon, lat, corners, radius)}})
    return {"type": "FeatureCollection", "features": features}


def best_of_three(path: Path) -> float:
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        report = validate_file(path)
        times.append(time.perf_counter() - t0)
        assert report.ok, report.errors[:3]
    return min(times)


def main() -> int:
    cases = [("10,000 polygons of 30 corners", collection(10_000, 30)),
             ("40,000 polygons of 10 corners", collection(40_000, 10)),
             ("one polygon of 5,000 positions", collection(1, 4999, radius=0.01))]
    print(f"Python {platform.python_version()} on {platform.system()} {platform.machine()}")
    with tempfile.TemporaryDirectory() as folder:
        for name, obj in cases:
            path = Path(folder) / "timing.geojson"
            path.write_text(json.dumps(obj), encoding="utf-8")
            size = path.stat().st_size / 1024 / 1024
            print(f"{name}: {size:.1f} MB, {best_of_three(path):.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
