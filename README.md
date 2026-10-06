# eudr-geojson-validator

Checks a GeoJSON file against the European Commission's **EUDR GeoJSON File
Description, version 1.5** — the format in which geolocation data for
commodity plots is submitted under Regulation (EU) 2023/1115.

[![validate](https://github.com/aolagoke-dsae/eudr-geojson-validator/actions/workflows/validate.yml/badge.svg)](https://github.com/aolagoke-dsae/eudr-geojson-validator/actions/workflows/validate.yml)

```bash
python -m src.validate_geojson data/valid_plots.geojson
python -m src.validate_geojson data/edge_cases.geojson --json
python -m src.validate_geojson my_plots.geojson --strict   # warnings fail too
```

Exit code is `1` when the file breaches the specification, `0` otherwise.

## Why it exists

The specification is a published document. Whether a file conforms to it is a
question with a definite answer, and that answer should be available before
the file is submitted anywhere rather than after it is rejected.

## Two kinds of finding

This is the whole idea, and it is the reason the tool is more than a schema
check.

| | Meaning | Example |
|---|---|---|
| **ERROR** | The file breaches the specification. A receiving system is entitled to reject it. | Polygon ring not closed; coordinate with eight decimal places |
| **WARNING** | The file satisfies every structural rule and is still probably wrong. Nothing may reject it on this basis, and a person should look. | Coordinates entered latitude-first; declared area four times the geometry's own area |

A plot whose coordinates were typed in the wrong order parses cleanly,
validates cleanly against the schema, and points at open ocean. Structure
alone cannot catch it. Comparing the position against the bounding box of the
country the record itself declares can, and when the pair reads correctly
reversed the warning says so.

## What is checked

| Code | Severity | Check |
|---|---|---|
| G000 | error | File above the 25 MB limit |
| G001 | error | Not valid JSON |
| G002 | error | Top-level type is not `FeatureCollection` |
| G003 / G004 | error | `features` missing, not an array, or empty |
| G005 | error | Element of `features` is not a `Feature` |
| G006 / G008 | error | Geometry or coordinates missing |
| G007 | error | Geometry type outside Point, MultiPoint, Polygon, MultiPolygon |
| G010 | error | Position is not a pair of numbers |
| G011 / G012 | error | Longitude outside ±180, latitude outside ±90 |
| G013 | error | More than six decimal places |
| G014 | error | Polygon declares an interior ring |
| G015 | error | Ring with fewer than four positions |
| G016 | error | Ring not closed |
| G017 | error | `properties` missing |
| G018 / G019 | error | `ProducerCountry` missing or not ISO 3166-1 alpha-2 |
| G020 | error | `ProducerName` missing |
| G022 / G023 | error | `Area` not a positive number |
| G024 | error | Point declaring more than 4 ha, which must be a polygon |
| G021 | warning | Point without `Area`; the 4 ha default will be assumed |
| G025 | warning | Declared `Area` differs from the geometry's own area by more than a factor of two |
| G026 | warning | Position outside the bounding box of the declared country |
| G027 | warning | Geometry identical to an earlier feature |

Positions are `[longitude, latitude]` in WGS84, as the specification requires.

## What this does not do

It does not assess deforestation, and it makes no statement about whether a
plot is compliant. It does not connect to TRACES or the EUDR Information
System, and it submits nothing. It does not validate the non-geographic parts
of a Due Diligence Statement. It checks one file against one published
schema, and it says where that file departs from it.

The country bounding boxes cover thirty-four commodity-producing
countries. A record declaring a country outside that list gets no G026 check,
which is a gap rather than a pass.

## Area

Polygon area is computed from the spherical excess of the ring, with an Earth
radius of 6 371 008.8 m. That is accurate to well under a percent at plot
scale and needs no projection library. The G025 threshold is deliberately
loose — a factor of two — because a declared area is an estimate and the point
is to catch a misplaced decimal, not to argue about surveying.

## Tests

```bash
pip install -r requirements.txt
python -m pytest -q        # 21 passed
```

Fifteen tests hold the specification, three hold the warning layer, and three
hold the shipped fixtures. `data/edge_cases.geojson` contains six deliberate
defects, and CI asserts that it **keeps failing**. A validator that silently
stops catching things is worse than no validator, because it is trusted.

`data/valid_plots.geojson` uses clearly-labelled test identities. It is not
derived from any real operator.

## Status

Complete for what it claims. Runtime dependencies: none beyond the Python
standard library. CI runs the suite on Python 3.10, 3.11 and 3.12.

## Licence

MIT.
