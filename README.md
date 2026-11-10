# eudr-geojson-validator

Checks a GeoJSON file against the European Commission's **EUDR GeoJSON File
Description** — the format in which geolocation data for commodity plots is
submitted under Regulation (EU) 2023/1115 — and against the Regulation's own
definition of geolocation in Article 2(28), before the file is submitted.

**[Try it in your browser](https://aolagoke-dsae.github.io/eudr-geojson-validator/)**:
the same code, and the file stays on your machine.

[![validate](https://github.com/aolagoke-dsae/eudr-geojson-validator/actions/workflows/validate.yml/badge.svg)](https://github.com/aolagoke-dsae/eudr-geojson-validator/actions/workflows/validate.yml)

## Why now

The EUDR applies from 30 December 2026 to large and medium operators and
traders, and from 30 June 2027 to micro and small enterprises (from
30 December 2026 for those the EU Timber Regulation already covered). These
are the dates of its second amendment, [Regulation (EU) 2025/2650](https://eur-lex.europa.eu/eli/reg/2025/2650/oj/eng)
of 19 December 2025, as the [Commission's EUDR page](https://environment.ec.europa.eu/topics/forests/deforestation/regulation-deforestation-free-products_en)
gave them on 10 November 2026. Every due diligence statement carries the
geolocation of the plots a commodity came from, and the EU Information System
takes it as a GeoJSON file in the format the File Description sets out. The
description lists the errors the system raises on a file that departs from
it. Whether a file conforms is a question with a definite answer, and the
answer should come before the file is submitted rather than after it is
rejected.

## Install and run

```bash
pip install eudr-geojson-validator
eudr-validate my_plots.geojson
```

Python 3.10 or later, and nothing beyond its standard library. On
`data/edge_cases.geojson`, the repository's file of seven breaches and one
plot entered latitude first:

```text
$ eudr-validate data/edge_cases.geojson
ERROR G016 [features[0]]: Polygon ring is not closed: the last position must repeat the first.
ERROR G014 [features[1]]: Polygon declares 1 interior ring(s). Interior rings are not permitted.
WARNING G013 [features[2]]: 6 coordinate value(s) carry more than 6 decimal places (e.g. -6.4318801234). The EU system truncates to 6 before storing, so the extra digits are discarded.
ERROR G028 [features[2]]: Positions 0 and 1 differ as written but become the same point, (-6.431880, 6.895020), after truncation to 6 decimals. The EU system reduces coordinates to six decimals and rejects the duplicate.
ERROR G024 [features[3]]: Area 11.8 ha exceeds 4 ha. Regulation (EU) 2023/1115, Art. 2(28), requires polygons for plots of more than four hectares used for commodities other than cattle. If this file describes cattle establishments, run with --cattle.
ERROR G007 [features[4]]: Geometry type 'LineString' is not permitted. Allowed: Point, MultiPoint, Polygon, MultiPolygon.
ERROR G031 [features[5]]: The ring crosses or touches itself: sides 0 and 2 meet. The EC lists crossing lines, such as a figure eight, among the errors its system raises (item 1).
ERROR G019 [features[6]]: ProducerCountry 'UK' is not an ISO 3166-1 alpha-2 code. ISO 3166-1 writes GB. The EC lists an invalid producer country code among the errors its system raises (item 12).
WARNING G026 [features[7]]: Position (6.895020, -6.430110) lies outside the bounding box of declared country CI. The pair reads correctly when reversed, so the coordinates are probably latitude-first.

7 error(s), 2 warning(s); Type I rules.
NOT conformant
```

```bash
eudr-validate my_plots.geojson --strict   # warnings fail too
eudr-validate my_plots.geojson --type II  # commodity-level import
eudr-validate my_herds.geojson --cattle   # cattle: no polygon rule
eudr-validate my_plots.geojson --json     # the report as JSON
eudr-validate --version                   # version and specification
```

| Exit code | Meaning |
|---|---|
| `0` | The file passes: no error, and no warning under `--strict` |
| `1` | The file breaches the specification, or raises a warning under `--strict` |
| `2` | The command line is wrong, or the file cannot be read |
| `3` | The validator itself failed: an internal error, which says nothing about the file |

The run above exits `1`. With `--strict` and warnings only, the last line says
so — `conformant, but rejected under --strict` — instead of the bare
`conformant` that 1.1 printed while exiting `1`. `--json` adds `strict`,
`cattle` and `passed` to the report. From Python, `validate_file` and
`validate_obj` run the same checks and return the report:

```python
from eudr_geojson_validator import validate_file

report = validate_file("my_plots.geojson", file_type="II")
print(report.ok, [str(finding) for finding in report.errors])
```

## In the browser

[The demo](https://aolagoke-dsae.github.io/eudr-geojson-validator/) runs this
package's `validate.py`, unchanged, in Pyodide: Python compiled to
WebAssembly. A file dropped on the page is read in the browser tab and goes
nowhere. As it opens, the page fetches Python (up to 14 MB, from jsDelivr)
and the validator's source, then a sample file if one is asked for, and
nothing else. A first visit can take up to a minute on a slow connection;
after that the browser usually has Python in its cache. The page draws the
plots without a map background, so no map server learns where they are,
shows each finding beside its plot, and offers the report as the same JSON as
`eudr-validate --json`.

It is slower than the command line (see **Speed**). `tools/check_demo.js`,
run by hand, holds the demo to the command line in headless Chromium: the
same findings, word for word, the same JSON report, and no request that
carries any part of the file.

## Which specification

The Commission publishes the description twice, with separate version
numbers: as a PDF, version 1.5, dated 5 May 2025, and online in the EUDR
Information System's API reference, [version 1.3, updated 29 May 2026](https://eudr.webcloud.ec.europa.eu/tracesnt/help/eudr-documentation/operator/geojson-description.html).
This validator started from the PDF and follows the online version, the newer
of the two, wherever they differ; its numbered list of errors is the one the
codes below cite. The online version was checked on 10 and 18 October 2026,
and on 10 November 2026 it was still version 1.3. The validator's own version,
1.3.0, numbers its releases and not the Commission's documents; `--version`,
the JSON report's `specification` field and the demo name the document it
follows in full.

## Two kinds of finding

This is the whole idea, and it is the reason the tool is more than a schema
check.

| | Meaning | Example |
|---|---|---|
| **ERROR** | The file breaches the specification. A receiving system is entitled to reject it. | Polygon ring not closed; two vertices that become one when the EU system truncates to six decimals |
| **WARNING** | The file satisfies every structural rule and is still probably wrong. Nothing may reject it on this basis, and a person should look. | Coordinates entered latitude-first; declared area four times the geometry's own area; more than six decimals, which the system discards |

A plot whose coordinates were typed in the wrong order parses cleanly,
validates cleanly against the schema, and points at open ocean. Structure
alone cannot catch it. Comparing the position against the bounding box of the
country the record itself declares can, and when the pair reads correctly
reversed the warning says so.

## Type I and Type II files

The EC defines two variants with the same structure. They differ only in which
properties are required.

| | Used for | Properties |
|---|---|---|
| **Type I** (default) | The API, and the UI import at producer level | All optional: `ProducerName`, `ProducerCountry`, `ProductionPlace`, `Area` |
| **Type II** (`--type II`) | The UI import at commodity level, several producers in one file | `ProducerCountry` required in every Feature; the rest optional |

A Type II file groups producers by `ProducerName` and `ProducerCountry`, so a
Feature without a `ProducerName` raises a warning there.

## What is checked

| Code | Severity | Check |
|---|---|---|
| G000 | error | File above the 25 MB limit |
| G001 | error | Not UTF-8 text, not valid JSON, containing `NaN` / `Infinity`, or nested more than 100 levels deep (a geometry needs eight) |
| G002 | error | Top-level type is not `FeatureCollection` |
| G003 / G004 | error | `features` missing, not an array, or empty |
| G005 | error | Element of `features` is not a `Feature` |
| G006 / G008 | error | Geometry or coordinates missing, or a MultiPoint or MultiPolygon with no members |
| G007 | error | Geometry type outside Point, MultiPoint, Polygon, MultiPolygon |
| G009 | error | Coordinates nested at the wrong depth for the geometry type — a Polygon given `[5]`, or a Point given an array of positions (EC error 14) |
| G010 | error | Position is not a pair of numbers |
| G011 / G012 | error | Longitude outside ±180, latitude outside ±90 |
| G014 | error | Polygon declares an interior ring |
| G015 | error | Ring with fewer than four positions |
| G016 | error | Ring not closed |
| G018 | error | Type II only: `ProducerCountry` missing |
| G019 | error | `ProducerCountry` is not one of the 249 assigned ISO 3166-1 alpha-2 codes (EC error 12). For `EL` and `UK`, the EU's own codes, the message names `GR` and `GB` |
| G022 / G023 | error | `Area` not a finite number / not positive, on every geometry type. A quoted number is not a number (EC error 14) |
| G024 | error | Point declaring more than 4 ha: Regulation (EU) 2023/1115, Art. 2(28), requires a polygon. Not applied with `--cattle` |
| G028 | error | Two positions that become one when the EU system reduces coordinates to six decimals (EC error 7) |
| G030 | error | `properties` is neither an object nor null |
| G031 | error | Ring that crosses or touches itself, or folds back so that two sides overlap (EC errors 1 and 2) |
| G032 | error | Ring whose positions lie on one straight line, so it encloses no area (EC error 6) |
| G033 | error | A known property in the wrong case, such as `productionplace` (EC error 9) |
| G013 | warning | More than six decimal places: the EU system truncates them |
| G017 | warning | No `properties` member: RFC 7946 requires one, the EC's own example omits it |
| G020 | warning | Type II only: `ProducerName` missing |
| G021 | warning | Point without `Area`; the 4 ha default will be assumed |
| G025 | warning | Declared `Area` differs from the geometry's own area by more than a factor of two |
| G026 | warning | Position outside the bounding box of the declared country |
| G027 | warning | Geometry identical to an earlier feature |
| G029 | warning | Fewer than six decimal places as written; the Regulation asks for at least six |
| G034 | warning | `ProducerCountry` is `XK`: the code the EU uses for Kosovo, user-assigned and outside ISO 3166-1 |

"EC error *n*" refers to the numbered list of errors in the EC's GeoJSON file
description: the errors its system raises on submitted files.

Positions are `[longitude, latitude]` in WGS84, as the specification requires.

## Precision

Regulation (EU) 2023/1115, Article 2(28), defines geolocation as coordinates
"using at least six decimal digits". The EU system "will truncate coordinate
points to 6 decimal places before storing". So extra digits are harmless and
missing ones may fall short of the Regulation:

- **more than six** — G013, a warning: the extra digits are discarded.
- **fewer than six, as written** — G029, a warning. Digits are counted as the
  file writes them, so `6.500000` has six places and `6.5` has one. If the
  trailing digits are genuinely zero, write them out; some exporters drop them.
- **two positions that become one at six decimals** — G028, an error. The EC
  lists "Duplicate coordinates due to 6 decimals rounding in the system" among
  the errors its system raises. Its documentation calls the reduction
  truncation in one place and rounding in another, so both are checked.

Version 1.0 had the first two rules backwards: it rejected more than six
decimals as an error and passed files with five.

## Rings

A ring must not cross itself, touch itself or fold back along one of its own
sides (G031), and its positions must not all lie on one line (G032). The test
is exact: floating point decides only where it cannot be wrong, and the
numbers as written decide the rest. So a ring that only just touches itself is
found, and one that misses by a millionth of a degree is not. Sides are
straight lines in longitude and latitude, which at plot scale is the same as
on the ground.

`tools/compare_shapely.py` checks this against Shapely on 1,500 random rings
on a grid, simple and not. Given the grid's integers, where floating point is
exact, the two agree on every ring. Given the six-decimal coordinates,
Shapely passes 13 rings the validator flags: each is degenerate exactly as
written and not in binary floating point, where 6.8003 is not quite 6.8003.
The validator decides on the numbers as written.

## Speed

`tools/timing.py` writes its own files and times the check on them. On a
laptop (Intel Core i7-1165G7, Python 3.10, in a Linux virtual machine) on
10 November 2026: 10,000 polygons of 30 corners, 7.9 MB, in 13 seconds;
40,000 polygons of 10 corners, 14.5 MB, in 15 seconds; one ring of 5,000
positions in 0.4 seconds. Those runs came before 1.3.0's depth check, which
reads the whole file once before parsing it and took a further quarter of a
second on the 14.5 MB file. The README of 1.2 gave faster figures, from files
and a machine it did not record.

The browser takes about twice as long on the two large files. On one cloud
machine (Intel Xeon, 2.1 GHz, two cores) the command line, under Python 3.13,
checked the three files in 7.3, 11.8 and 0.17 seconds; the demo, in headless
Chromium with Pyodide 314.0.7 and Python 3.14, took 13 to 17, 22 to 23, and
0.4 to 0.6 seconds in two sessions.

## The four-hectare rule and cattle

The GeoJSON description sets a default: a Point without `Area` counts as
4 ha. The rule that a larger plot must be a polygon is the Regulation's,
Article 2(28), and it applies to plots "other than cattle". A GeoJSON file
does not say which commodity it serves, so the exemption is stated on the
command line: `--cattle` switches G024 off. Without it, a Point above 4 ha is
an error. G024 applies to a Point: the EC defines `Area` for a Point and says
nothing about it for a MultiPoint, whose `Area` is checked only for being a
positive number.

## What this does not do

It does not assess deforestation, and it makes no statement about whether a
plot is compliant. It does not connect to TRACES or the EUDR Information
System, and it submits nothing. It does not validate the non-geographic parts
of a Due Diligence Statement. It checks one file against one published
schema, and it says where that file departs from it.

It is not legal advice. A file it passes can still be refused by the EU
Information System, whose checks are the Commission's own and can change, and
a conforming file says nothing about whether the products it covers comply
with the Regulation.

The country bounding boxes cover thirty-four commodity-producing
countries. A record declaring a country outside that list gets no G026 check,
which is a gap rather than a pass.

### Known gaps

Version 1.1 listed eight; 1.2 closes them (see **Changes**). Still not
checked:

- overlaps between the polygons of one MultiPolygon, or between features;
- the EC's description of a MultiPoint or MultiPolygon as "two or more"
  members: a single-member one is not flagged, since the EC's list of errors
  does not include it.

The 25 MB limit behind G000 is not stated in the GeoJSON file description.
It is the cap commonly reported for a whole due diligence statement, and it
is kept as a guard rather than as a rule of the specification.

## Area

Polygon area is computed from the spherical excess of the ring, with an Earth
radius of 6 371 008.8 m. That is accurate to well under a percent at plot
scale and needs no projection library. The G025 threshold is deliberately
loose — a factor of two — because a declared area is an estimate and the point
is to catch a misplaced decimal, not to argue about surveying.

## Tests

```bash
pip install -e ".[test]"
python -m pytest -q        # 91 passed
```

Most tests hold the specification and the Regulation, each beside the text it
follows; the rest hold the warning layer, the area computation against a
closed-form area, the command line and its exit codes, and the shipped
fixtures. `data/edge_cases.geojson` holds seven deliberate breaches and one
plot entered latitude first, and CI asserts that it **keeps failing**. A
validator that silently stops catching things is worse than no validator,
because it is trusted.

`tools/mutants.py` holds 59 mutants of the validator, copies with one rule
reverted or weakened, and runs the suite against each: every mutant makes at
least one test fail (10 November 2026). Twelve of them survived the suite of
1.2, among them latitudes up to 91, booleans read as coordinates, and a ring
that touches itself where the touching side happens to be tested first; each
has a test now. The 50 mutants 1.2 was checked against were not kept, which is
why the set is a script now. An audit of version 1.0 found 35 of its 48
mutants surviving, among them an area computation multiplied by ten.

`tools/check_demo.js` holds the browser demo to the command line's answers
(see **In the browser**); with the depth check switched off, three of its
checks fail.

`data/valid_plots.geojson` uses clearly-labelled test identities. It is not
derived from any real operator.

## Status

Version 1.3.0, 10 November 2026. The gaps above are known and listed rather
than discovered. Runtime dependencies: none beyond the Python standard
library. CI runs the tests and the installed command on Python 3.10 to 3.14,
on Linux and on Windows, on every push and every Monday, and builds the
package; a second workflow tests on Python 3.14 and publishes the demo when
the validator, its samples or the demo change.

## Changes

**1.3.0 — 10 November 2026.** A package with its own command, a browser demo,
and two tracebacks turned into answers:

- on PyPI as `eudr-geojson-validator`, with the command `eudr-validate`;
  `python -m eudr_geojson_validator` works too, and so, for now, does
  `python -m src.validate_geojson`;
- the version is the validator's own. 1.2 reported `"spec_version": "1.5"`,
  the PDF's number, while it followed the online version 1.3; the JSON report
  now has `specification`, which names the document in full, and `--version`
  gives both;
- a file nested more than 100 levels deep is G001, found before the file is
  parsed, so the answer is the same on every Python and in the browser; 1.2
  stopped with a RecursionError traceback and exit code `1`;
- a fault in the validator itself exits `3`, not `1`, which a pipeline would
  read as a verdict on the file;
- CI on Python 3.10 to 3.14, on Linux and Windows, weekly as well as on every
  push, with the package built and its wheel installed in a clean
  environment;
- `tools/mutants.py`, `tools/compare_shapely.py` and `tools/timing.py`
  reproduce the claims above; the suite grows from 69 tests to 91, and all 59
  mutants are killed;
- the browser demo, on GitHub Pages, and `tools/check_demo.js`;
- the README gives the dates the EUDR applies from, a sample run, and the
  line that this is not legal advice.

**1.2 — 18 October 2026.** The eight gaps 1.1 listed are closed:

- rings that cross, touch or fold back on themselves (G031) and rings with no
  area (G032), the EC's errors 1, 2 and 6;
- `ProducerCountry` is checked against the 249 assigned ISO 3166-1 codes, not
  only their form (G019, error 12), so `XX` fails; `XK`, the EU's code for
  Kosovo, is a warning (G034);
- a known property in the wrong case is an error (G033, error 9);
- G024 cites Article 2(28), applies to Points only, and `--cattle` exempts
  cattle establishments;
- `Area` must be a positive, finite number on every geometry type;
- an empty MultiPoint or MultiPolygon is G008, and coordinates nested at the
  wrong depth are G009 instead of a Python traceback;
- exit codes are documented (`2` for a file that cannot be read), and
  `--strict` says why it rejects a conformant file;
- 36 new tests, including a closed-form area, the 4 ha and factor-of-two
  boundaries, MultiPoint and MultiPolygon cases and the command line; the
  edge-case fixture gains a figure-eight ring and a `UK` country code.

**1.1 — 10 October 2026.** Two rules corrected against the EC documentation
and the Regulation, after an audit found them backwards:

- more than six decimals is now a warning (G013), not an error; fewer than six
  as written is a new warning (G029); positions that collapse at six decimals
  are a new error (G028);
- `ProducerName` and `ProducerCountry` are optional, as the EC lists them,
  except `ProducerCountry` in a Type II file (`--type II`). A Feature without
  a `properties` member is a warning (G017), and `"properties": null` is valid;
- a file that is not UTF-8, or that contains `NaN`, is reported as G001
  instead of a traceback;
- the reference fixture writes six decimals, as the Regulation asks.

**1.0 — 6 October 2026.** First release.

## Licence

MIT.
