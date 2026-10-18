"""Validate a GeoJSON file against the European Commission's
EUDR GeoJSON File Description, version 1.5.

Sources, checked 10 October 2026 and again on 18 October 2026:
  * EUDR GeoJSON File Description v1.5 (5 May 2025), and the EC's online
    "GeoJSON file description", version 1.3 updated 29 May 2026, with its
    numbered list of the errors the EU system raises:
    https://eudr.webcloud.ec.europa.eu/tracesnt/help/eudr-documentation/operator/geojson-description.html
  * Regulation (EU) 2023/1115, Article 2(28): geolocation "using at least six
    decimal digits"; polygons for plots of more than four hectares "other than
    cattle".

Version 1.0 of this module got two rules backwards. It rejected coordinates
with more than six decimals, although the Regulation asks for AT LEAST six and
the EU system truncates longer ones; and it required ProducerName and
ProducerCountry in every file, although the EC lists both as optional except
ProducerCountry in a Type II file. Version 1.1 follows the text above.

Version 1.2 closes the gaps 1.1 listed: rings that cross, touch or fold back
on themselves and rings with no area (the EC's errors 1, 2 and 6), property
names in the wrong case (9), country codes that ISO 3166-1 does not assign
(12), empty Multi* geometries, coordinates nested at the wrong depth, Area
checked on every geometry type, and the Regulation's cattle exemption from the
four-hectare rule.

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
import sys
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

SPEC_VERSION = "1.5"
VALIDATOR_VERSION = "1.2"
MAX_FILE_BYTES = 25 * 1024 * 1024
SYSTEM_DECIMALS = 6   # the EU system truncates to six before storing
MIN_DECIMALS = 6      # Regulation (EU) 2023/1115, Art. 2(28): "at least six"
FILE_TYPES = ("I", "II")
NUMBER = (int, float, Decimal)
POINT_DEFAULT_AREA_HA = 4.0
ALLOWED_GEOMETRY = ("Point", "MultiPoint", "Polygon", "MultiPolygon")
EARTH_RADIUS_M = 6_371_008.8

# ISO 3166-1 alpha-2: the 249 officially assigned codes, as listed by
# pycountry 26.2.16 (Debian iso-codes), checked 18 October 2026. The EC asks
# for "the country of production ISO2 code" and lists an invalid one among the
# errors its system raises (item 12). v1.1 checked only the form, so XX passed.
ISO_3166_1_ALPHA2 = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF
BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG
CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC
EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL
GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN
IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA
LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN
MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP
NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO
RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV
SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG
UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())
# Codes that look right and are not ISO 3166-1, with the code that is. The EU
# itself writes EL for Greece and UK for the United Kingdom.
NOT_ISO_3166_1 = {"EL": "GR", "UK": "GB"}
# User-assigned and outside ISO 3166-1, but the code the EU uses for Kosovo.
EU_USER_ASSIGNED = {"XK": "Kosovo"}
# Property names are case-sensitive (the EC's list of errors, item 9).
KNOWN_PROPERTIES = ("ProducerName", "ProducerCountry", "ProductionPlace", "Area")

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
    file_type: str = "I"

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
            "validator_version": VALIDATOR_VERSION,
            "file_type": self.file_type,
            "conformant": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [
                {"code": f.code, "severity": f.severity,
                 "message": f.message, "where": f.where}
                for f in self.findings
            ],
        }


def _decimals(value: float | int | Decimal) -> int:
    """Decimal places as written in the file.

    validate_file parses numbers as Decimal, which keeps the digits exactly as
    written: "6.500000" has six places, "6.5" has one. A float -- validate_obj
    called from Python -- carries no such record, so its shortest repr is the
    best available reading. (v1.0 claimed to count "as written" while reading
    floats, so 6.8950230 passed as six places.)
    """
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        return -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if isinstance(value, int):
        return 0
    text = format(Decimal(repr(value)), "f")
    return len(text.split(".")[1]) if "." in text else 0


def _as_decimal(value: float | int | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)


_SIX_PLACES = Decimal(1).scaleb(-SYSTEM_DECIMALS)


def _collapse(positions: Any) -> tuple[int, int, str, tuple] | None:
    """Two positions distinct as written that become one at six decimals.

    The EC lists this among the errors its system raises: "Duplicate
    coordinates due to 6 decimals rounding in the system". Its documentation
    calls the reduction truncation in one place and rounding in another, so
    both are tried. Positions already identical as written are a different
    defect and are not reported here.
    """
    if not isinstance(positions, list):
        return None
    pts = [
        (_as_decimal(p[0]), _as_decimal(p[1]))
        for p in positions
        if isinstance(p, (list, tuple)) and len(p) >= 2
        and all(isinstance(v, NUMBER) and not isinstance(v, bool) for v in p[:2])
    ]
    for mode, label in ((ROUND_DOWN, "truncation"), (ROUND_HALF_UP, "rounding")):
        seen: dict[tuple, int] = {}
        for i, (lon, lat) in enumerate(pts):
            key = (lon.quantize(_SIX_PLACES, rounding=mode),
                   lat.quantize(_SIX_PLACES, rounding=mode))
            j = seen.get(key)
            if j is not None and pts[j] != (lon, lat):
                return j, i, label, key
            seen.setdefault(key, i)
    return None


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


# How deep each geometry type nests its coordinates: a position is a list of
# numbers, a ring a list of positions, a polygon a list of rings.
_DEPTH = {"Point": 1, "MultiPoint": 2, "Polygon": 3, "MultiPolygon": 4}
_SHAPE = {
    "Point": "one position, [longitude, latitude], not an array of positions "
             "(the EC's list of errors, item 14)",
    "MultiPoint": "an array of positions",
    "Polygon": "an array of rings, each an array of positions",
    "MultiPolygon": "an array of polygons, each an array of rings",
}


def _nesting_ok(value: Any, depth: int) -> bool:
    """True when value is a list nested exactly `depth` deep.

    v1.1 walked the coordinates without looking first, so a Polygon given
    [5] stopped the run with a TypeError instead of producing a finding.
    """
    if not isinstance(value, list):
        return False
    if depth == 1:
        return not any(isinstance(v, (list, dict)) for v in value)
    return all(_nesting_ok(v, depth - 1) for v in value)


def _is_number(value: Any) -> bool:
    """A finite number. NaN reaches here only through validate_obj: the file
    reader refuses it as G001."""
    if isinstance(value, bool) or not isinstance(value, NUMBER):
        return False
    return value.is_finite() if isinstance(value, Decimal) else math.isfinite(value)


def _ring_points(ring: list) -> list[tuple] | None:
    """Each position as (lon, lat, float lon, float lat), or None when one is
    not a finite pair of numbers (that already carries G010, G011 or G012)."""
    pts = []
    for p in ring:
        if not (isinstance(p, list) and len(p) >= 2 and _is_number(p[0])
                and _is_number(p[1])):
            return None
        pts.append((p[0], p[1], float(p[0]), float(p[1])))
    return pts


def _orient(a: tuple, b: tuple, c: tuple) -> int:
    """Sign of the turn a -> b -> c: 1 left, -1 right, 0 straight.

    Exact. Floating point decides only where its error bound cannot change
    the sign; elsewhere fractions of the numbers as written decide.
    """
    d1, d2, d3, d4 = b[2] - a[2], c[3] - a[3], b[3] - a[3], c[2] - a[2]
    t1, t2 = d1 * d2, d3 * d4
    v = t1 - t2
    bound = 1e-12 * (abs(d1) + abs(d2) + abs(d3) + abs(d4)) + 1e-15 * (abs(t1) + abs(t2))
    if v > bound:
        return 1
    if v < -bound:
        return -1
    f = Fraction
    e = ((f(b[0]) - f(a[0])) * (f(c[1]) - f(a[1]))
         - (f(b[1]) - f(a[1])) * (f(c[0]) - f(a[0])))
    return (e > 0) - (e < 0)


def _within(a: tuple, b: tuple, c: tuple) -> bool:
    """c lies in the box spanned by a and b; with c on the line ab, on the side."""
    return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))


def _segments_meet(p1: tuple, p2: tuple, q1: tuple, q2: tuple) -> bool:
    """Do the sides p1-p2 and q1-q2 share any point: cross, touch or overlap?"""
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return True
    return ((d1 == 0 and _within(q1, q2, p1)) or (d2 == 0 and _within(q1, q2, p2))
            or (d3 == 0 and _within(p1, p2, q1)) or (d4 == 0 and _within(p1, p2, q2)))


def _ring_shape_problem(ring: list) -> tuple[str, str] | None:
    """G032 for a closed ring with no area, G031 for one that crosses, touches
    or folds back on itself, None for a simple ring.

    The EC lists among the errors its system raises "crossing coordinate
    lines", such as a figure eight (item 1), overlapping sides, including
    inward-folding ones (item 2), and coordinates that represent straight lines
    (item 6). The test is exact: floating point decides only where it cannot be
    wrong, and the numbers as written, as fractions, decide the rest. So a ring
    that just touches itself is found and one that just misses is not. Sides
    are straight lines in longitude and latitude, which at plot scale is the
    same as on the ground.
    """
    pts = _ring_points(ring)
    if pts is None:
        return None
    v: list = []
    for p in pts[:-1]:                 # the last position repeats the first
        if not v or p != v[-1]:        # a repeated position adds no side
            v.append(p)
    while len(v) > 1 and v[-1] == v[0]:
        v.pop()
    if len(v) < 3 or all(_orient(v[0], v[1], p) == 0 for p in v[2:]):
        return ("G032", "The ring's positions lie on one straight line, so it "
                "encloses no area. The EC lists coordinates that represent "
                "straight lines among the errors its system raises (item 6).")
    n = len(v)
    # Two sides that meet at a position overlap when the turn there is
    # straight and the second side runs back along the first.
    for i in range(n):
        a, s, b = v[i - 1], v[i], v[(i + 1) % n]
        if _orient(a, s, b) != 0:
            continue
        f = Fraction
        back = ((f(a[0]) - f(s[0])) * (f(b[0]) - f(s[0]))
                + (f(a[1]) - f(s[1])) * (f(b[1]) - f(s[1])))
        if back > 0:
            return ("G031", f"The ring folds back on itself at its position "
                    f"{i}: two sides overlap. The EC lists overlapping sides "
                    "among the errors its system raises (item 2).")
    # Sides that do not share a position must not meet at all. Sweeping the
    # sides by longitude keeps a detailed polygon from costing n² exact tests.
    edges = [(v[i], v[(i + 1) % n]) for i in range(n)]
    lo = [min(e[0][2], e[1][2]) for e in edges]
    hi = [max(e[0][2], e[1][2]) for e in edges]
    order = sorted(range(n), key=lo.__getitem__)
    for k, i in enumerate(order):
        reach = hi[i] + 1e-9           # a margin over float rounding keeps exact touches in
        for j in order[k + 1:]:
            if lo[j] > reach:
                break
            if abs(i - j) in (1, n - 1):
                continue
            if _segments_meet(*edges[i], *edges[j]):
                first, second = sorted((i, j))
                return ("G031", f"The ring crosses or touches itself: sides "
                        f"{first} and {second} meet. The EC lists crossing lines, "
                        "such as a figure eight, among the errors its system "
                        "raises (item 1).")
    return None


def _check_position(pos: Any, report: Report, where: str) -> bool:
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        report.add("G010", SEVERITY_ERROR,
                   "Position must be an array of at least two numbers.", where)
        return False
    lon, lat = pos[0], pos[1]
    if not all(isinstance(v, NUMBER) and not isinstance(v, bool)
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
    return ok


def _check_geometry(geometry: Any, report: Report, where: str) -> bool:
    """Structure and precision. Returns True when the coordinates are nested
    as the geometry type requires, so later checks may walk them."""
    if not isinstance(geometry, dict):
        report.add("G006", SEVERITY_ERROR, "Feature has no geometry object.", where)
        return False
    gtype = geometry.get("type")
    if gtype not in ALLOWED_GEOMETRY:
        report.add("G007", SEVERITY_ERROR,
                   f"Geometry type {gtype!r} is not permitted. "
                   f"Allowed: {', '.join(ALLOWED_GEOMETRY)}.", where)
        return False
    coords = geometry.get("coordinates")
    if coords is None:
        report.add("G008", SEVERITY_ERROR, "Geometry has no coordinates.", where)
        return False
    if not _nesting_ok(coords, _DEPTH[gtype]):
        report.add("G009", SEVERITY_ERROR,
                   f"Coordinates are not nested as a {gtype} requires: "
                   f"{_SHAPE[gtype]}.", where)
        return False
    if gtype in ("MultiPoint", "MultiPolygon") and not coords:
        # v1.1 passed this with no finding at all.
        report.add("G008", SEVERITY_ERROR,
                   f"{gtype} has no members, so it gives no location.", where)
        return False

    over: list = []
    under: list = []
    for pos in _iter_positions(geometry):
        if _check_position(pos, report, where):
            for value in pos[:2]:
                places = _decimals(value)
                if places > SYSTEM_DECIMALS:
                    over.append(value)
                elif places < MIN_DECIMALS:
                    under.append(value)
    # One finding per Feature, not one per vertex: a 5,000-vertex polygon
    # exported at five decimals is one problem, not 10,000.
    if over:
        report.add("G013", SEVERITY_WARNING,
                   f"{len(over)} coordinate value(s) carry more than "
                   f"{SYSTEM_DECIMALS} decimal places (e.g. {over[0]}). The EU "
                   f"system truncates to {SYSTEM_DECIMALS} before storing, so "
                   "the extra digits are discarded.", where)
    if under:
        report.add("G029", SEVERITY_WARNING,
                   f"{len(under)} coordinate value(s) are written with fewer "
                   f"than {MIN_DECIMALS} decimal places (e.g. {under[0]}). "
                   "Regulation (EU) 2023/1115, Art. 2(28), asks for at least "
                   "six; if the trailing digits are genuinely zero, write them "
                   "out.", where)

    if gtype == "Polygon":
        _check_rings(coords, report, where)
    elif gtype == "MultiPolygon":
        for p, polygon in enumerate(coords):
            _check_rings(polygon, report, f"{where}/polygon[{p}]")
    elif gtype == "MultiPoint":
        _report_collapse(_collapse(coords), report, where)
    return True


def _report_collapse(hit: tuple | None, report: Report, where: str) -> None:
    if hit:
        j, i, label, key = hit
        report.add("G028", SEVERITY_ERROR,
                   f"Positions {j} and {i} differ as written but become the same "
                   f"point, ({key[0]}, {key[1]}), after {label} to "
                   f"{SYSTEM_DECIMALS} decimals. The EU system reduces "
                   "coordinates to six decimals and rejects the duplicate.",
                   where)


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
        _report_collapse(_collapse(outer), report, where)
    else:
        _report_collapse(_collapse(outer[:-1]), report, where)
        problem = _ring_shape_problem(outer)
        if problem:
            report.add(problem[0], SEVERITY_ERROR, problem[1], where)


def _check_properties(feature: dict, geometry: Any, report: Report, where: str,
                      file_type: str, walkable: bool = True,
                      cattle: bool = False) -> None:
    """ProducerName, ProducerCountry, ProductionPlace and Area are optional:
    "The system additionally accepts and will process the following optional
    properties". A Type I file "May include any of the optional properties";
    a Type II file "Includes the "ProducerCountry" property per "Feature"".
    (EC GeoJSON file description, 29 May 2026.)
    """
    if "properties" not in feature:
        report.add("G017", SEVERITY_WARNING,
                   "Feature has no 'properties' member. RFC 7946, section 3.2, "
                   "requires one (an object, or null); the EC's own "
                   "single-Feature example omits it, so the EU system evidently "
                   "accepts this.", where)
    props = feature.get("properties")
    if props is None:
        props = {}
    elif not isinstance(props, dict):
        report.add("G030", SEVERITY_ERROR,
                   f"'properties' must be an object or null, found "
                   f"{type(props).__name__}.", where)
        return

    # Names are case-sensitive; the system ignores other names, so only a
    # wrongly cased known one is reported.
    for key in props:
        for name in KNOWN_PROPERTIES:
            if isinstance(key, str) and key != name and key.lower() == name.lower():
                report.add("G033", SEVERITY_ERROR,
                           f"Property {key!r} must be spelled {name!r}: property "
                           "names are case-sensitive, and the EC lists a wrongly "
                           "cased one among the errors its system raises "
                           "(item 9).", where)

    country = props.get("ProducerCountry")
    if country is None:
        if file_type == "II":
            report.add("G018", SEVERITY_ERROR,
                       "ProducerCountry is required in a Type II file, once per "
                       "Feature.", where)
    elif isinstance(country, str) and country in EU_USER_ASSIGNED:
        report.add("G034", SEVERITY_WARNING,
                   f"ProducerCountry {country!r} ({EU_USER_ASSIGNED[country]}) is a "
                   "user-assigned code the EU uses, not an ISO 3166-1 code. Check "
                   "that the receiving system accepts it.", where)
    elif not isinstance(country, str) or country not in ISO_3166_1_ALPHA2:
        hint = (f" ISO 3166-1 writes {NOT_ISO_3166_1[country]}."
                if isinstance(country, str) and country in NOT_ISO_3166_1 else "")
        report.add("G019", SEVERITY_ERROR,
                   f"ProducerCountry {country!r} is not an ISO 3166-1 alpha-2 "
                   f"code.{hint} The EC lists an invalid producer country code "
                   "among the errors its system raises (item 12).", where)

    if file_type == "II" and props.get("ProducerName") in (None, ""):
        report.add("G020", SEVERITY_WARNING,
                   "Type II files group producers by ProducerName and "
                   "ProducerCountry; this Feature has no ProducerName.", where)

    gtype = geometry.get("type") if isinstance(geometry, dict) else None
    area = props.get("Area")

    # G022 and G023 hold for every geometry type; v1.1 checked a polygon's
    # Area for being a number only, so -5 passed.
    area_ok = False
    if area is not None:
        if not _is_number(area):
            quoted = (" A quoted number reads as an area of 0 (the EC's list of "
                      "errors, item 14)." if isinstance(area, str) else "")
            report.add("G022", SEVERITY_ERROR,
                       f"Area must be a finite number.{quoted}", where)
        elif area <= 0:
            report.add("G023", SEVERITY_ERROR,
                       f"Area {area} must be greater than zero.", where)
        else:
            area_ok = True

    if gtype in ("Point", "MultiPoint") and area is None:
        report.add("G021", SEVERITY_WARNING,
                   f"Point has no Area. The default of "
                   f"{POINT_DEFAULT_AREA_HA:g} ha will be assumed by the "
                   "receiving system.", where)
    # The four-hectare rule is the Regulation's, not the specification's, and
    # it exempts cattle. A GeoJSON file does not say which commodity it
    # serves, so the exemption is the user's to state (--cattle). It applies
    # to a Point: the EC defines Area for a Point, not for a MultiPoint.
    if gtype == "Point" and area_ok and area > POINT_DEFAULT_AREA_HA and not cattle:
        report.add("G024", SEVERITY_ERROR,
                   f"Area {area} ha exceeds {POINT_DEFAULT_AREA_HA:g} ha. "
                   "Regulation (EU) 2023/1115, Art. 2(28), requires polygons for "
                   "plots of more than four hectares used for commodities other "
                   "than cattle. If this file describes cattle establishments, "
                   "run with --cattle.", where)
    if gtype in ("Polygon", "MultiPolygon") and area_ok and walkable:
        measured = _measured_area_ha(geometry)
        if measured > 0 and (area > measured * 2 or area < measured / 2):
            report.add("G025", SEVERITY_WARNING,
                       f"Declared Area {area:g} ha differs from the geometry's "
                       f"own area of {measured:.2f} ha by more than a factor "
                       "of two.", where)

    if walkable and isinstance(country, str) and country in ISO_3166_1_ALPHA2:
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
        if not all(isinstance(v, NUMBER) for v in (lon, lat)):
            continue
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            swapped = (min_lon <= lat <= max_lon and min_lat <= lon <= max_lat)
            hint = (" The pair reads correctly when reversed, so the coordinates "
                    "are probably latitude-first.") if swapped else ""
            report.add("G026", SEVERITY_WARNING,
                       f"Position ({lon}, {lat}) lies outside the bounding box of "
                       f"declared country {country}.{hint}", where)
            return


def validate_obj(obj: Any, report: Report | None = None,
                 file_type: str = "I", cattle: bool = False) -> Report:
    """Validate a parsed GeoJSON object. cattle=True states that the file
    describes cattle establishments, which Art. 2(28) exempts from G024."""
    if file_type not in FILE_TYPES:
        raise ValueError(f"file_type must be one of {FILE_TYPES}, not {file_type!r}")
    report = report or Report()
    report.file_type = file_type

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
        walkable = _check_geometry(geometry, report, where)
        _check_properties(feature, geometry, report, where, file_type,
                          walkable, cattle)

        if isinstance(geometry, dict):
            key = json.dumps(geometry.get("coordinates"), sort_keys=True,
                             default=float)
            if key in seen:
                report.add("G027", SEVERITY_WARNING,
                           f"Geometry is identical to {seen[key]}.", where)
            else:
                seen[key] = i

    return report


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a JSON number (RFC 8259)")


def validate_file(path: str | Path, file_type: str = "I",
                  cattle: bool = False) -> Report:
    path = Path(path)
    report = Report(file_type=file_type)
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        report.add("G000", SEVERITY_ERROR,
                   f"File is {size / 1024 / 1024:.1f} MB, above the 25 MB limit.")
        return report
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        report.add("G001", SEVERITY_ERROR, f"File is not UTF-8 text: {exc}")
        return report
    try:
        # Decimal keeps every number exactly as written, which the precision
        # rules need; NaN and Infinity are not JSON and are refused here.
        obj = json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    except ValueError as exc:
        report.add("G001", SEVERITY_ERROR, f"File is not valid JSON: {exc}")
        return report
    return validate_obj(obj, report, file_type, cattle)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="validate_geojson",
        description=f"Validate a GeoJSON file against EUDR GeoJSON File "
                    f"Description v{SPEC_VERSION}.",
        epilog="Exit status: 0 the file passes; 1 it breaches the "
               "specification, or raises a warning under --strict; 2 the "
               "command line is wrong or the file cannot be read.")
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true",
                        help="emit the report as JSON")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as failures")
    parser.add_argument("--type", choices=FILE_TYPES, default="I",
                        help="I: API or producer-level import, every property "
                             "optional (default). II: commodity-level import, "
                             "ProducerCountry required per Feature.")
    parser.add_argument("--cattle", action="store_true",
                        help="the file describes establishments where cattle are "
                             "kept: Regulation (EU) 2023/1115, Art. 2(28), does "
                             "not require polygons for them, so G024 is not "
                             "applied")
    args = parser.parse_args(argv)

    try:
        report = validate_file(args.path, args.type, cattle=args.cattle)
    except OSError as exc:
        print(f"validate_geojson: cannot read {args.path}: {exc.strerror or exc}",
              file=sys.stderr)
        return 2
    failed = bool(report.errors) or (args.strict and bool(report.warnings))

    if args.json:
        out = report.as_dict()
        out.update({"strict": args.strict, "cattle": args.cattle,
                    "passed": not failed})
        print(json.dumps(out, indent=2))
    else:
        for finding in report.findings:
            print(finding)
        print(f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s); "
              f"Type {args.type} rules.")
        # v1.1 printed "conformant" here and still exited 1 under --strict.
        if report.errors:
            print("NOT conformant")
        elif failed:
            print(f"conformant, but rejected under --strict: "
                  f"{len(report.warnings)} warning(s)")
        else:
            print("conformant")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
