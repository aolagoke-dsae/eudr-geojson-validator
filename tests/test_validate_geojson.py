"""Twenty-one tests.

Fifteen hold the specification. Three hold the warning layer, which is the
part that catches files that are structurally perfect and still wrong. Three
hold the shipped fixtures, including the assertion that the deliberately broken
file stays broken -- a validator that quietly stops catching things is worse
than no validator, because it is trusted.
"""
import copy
import json
from pathlib import Path

import pytest

from src.validate_geojson import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Report,
    validate_file,
    validate_obj,
)

DATA = Path(__file__).resolve().parent.parent / "data"


def base_feature():
    return {
        "type": "Feature",
        "properties": {
            "ProducerName": "Test cooperative",
            "ProducerCountry": "CI",
            "ProductionPlace": "parcel",
            "Area": 2.0,
        },
        "geometry": {"type": "Point", "coordinates": [-6.43011, 6.89502]},
    }


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def codes(obj):
    return validate_obj(obj).codes()


# ── structure ────────────────────────────────────────────────────────────

def test_a_minimal_valid_collection_passes():
    report = validate_obj(collection(base_feature()))
    assert report.ok
    assert report.errors == []


def test_top_level_must_be_a_feature_collection():
    assert "G002" in codes({"type": "Feature", "features": []})


def test_features_must_be_an_array():
    assert "G003" in codes({"type": "FeatureCollection", "features": {}})


def test_empty_feature_collection_is_rejected():
    assert "G004" in codes(collection())


def test_element_that_is_not_a_feature_is_rejected():
    assert "G005" in codes(collection({"type": "Point", "coordinates": [0, 0]}))


# ── geometry ─────────────────────────────────────────────────────────────

def test_linestring_is_not_a_permitted_geometry():
    f = base_feature()
    f["geometry"] = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    assert "G007" in codes(collection(f))


def test_longitude_beyond_180_is_rejected():
    f = base_feature()
    f["geometry"]["coordinates"] = [181.0, 6.5]
    assert "G011" in codes(collection(f))


def test_latitude_beyond_90_is_rejected():
    f = base_feature()
    f["geometry"]["coordinates"] = [6.5, 95.0]
    assert "G012" in codes(collection(f))


def test_more_than_six_decimals_is_rejected():
    f = base_feature()
    f["geometry"]["coordinates"] = [-6.4301123, 6.8950233]
    assert "G013" in codes(collection(f))


def test_six_decimals_exactly_is_accepted():
    f = base_feature()
    f["geometry"]["coordinates"] = [-6.430112, 6.895023]
    assert "G013" not in codes(collection(f))


def test_interior_ring_is_rejected():
    f = base_feature()
    f["properties"].pop("Area")
    f["geometry"] = {
        "type": "Polygon",
        "coordinates": [
            [[-6.46, 6.88], [-6.44, 6.88], [-6.44, 6.90], [-6.46, 6.90], [-6.46, 6.88]],
            [[-6.455, 6.885], [-6.45, 6.885], [-6.45, 6.89], [-6.455, 6.89], [-6.455, 6.885]],
        ],
    }
    assert "G014" in codes(collection(f))


def test_unclosed_ring_is_rejected():
    f = base_feature()
    f["properties"].pop("Area")
    f["geometry"] = {
        "type": "Polygon",
        "coordinates": [[[-6.46, 6.88], [-6.44, 6.88], [-6.44, 6.90], [-6.46, 6.90]]],
    }
    assert "G016" in codes(collection(f))


# ── properties ───────────────────────────────────────────────────────────

def test_missing_producer_country_is_rejected():
    f = base_feature()
    f["properties"].pop("ProducerCountry")
    assert "G018" in codes(collection(f))


def test_lowercase_country_code_is_rejected():
    f = base_feature()
    f["properties"]["ProducerCountry"] = "ci"
    assert "G019" in codes(collection(f))


def test_point_above_four_hectares_must_be_a_polygon():
    f = base_feature()
    f["properties"]["Area"] = 11.8
    assert "G024" in codes(collection(f))


# ── warnings, not errors ─────────────────────────────────────────────────

def test_point_without_area_warns_about_the_default():
    f = base_feature()
    f["properties"].pop("Area")
    report = validate_obj(collection(f))
    assert report.ok
    assert "G021" in {w.code for w in report.warnings}


def test_reversed_coordinates_warn_but_do_not_breach_the_spec():
    f = base_feature()
    f["geometry"]["coordinates"] = [6.89502, -6.43011]
    report = validate_obj(collection(f))
    assert report.ok, "a reversed pair is still a structurally valid position"
    assert "G026" in {w.code for w in report.warnings}


def test_declared_area_far_from_geometry_area_warns():
    f = base_feature()
    f["geometry"] = {
        "type": "Polygon",
        "coordinates": [[
            [-6.45183, 6.88412], [-6.44921, 6.88407],
            [-6.44915, 6.88183], [-6.45179, 6.88188],
            [-6.45183, 6.88412],
        ]],
    }
    f["properties"]["Area"] = 400.0
    report = validate_obj(collection(f))
    assert report.ok
    assert "G025" in {w.code for w in report.warnings}


# ── shipped fixtures ─────────────────────────────────────────────────────

def test_shipped_valid_fixture_is_conformant():
    report = validate_file(DATA / "valid_plots.geojson")
    assert report.ok, [str(f) for f in report.errors]


def test_shipped_edge_case_fixture_still_fails():
    """If this ever passes, the validator stopped working, not the file."""
    report = validate_file(DATA / "edge_cases.geojson")
    assert not report.ok
    assert {"G016", "G014", "G013", "G024", "G007"} <= report.codes()


def test_edge_case_fixture_also_raises_the_reversed_coordinate_warning():
    report = validate_file(DATA / "edge_cases.geojson")
    assert "G026" in {w.code for w in report.warnings}
