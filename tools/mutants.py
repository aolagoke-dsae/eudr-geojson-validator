"""Mutation testing: does every rule have a test that fails when it breaks?

    python tools/mutants.py            # every mutant
    python tools/mutants.py 10-20      # some of them, by number

A mutant is a copy of the validator with one rule reverted or weakened, by a
single exact replacement in eudr_geojson_validator/validate.py. For each, the
package, the tests and the fixtures are copied to a temporary folder, the
replacement is made there, and the suite runs against the copy. A mutant the
suite does not fail has survived: the rule it breaks has no test that holds
it. Exits 0 when every mutant is killed. Needs pytest.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("eudr_geojson_validator") / "validate.py"

# (what breaks, the text replaced, its replacement)
MUTANTS = [
    ("G000: the 25 MB limit raised to 26 MB",
     "MAX_FILE_BYTES = 25 * 1024 * 1024", "MAX_FILE_BYTES = 26 * 1024 * 1024"),
    ("G000: the size limit never reached",
     "if size > MAX_FILE_BYTES:", "if size > MAX_FILE_BYTES * 1000:"),
    ("G001: NaN read as a number",
     "obj = json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)",
     "obj = json.loads(text, parse_float=Decimal)"),
    ("G001: the depth limit never reached",
     "    if depth > MAX_DEPTH:", "    if depth > MAX_DEPTH * 1000:"),
    ("G001: a file nested exactly to the limit refused",
     "    if depth > MAX_DEPTH:", "    if depth >= MAX_DEPTH:"),
    ("G001: brackets inside strings counted as nesting",
     """outside = "".join(unescaped.split('"')[::2])""", "outside = unescaped"),
    ("G001: an escaped quote read as the end of a string",
     r"""unescaped = text.replace("\\\\", "").replace('\\"', "")""",
     r"""unescaped = text.replace("\\\\", "")"""),
    ("G001: an escaped backslash read as escaping the quote after it",
     r"""unescaped = text.replace("\\\\", "").replace('\\"', "")""",
     r"""unescaped = text.replace('\\"', "")"""),
    ("G002: a bare Feature accepted at the top level",
     'if obj.get("type") != "FeatureCollection":',
     'if obj.get("type") not in ("FeatureCollection", "Feature"):'),
    ("G004: an empty features array accepted",
     'if not features:\n        report.add("G004"', 'if features is None:\n        report.add("G004"'),
    ("G005: an element that is not a Feature accepted",
     'if not isinstance(feature, dict) or feature.get("type") != "Feature":',
     "if not isinstance(feature, dict):"),
    ("G008: an empty MultiPolygon accepted",
     'if gtype in ("MultiPoint", "MultiPolygon") and not coords:',
     'if gtype in ("MultiPoint",) and not coords:'),
    ("G009: a Point given an array of positions accepted",
     "return not any(isinstance(v, (list, dict)) for v in value)", "return True"),
    ("G010: booleans accepted as coordinates",
     "if not all(isinstance(v, NUMBER) and not isinstance(v, bool)\n               for v in (lon, lat)):",
     "if not all(isinstance(v, NUMBER)\n               for v in (lon, lat)):"),
    ("G011: longitudes up to 181 accepted",
     "if not -180.0 <= lon <= 180.0:", "if not -180.0 <= lon <= 181.0:"),
    ("G012: latitudes up to 91 accepted",
     "if not -90.0 <= lat <= 90.0:", "if not -90.0 <= lat <= 91.0:"),
    ("G013: more than six decimals an error, as in 1.0",
     'report.add("G013", SEVERITY_WARNING,', 'report.add("G013", SEVERITY_ERROR,'),
    ("G013: exactly six decimals counted as more",
     "if places > SYSTEM_DECIMALS:", "if places >= SYSTEM_DECIMALS:"),
    ("G029: five decimals accepted",
     "elif places < MIN_DECIMALS:", "elif places < MIN_DECIMALS - 1:"),
    ("G029: too few decimals an error",
     'report.add("G029", SEVERITY_WARNING,', 'report.add("G029", SEVERITY_ERROR,'),
    ("decimals counted from the float, not as written, as in 1.0",
     "return -exponent if isinstance(exponent, int) and exponent < 0 else 0",
     'return len(str(float(value)).split(".")[1]) if "." in str(float(value)) else 0'),
    ("G014: an interior ring accepted", "if len(rings) > 1:", "if len(rings) > 2:"),
    ("G015: a ring of three positions accepted",
     "if not isinstance(outer, list) or len(outer) < 4:",
     "if not isinstance(outer, list) or len(outer) < 3:"),
    ("G016: an open ring accepted", "if outer[0] != outer[-1]:", "if outer[0] != outer[-1] and False:"),
    ("G017: a Feature without properties not flagged",
     'if "properties" not in feature:', "if False:"),
    ("G018: ProducerCountry not required in a Type II file",
     'if file_type == "II":\n            report.add("G018"',
     'if file_type == "III":\n            report.add("G018"'),
    ("G019: country codes checked for their form only, as in 1.1",
     "elif not isinstance(country, str) or country not in ISO_3166_1_ALPHA2:",
     "elif not isinstance(country, str) or len(country) != 2:"),
    ("G019: no hint that ISO writes GB for UK",
     'NOT_ISO_3166_1 = {"EL": "GR", "UK": "GB"}', 'NOT_ISO_3166_1 = {"EL": "GR"}'),
    ("G020: an empty ProducerName in a Type II file not flagged",
     'props.get("ProducerName") in (None, "")', 'props.get("ProducerName") in (None,)'),
    ("G021: a MultiPoint without Area not flagged",
     'if gtype in ("Point", "MultiPoint") and area is None:',
     'if gtype in ("Point",) and area is None:'),
    ("G022: a non-finite Area accepted",
     "return value.is_finite() if isinstance(value, Decimal) else math.isfinite(value)",
     "return True"),
    ("G023: an Area of zero accepted", "elif area <= 0:", "elif area < 0:"),
    ("G024: exactly four hectares rejected",
     "and area > POINT_DEFAULT_AREA_HA and not cattle",
     "and area >= POINT_DEFAULT_AREA_HA and not cattle"),
    ("G024: the cattle exemption ignored",
     "and area > POINT_DEFAULT_AREA_HA and not cattle", "and area > POINT_DEFAULT_AREA_HA"),
    ("G024: the four-hectare rule at five hectares",
     "POINT_DEFAULT_AREA_HA = 4.0", "POINT_DEFAULT_AREA_HA = 5.0"),
    ("G025: a factor of three instead of two",
     "if measured > 0 and (area > measured * 2 or area < measured / 2):",
     "if measured > 0 and (area > measured * 3 or area < measured / 3):"),
    ("G025: only an Area too large flagged",
     "if measured > 0 and (area > measured * 2 or area < measured / 2):",
     "if measured > 0 and (area > measured * 2):"),
    ("area: ten times too large, as 1.0's tests let through", "/ 10_000.0", "/ 1_000.0"),
    ("area: another Earth radius", "EARTH_RADIUS_M = 6_371_008.8", "EARTH_RADIUS_M = 6_378_137.0"),
    ("G026: the country box's latitudes ignored",
     "if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):",
     "if not (min_lon <= lon <= max_lon):"),
    ("G026: no hint that the pair is reversed",
     "swapped = (min_lon <= lat <= max_lon and min_lat <= lon <= max_lat)", "swapped = False"),
    ("G027: a repeated geometry not flagged", "if key in seen:", "if key in seen and False:"),
    ("G028: truncation tried, rounding not",
     'for mode, label in ((ROUND_DOWN, "truncation"), (ROUND_HALF_UP, "rounding")):',
     'for mode, label in ((ROUND_DOWN, "truncation"),):'),
    ("G028: rounding tried, truncation not",
     'for mode, label in ((ROUND_DOWN, "truncation"), (ROUND_HALF_UP, "rounding")):',
     'for mode, label in ((ROUND_HALF_UP, "rounding"),):'),
    ("G028: positions identical as written reported as a collapse",
     "if j is not None and pts[j] != (lon, lat):", "if j is not None:"),
    ("G030: a list as properties accepted",
     "elif not isinstance(props, dict):", "elif isinstance(props, str):"),
    ("G031: crossing sides not found",
     "if d1 * d2 < 0 and d3 * d4 < 0:\n        return True",
     "if d1 * d2 < 0 and d3 * d4 < 0:\n        return False"),
    ("G031: touching sides not found",
     "return ((d1 == 0 and _within(q1, q2, p1)) or (d2 == 0 and _within(q1, q2, p2))",
     "return ((d1 == 0 and False) or (d2 == 0 and False)"),
    ("G031: a ring folding back on itself not found", "if back > 0:", "if back > 0 and False:"),
    ("G031: the sweep stops short of sides it must test",
     "reach = hi[i] + 1e-9", "reach = hi[i] - 1e-3"),
    ("G031: neighbouring sides through the closing position compared",
     "if abs(i - j) in (1, n - 1):", "if abs(i - j) in (1,):"),
    ("G032: a ring on one straight line accepted",
     "if len(v) < 3 or all(_orient(v[0], v[1], p) == 0 for p in v[2:]):", "if len(v) < 3:"),
    ("exactness: the exact orientation's sign reversed",
     "return (e > 0) - (e < 0)", "return (e < 0) - (e > 0)"),
    ("exactness: floating point decides every turn",
     "bound = 1e-12 * (abs(d1)", "bound = 0 * (abs(d1)"),
    ("G033: a wrongly cased property found only in lower case",
     "if isinstance(key, str) and key != name and key.lower() == name.lower():",
     "if isinstance(key, str) and key != name and key == name.lower():"),
    ("G034: XK an error instead of a warning",
     'EU_USER_ASSIGNED = {"XK": "Kosovo"}', "EU_USER_ASSIGNED = {}"),
    ("--strict: warnings never fail the file",
     "failed = bool(report.errors) or (args.strict and bool(report.warnings))",
     "failed = bool(report.errors)"),
    ("exit code 2, a file that cannot be read, given as 1",
     "        return 2\n    except Exception", "        return 1\n    except Exception"),
    ("exit code 3, a fault in the validator, given as 1",
     "        return 3\n", "        return 1\n"),
]


def run(number: int, what: str, old: str, new: str, source: str) -> bool:
    """True when the suite fails against the mutant: it is killed."""
    if source.count(old) != 1:
        raise SystemExit(f"mutant {number} ({what}): its text occurs "
                         f"{source.count(old)} times in {TARGET}, not once")
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder)
        for part in ("eudr_geojson_validator", "src", "tests", "data"):
            shutil.copytree(ROOT / part, copy / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        (copy / TARGET).write_text(source.replace(old, new), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x",
                                 "-p", "no:cacheprovider", "tests"],
                                cwd=copy, capture_output=True, text=True)
        return result.returncode != 0


def main(argv: list[str]) -> int:
    chosen = range(1, len(MUTANTS) + 1)
    if argv:
        first, _, last = argv[0].partition("-")
        chosen = range(int(first), int(last or first) + 1)
    source = (ROOT / TARGET).read_text(encoding="utf-8")
    survivors = []
    for number in chosen:
        what, old, new = MUTANTS[number - 1]
        killed = run(number, what, old, new, source)
        print(f"{number:3d} {'killed  ' if killed else 'SURVIVED'} {what}", flush=True)
        if not killed:
            survivors.append(number)
    print(f"\n{len(chosen) - len(survivors)} of {len(chosen)} mutants killed"
          + (f"; survived: {', '.join(map(str, survivors))}" if survivors else ""))
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
