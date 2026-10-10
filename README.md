# eudr-geojson-validator

Checks a GeoJSON file against the European Commission's **EUDR GeoJSON File
Description, version 1.5** — the format in which geolocation data for
commodity plots is submitted under Regulation (EU) 2023/1115 — and against the
Regulation's own definition of geolocation in Article 2(28). The rules follow
the EC's online [GeoJSON file description](https://eudr.webcloud.ec.europa.eu/tracesnt/help/eudr-documentation/operator/geojson-description.html)
(version 1.3, updated 29 May 2026), checked on 10 October 2026.

[![validate](https://github.com/aolagoke-dsae/eudr-geojson-validator/actions/workflows/validate.yml/badge.svg)](https://github.com/aolagoke-dsae/eudr-geojson-validator/actions/workflows/validate.yml)

```bash
python -m src.validate_geojson data/valid_plots.geojson
python -m src.validate_geojson data/edge_cases.geojson --json
python -m src.validate_geojson my_plots.geojson --strict   # warnings fail too
python -m src.validate_geojson my_plots.geojson --type II  # commodity-level import
```

Exit code is `1` when the file breaches the specification — or, with
`--strict`, when it raises any warning — and `0` otherwise.

## Why it exists

The specification is a published document. Whether a file conforms to it is a
question with a definite answer, and that answer should be available before
the file is submitted anywhere rather than after it is rejected.

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
| G001 | error | Not UTF-8 text, not valid JSON, or containing `NaN` / `Infinity` |
| G002 | error | Top-level type is not `FeatureCollection` |
| G003 / G004 | error | `features` missing, not an array, or empty |
| G005 | error | Element of `features` is not a `Feature` |
| G006 / G008 | error | Geometry or coordinates missing |
| G007 | error | Geometry type outside Point, MultiPoint, Polygon, MultiPolygon |
| G010 | error | Position is not a pair of numbers |
| G011 / G012 | error | Longitude outside ±180, latitude outside ±90 |
| G014 | error | Polygon declares an interior ring |
| G015 | error | Ring with fewer than four positions |
| G016 | error | Ring not closed |
| G018 | error | Type II only: `ProducerCountry` missing |
| G019 | error | `ProducerCountry` not in the form of an ISO 3166-1 alpha-2 code |
| G022 / G023 | error | `Area` not a number / not positive (see Known gaps) |
| G024 | error | Point declaring more than 4 ha, which must be a polygon |
| G028 | error | Two positions that become one when the EU system reduces coordinates to six decimals |
| G030 | error | `properties` is neither an object nor null |
| G013 | warning | More than six decimal places: the EU system truncates them |
| G017 | warning | No `properties` member: RFC 7946 requires one, the EC's own example omits it |
| G020 | warning | Type II only: `ProducerName` missing |
| G021 | warning | Point without `Area`; the 4 ha default will be assumed |
| G025 | warning | Declared `Area` differs from the geometry's own area by more than a factor of two |
| G026 | warning | Position outside the bounding box of the declared country |
| G027 | warning | Geometry identical to an earlier feature |
| G029 | warning | Fewer than six decimal places as written; the Regulation asks for at least six |

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

## What this does not do

It does not assess deforestation, and it makes no statement about whether a
plot is compliant. It does not connect to TRACES or the EUDR Information
System, and it submits nothing. It does not validate the non-geographic parts
of a Due Diligence Statement. It checks one file against one published
schema, and it says where that file departs from it.

The country bounding boxes cover thirty-four commodity-producing
countries. A record declaring a country outside that list gets no G026 check,
which is a gap rather than a pass.

### Known gaps

Not yet checked:

- self-intersecting ("figure eight") rings, and polygons whose points lie on
  one line — items 1 and 6 of the EC's list of errors;
- property names in the wrong case, such as `productionplace` for
  `ProductionPlace` — item 9;
- whether `ProducerCountry` is an existing ISO 3166-1 code — item 12. G019
  checks the form only, so `XX` passes;
- the Regulation's cattle exemption: G024 treats every Point above 4 ha as a
  breach, although Article 2(28) requires polygons only for plots "other than
  cattle";
- an `Area` of zero or below on a Polygon, which G023 checks for Points only;
- a MultiPolygon or MultiPoint whose coordinates array is empty — no location
  at all — which currently passes;
- coordinates nested at the wrong depth (a Polygon given `[5]`), which can
  stop the run with a Python error instead of a finding.

## Area

Polygon area is computed from the spherical excess of the ring, with an Earth
radius of 6 371 008.8 m. That is accurate to well under a percent at plot
scale and needs no projection library. The G025 threshold is deliberately
loose — a factor of two — because a declared area is an estimate and the point
is to catch a misplaced decimal, not to argue about surveying.

## Tests

```bash
pip install -r requirements.txt
python -m pytest -q        # 33 passed
```

Twenty-seven tests hold the specification and the Regulation, each beside the
text it follows; three hold the warning layer; three hold the shipped fixtures. `data/edge_cases.geojson` contains six deliberate
defects, and CI asserts that it **keeps failing**. A validator that silently
stops catching things is worse than no validator, because it is trusted.

`data/valid_plots.geojson` uses clearly-labelled test identities. It is not
derived from any real operator.

## Status

Version 1.1, 10 October 2026. The gaps above are known and listed rather than
discovered. Runtime dependencies: none beyond the Python standard library. CI
runs the suite on Python 3.10, 3.11 and 3.12.

## Changes

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
