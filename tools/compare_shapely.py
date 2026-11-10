"""The ring check, G031 and G032, against Shapely, on random rings.

    pip install shapely
    python tools/compare_shapely.py [--rings 1500] [--seed 20261018]

Each ring has 3 to 8 corners drawn from a 7 x 7 grid of 0.0001-degree steps,
so rings that cross, touch or fold back on themselves, or lie on one line,
are common rather than rare; it is written at six decimals, as the Regulation
asks. The validator flags a ring when it reports G031 or G032; Shapely
(GEOS), when Polygon(ring).is_valid is False.

The validator decides on the numbers as written. Shapely computes in binary
floating point, where 6.8003 is not exactly 6.8003, so three positions that
lie exactly on one line as written may not lie on one line for Shapely.
Shapely is therefore given each ring twice: as the grid's integers, where
floating point is exact and the two must agree, and as the six-decimal
coordinates, where every disagreement must be such a ring, flagged by the
validator and passed by Shapely. Exits 0 when both hold.
"""
from __future__ import annotations

import argparse
import random
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eudr_geojson_validator.validate import validate_obj  # noqa: E402

STEP = Decimal("0.0001")
ORIGIN = (Decimal("-5.400000"), Decimal("6.800000"))      # inland Côte d'Ivoire


def random_corners(rng: random.Random) -> list[tuple[int, int]]:
    corners = [(rng.randrange(7), rng.randrange(7)) for _ in range(rng.randint(3, 8))]
    return corners + [corners[0]]


def as_written(corners) -> list[list[Decimal]]:
    return [[(ORIGIN[0] + STEP * x).quantize(Decimal("0.000001")),
             (ORIGIN[1] + STEP * y).quantize(Decimal("0.000001"))] for x, y in corners]


def flagged_by_validator(ring) -> bool:
    feature = {"type": "Feature", "properties": {"ProducerCountry": "CI"},
               "geometry": {"type": "Polygon", "coordinates": [ring]}}
    codes = validate_obj({"type": "FeatureCollection", "features": [feature]}).codes()
    return bool(codes & {"G031", "G032"})


def main() -> int:
    from shapely.geometry import Polygon

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rings", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=20261018)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    flagged = exact_disagree = float_disagree = float_other = 0
    for k in range(args.rings):
        corners = random_corners(rng)
        ring = as_written(corners)
        ours = flagged_by_validator(ring)
        flagged += ours
        exact = not Polygon([(float(x), float(y)) for x, y in corners]).is_valid
        floats = not Polygon([(float(x), float(y)) for x, y in ring]).is_valid
        if ours != exact:
            exact_disagree += 1
            print(f"  ring {k}, grid integers: validator {'flags' if ours else 'passes'}, "
                  f"Shapely {'invalid' if exact else 'valid'}: {corners}")
        if ours != floats:
            float_disagree += 1
            if not (ours and not floats and ours == exact):
                float_other += 1
                print(f"  ring {k}, six decimals: an unexplained disagreement: {corners}")
    print(f"{args.rings} rings, seed {args.seed}: the validator flags {flagged}.")
    print(f"Shapely on the grid's integers disagrees on {exact_disagree}.")
    print(f"Shapely on the six-decimal coordinates disagrees on {float_disagree}, "
          f"{float_disagree - float_other} of them rings that are degenerate exactly "
          f"as written and not in binary floating point.")
    return 1 if exact_disagree or float_other else 0


if __name__ == "__main__":
    raise SystemExit(main())
