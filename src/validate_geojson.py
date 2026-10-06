"""Validate a GeoJSON file against the European Commission's
EUDR GeoJSON File Description, version 1.5.

Two kinds of finding are kept apart on purpose.

ERROR   the file breaches the published specification. A system that accepts
        the specification is entitled to reject the file.
WARNING the file satisfies every structural rule and is still probably wrong.
        Nothing may reject it on this basis, and a human should look.

The distinction matters because the second kind is where real submissions
fail. A plot whose coordinates were entered latitude-first parses cleanly,
validates cleanly, and points at open ocean.
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

SPEC_VERSION = "1.5"
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DECIMALS = 6
POINT_DEFAULT_AREA_HA = 4.0
ALLOWED_GEOMETRY = ("Point", "MultiPoint", "Polygon", "MultiPolygon")
EARTH_RADIUS_M = 6_371_008.8

ISO_3166_1_ALPHA2 = re.compile(r"^[A-Z]{2}$")

# Bounding boxes (min_lon, min_lat, max_lon, max_lat) for countries that
# appear in EUDR commodity supply chains. Used only to raise a warning when a
# plot sits outside the country it declares, which is the signature of
# transposed coordinates.
COUNTRY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "AR": (-73.6, -55.1, -53.6, -21.8),
    "BR": (-74.0, -33.8, -34.8, 5.3),
    "CD": (12.2, -13.5, 31.3, 5.4),
    "CI": (-8.6, 4.3, -2.5, 10.7),
    "CM": (8.5, 1.7, 16.2, 13.1),
    "CN": (73.5, 18.2, 134.8, 53.6),
    "CO": (-79.0, -4.2, -66.9, 12.5),
    "CR": (-85.9, 8.0, -82.6, 11.2),
    "DE": (5.9, 47.3, 15.0, 55.1),
    "EC": (-81.0, -5.0, -75.2, 1.4),
    "ET": (33.0, 3.4, 48.0, 14.9),
    "FR": (-5.1, 41.3, 9.6, 51.1),
    "GH": (-3.3, 4.7, 1.2, 11.2),
    "GN": (-15.1, 7.2, -7.6, 12.7),
    "GT": (-92.2, 13.7, -88.2, 17.8),
    "HN": (-89.4, 12.9, -83.1, 16.5),
    "ID": (95.0, -11.0, 141.0, 6.1),
    "IN": (68.1, 6.7, 97.4, 35.5),
    "KE": (33.9, -4.7, 41.9, 5.5),
    "LR": (-11.5, 4.3, -7.4, 8.6),
    "MY": (99.6, 0.8, 119.3, 7.4),
    "NG": (2.7, 4.2, 14.7, 13.9),
    "NI": (-87.7, 10.7, -82.6, 15.0),
    "PE": (-81.4, -18.4, -68.7, -0.0),
    "PG": (140.8, -11.7, 155.9, -1.3),
    "PH": (116.9, 4.6, 126.6, 21.1),
    "PY": (-62.6, -27.6, -54.3, -19.3),
    "RW": (28.8, -2.9, 30.9, -1.0),
    "SL": (-13.3, 6.9, -10.3, 10.0),
    "TG": (-0.1, 6.1, 1.8, 11.1),
    "TH": (97.3, 5.6, 105.6, 20.5),
    "TZ": (29.3, -11.8, 40.5, -0.9),
    "UG": (29.5, -1.5, 35.0, 4.2),
    "VN": (102.1, 8.2, 109.5, 23.4),
}

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    where: str = ""

    def __str__(self) -> str:
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.severity} {self.code}{loc}: {self.message}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, severity: str, message: str, where: str = "") -> None:
        self.findings.append(Finding(code, severity, message, where))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {f.code for f in self.findings}

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec_version": SPEC_VERSION,
            "conformant": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [
                {"code": f.code, "severity": f.severity,
                 "message": f.message, "where": f.where}
                for f in self.findings
            ],
        }


def _decimals(value: float | int | str) -> int:
    """Count decimal places as written, not as float rounding leaves them."""
    text = format(Decimal(str(value)), "f")
    return len(text.split(".")[1]) if "." in text else 0


def _ring_area_ha(ring: list[list[float]]) -> float:
    """Spherical excess area of a closed ring, in hectares.

    Dependency-free on purpose: pulling in a projection library to answer
    "is the declared area plausible" would be the wrong trade.
    """
    if len(ring) < 4:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2.0) / 10_000.0


def _iter_positions(geometry: dict) -> Iterable[list[float]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if coords is None:
        return
    if gtype == "Point":
        yield coords
    elif gtype in ("MultiPoint",):
        yield from coords
    elif gtype == "Polygon":
        for ring in coords:
            yield from ring
    elif gtype == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                yield from ring


def _check_position(pos: Any, report: Report, where: str) -> bool:
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        report.add("G010", SEVERITY_ERROR,
                   "Position must be an array of at least two numbers.", where)
        return False
    lon, lat = pos[0], pos[1]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (lon, lat)):
        report.add("G010", SEVERITY_ERROR,
                   "Position values must be numbers.", where)
        return False
    ok = True
    if not -180.0 <= lon <= 180.0:
        report.add("G011", SEVERITY_ERROR,
                   f"Longitude {lon} is outside [-180, 180]. "
                   "Positions are [longitude, latitude].", where)
        ok = False
    if not -90.0 <= lat <= 90.0:
        report.add("G012", SEVERITY_ERROR,
                   f"Latitude {lat} is outside [-90, 90]. "
                   "A value above 90 usually means the pair is reversed.", where)
        ok = False
    for value, name in ((lon, "longitude"), (lat, "latitude")):
        if _decimals(value) > MAX_DECIMALS:
            report.add("G013", SEVERITY_ERROR,
                       f"{name} {value} carries more than {MAX_DECIMALS} "
                       "decimal places.", where)
            ok = False
    return ok


def _check_geometry(geometry: Any, report: Report, where: str) -> None:
    if not isinstance(geometry, dict):
        report.add("G006", SEVERITY_ERROR, "Feature has no geometry object.", where)
        return
    gtype = geometry.get("type")
    if gtype not in ALLOWED_GEOMETRY:
        report.add("G007", SEVERITY_ERROR,
                   f"Geometry type {gtype!r} is not permitted. "
                   f"Allowed: {', '.join(ALLOWED_GEOMETRY)}.", where)
        return
    coords = geometry.get("coordinates")
    if coords is None:
        report.add("G008", SEVERITY_ERROR, "Geometry has no coordinates.", where)
        return

    for pos in _iter_positions(geometry):
        _check_position(pos, report, where)

    if gtype == "Polygon":
        _check_rings(coords, report, where)
    elif gtype == "MultiPolygon":
        for p, polygon in enumerate(coords):
            _check_rings(polygon, report, f"{where}/polygon[{p}]")


def _check_rings(rings: Any, report: Report, where: str) -> None:
    if not isinstance(rings, list) or not rings:
        report.add("G008", SEVERITY_ERROR, "Polygon has no rings.", where)
        return
    if len(rings) > 1:
        report.add("G014", SEVERITY_ERROR,
                   f"Polygon declares {len(rings) - 1} interior ring(s). "
                   "Interior rings are not permitted.", where)
    outer = rings[0]
    if not isinstance(outer, list) or len(outer) < 4:
        report.add("G015", SEVERITY_ERROR,
                   "A polygon ring needs at least four positions.", where)
        return
    if outer[0] != outer[-1]:
        report.add("G016", SEVERITY_ERROR,
                   "Polygon ring is not closed: the last position must repeat "
                   "the first.", where)


def _check_properties(props: Any, geometry: Any, report: Report, where: str) -> None:
    if not isinstance(props, dict):
        report.add("G017", SEVERITY_ERROR, "Feature has no properties object.", where)
        return

    country = props.get("ProducerCountry")
    if country is None:
        report.add("G018", SEVERITY_ERROR, "ProducerCountry is required.", where)
    elif not isinstance(country, str) or not ISO_3166_1_ALPHA2.match(country):
        report.add("G019", SEVERITY_ERROR,
                   f"ProducerCountry {country!r} is not an uppercase ISO 3166-1 "
                   "alpha-2 code.", where)

    if props.get("ProducerName") in (None, ""):
        report.add("G020", SEVERITY_ERROR, "ProducerName is required.", where)

    gtype = geometry.get("type") if isinstance(geometry, dict) else None
    area = props.get("Area")

    if gtype in ("Point", "MultiPoint"):
        if area is None:
            report.add("G021", SEVERITY_WARNING,
                       f"Point has no Area. The default of "
                       f"{POINT_DEFAULT_AREA_HA:g} ha will be assumed by the "
                       "receiving system.", where)
        elif not isinstance(area, (int, float)) or isinstance(area, bool):
            report.add("G022", SEVERITY_ERROR, "Area must be a number.", where)
        elif area <= 0:
            report.add("G023", SEVERITY_ERROR,
                       f"Area {area} must be greater than zero.", where)
        elif area > POINT_DEFAULT_AREA_HA:
            report.add("G024", SEVERITY_ERROR,
                       f"Area {area} ha exceeds {POINT_DEFAULT_AREA_HA:g} ha. "
                       "A plot above that threshold must be given as a polygon.",
                       where)
    elif gtype in ("Polygon", "MultiPolygon") and area is not None:
        if not isinstance(area, (int, float)) or isinstance(area, bool):
            report.add("G022", SEVERITY_ERROR, "Area must be a number.", where)
        else:
            measured = _measured_area_ha(geometry)
            if measured > 0 and (area > measured * 2 or area < measured / 2):
                report.add("G025", SEVERITY_WARNING,
                           f"Declared Area {area:g} ha differs from the geometry's "
                           f"own area of {measured:.2f} ha by more than a factor "
                           "of two.", where)

    if isinstance(country, str) and ISO_3166_1_ALPHA2.match(country or ""):
        _check_country_box(country, geometry, report, where)


def _measured_area_ha(geometry: dict) -> float:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    try:
        if gtype == "Polygon":
            return _ring_area_ha(coords[0])
        if gtype == "MultiPolygon":
            return sum(_ring_area_ha(p[0]) for p in coords)
    except (IndexError, TypeError):
        return 0.0
    return 0.0


def _check_country_box(country: str, geometry: Any, report: Report, where: str) -> None:
    box = COUNTRY_BBOX.get(country)
    if not box or not isinstance(geometry, dict):
        return
    min_lon, min_lat, max_lon, max_lat = box
    for pos in _iter_positions(geometry):
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue
        lon, lat = pos[0], pos[1]
        if not all(isinstance(v, (int, float)) for v in (lon, lat)):
            continue
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            swapped = (min_lon <= lat <= max_lon and min_lat <= lon <= max_lat)
            hint = (" The pair reads correctly when reversed, so the coordinates "
                    "are probably latitude-first.") if swapped else ""
            report.add("G026", SEVERITY_WARNING,
                       f"Position ({lon}, {lat}) lies outside the bounding box of "
                       f"declared country {country}.{hint}", where)
            return


def validate_obj(obj: Any, report: Report | None = None) -> Report:
    report = report or Report()

    if not isinstance(obj, dict):
        report.add("G001", SEVERITY_ERROR, "Top level must be a JSON object.")
        return report
    if obj.get("type") != "FeatureCollection":
        report.add("G002", SEVERITY_ERROR,
                   f"Top-level type must be 'FeatureCollection', found "
                   f"{obj.get('type')!r}.")
        return report

    features = obj.get("features")
    if not isinstance(features, list):
        report.add("G003", SEVERITY_ERROR, "'features' must be an array.")
        return report
    if not features:
        report.add("G004", SEVERITY_ERROR, "'features' is empty.")
        return report

    seen: dict[str, int] = {}
    for i, feature in enumerate(features):
        where = f"features[{i}]"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            report.add("G005", SEVERITY_ERROR,
                       "Each element of 'features' must be a Feature.", where)
            continue
        geometry = feature.get("geometry")
        _check_geometry(geometry, report, where)
        _check_properties(feature.get("properties"), geometry, report, where)

        if isinstance(geometry, dict):
            key = json.dumps(geometry.get("coordinates"), sort_keys=True)
            if key in seen:
                report.add("G027", SEVERITY_WARNING,
                           f"Geometry is identical to {seen[key]}.", where)
            else:
                seen[key] = i

    return report


def validate_file(path: str | Path) -> Report:
    path = Path(path)
    report = Report()
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        report.add("G000", SEVERITY_ERROR,
                   f"File is {size / 1024 / 1024:.1f} MB, above the 25 MB limit.")
        return report
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add("G001", SEVERITY_ERROR, f"File is not valid JSON: {exc}")
        return report
    return validate_obj(obj, report)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="validate_geojson",
        description=f"Validate a GeoJSON file against EUDR GeoJSON File "
                    f"Description v{SPEC_VERSION}.")
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true",
                        help="emit the report as JSON")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as failures")
    args = parser.parse_args(argv)

    report = validate_file(args.path)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        for finding in report.findings:
            print(finding)
        print(f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s).")
        print("conformant" if report.ok else "NOT conformant")

    if report.errors or (args.strict and report.warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
