"""Thirty-three tests.

Twenty-seven hold the specification and the Regulation, each beside the text
it follows. Version 1.0 got two rules backwards: it rejected coordinates with
more than six decimals, although Regulation (EU) 2023/1115 asks for AT LEAST
six and the EU system truncates longer ones; and it required ProducerName and
ProducerCountry in every file, although the EC lists both as optional except
ProducerCountry in a Type II file. The tests below hold the corrected rules.

Three hold the warning layer, which is the part that catches files that are
structurally perfect and still wrong. Three hold the shipped fixtures,
including the assertion that the deliberately broken file stays broken -- a
validator that quietly stops catching things is worse than no validator,
because it is trusted.
"""
import json
from pathlib import Path

from src.validate_geojson import main, validate_file, validate_obj

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
        "geometry": {"type": "Point", "coordinates": [-6.430112, 6.895021]},
    }


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def codes(obj, **kw):
    return validate_obj(obj, **kw).codes()


def errors(obj, **kw):
    return {f.code for f in validate_obj(obj, **kw).errors}


def warnings(obj, **kw):
    return {f.code for f in validate_obj(obj, **kw).warnings}


def write(tmp_path, text, name="f.geojson"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


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


# ── precision: Regulation Art. 2(28), and what the EU system does ─────────

def test_more_than_six_decimals_is_a_warning_not_a_breach():
    """The EU system "will truncate coordinate points to 6 decimal places
    before storing". The extra digits are discarded, not refused."""
    f = base_feature()
    f["geometry"]["coordinates"] = [-6.4301123, 6.8950233]
    report = validate_obj(collection(f))
    assert report.ok
    assert "G013" in {w.code for w in report.warnings}


def test_six_decimals_exactly_raises_no_precision_finding():
    assert not {"G013", "G029"} & codes(collection(base_feature()))


def test_fewer_than_six_decimals_warns():
    """Regulation (EU) 2023/1115, Art. 2(28): "using at least six decimal digits"."""
    f = base_feature()
    f["geometry"]["coordinates"] = [-6.43011, 6.89502]
    report = validate_obj(collection(f))
    assert report.ok
    assert "G029" in {w.code for w in report.warnings}


def test_decimals_are_counted_as_written_in_the_file(tmp_path):
    """6.500000 has six places as written; read as a float it would show one."""
    text = json.dumps(collection(base_feature()))
    six = text.replace("-6.430112, 6.895021", "-6.500000, 6.500000")
    one = text.replace("-6.430112, 6.895021", "-6.5, 6.5")
    assert "-6.500000" in six and "-6.5, 6.5" in one
    assert "G029" not in validate_file(write(tmp_path, six, "six.geojson")).codes()
    assert "G029" in validate_file(write(tmp_path, one, "one.geojson")).codes()


def test_vertices_that_collapse_at_six_decimals_are_a_breach():
    """EC list of errors, item 7: "Duplicate coordinates due to 6 decimals
    rounding in the system"."""
    f = base_feature()
    f["properties"].pop("Area")
    f["geometry"] = {"type": "Polygon", "coordinates": [[
        [-6.4518301234, 6.8841201234], [-6.4518304321, 6.8841204321],
        [-6.449210, 6.884070], [-6.449150, 6.881830],
        [-6.4518301234, 6.8841201234],
    ]]}
    report = validate_obj(collection(f))
    assert not report.ok
    assert "G028" in {e.code for e in report.errors}


def test_distinct_vertices_at_six_decimals_do_not_collapse():
    f = base_feature()
    f["properties"].pop("Area")
    f["geometry"] = {"type": "Polygon", "coordinates": [[
        [-6.451830, 6.884120], [-6.449210, 6.884070], [-6.449150, 6.881830],
        [-6.451790, 6.881880], [-6.451830, 6.884120],
    ]]}
    assert "G028" not in codes(collection(f))


# ── properties: optional in Type I, ProducerCountry required in Type II ────

def test_type_i_accepts_a_feature_with_no_optional_properties():
    """Type I "May include any of the optional properties"."""
    f = base_feature()
    f["properties"] = {}
    report = validate_obj(collection(f))
    assert report.ok
    assert not {"G017", "G018", "G020"} & report.codes()


def test_null_properties_are_valid_geojson():
    """RFC 7946, section 3.2: "any JSON object or a JSON null value"."""
    f = base_feature()
    f["properties"] = None
    report = validate_obj(collection(f))
    assert report.ok
    assert not {"G017", "G030"} & report.codes()


def test_a_missing_properties_member_warns_but_is_accepted():
    """RFC 7946 requires the member; the EC's own single-Feature example omits it."""
    f = base_feature()
    del f["properties"]
    report = validate_obj(collection(f))
    assert report.ok
    assert "G017" in {w.code for w in report.warnings}


def test_properties_that_are_not_an_object_are_a_breach():
    f = base_feature()
    f["properties"] = "CI"
    assert "G030" in errors(collection(f))


def test_type_ii_requires_producer_country():
    """Type II "Includes the "ProducerCountry" property per "Feature"";
    Type I does not."""
    f = base_feature()
    f["properties"].pop("ProducerCountry")
    assert "G018" in errors(collection(f), file_type="II")
    assert validate_obj(collection(f), file_type="I").ok


def test_type_ii_without_producer_name_warns():
    f = base_feature()
    f["properties"].pop("ProducerName")
    report = validate_obj(collection(f), file_type="II")
    assert report.ok
    assert "G020" in {w.code for w in report.warnings}


def test_lowercase_country_code_is_rejected():
    f = base_feature()
    f["properties"]["ProducerCountry"] = "ci"
    assert "G019" in codes(collection(f))


def test_point_above_four_hectares_must_be_a_polygon():
    f = base_feature()
    f["properties"]["Area"] = 11.8
    assert "G024" in codes(collection(f))


# ── reading the file ─────────────────────────────────────────────────────

def test_nan_is_not_json(tmp_path):
    text = json.dumps(collection(base_feature())).replace('"Area": 2.0', '"Area": NaN')
    assert '"Area": NaN' in text
    assert "G001" in validate_file(write(tmp_path, text)).codes()


def test_a_file_that_is_not_utf8_is_reported_not_raised(tmp_path):
    path = tmp_path / "cp1252.geojson"
    text = json.dumps(collection(base_feature()), ensure_ascii=False)
    path.write_bytes(text.replace("Test cooperative", "Coopérative").encode("cp1252"))
    assert "G001" in validate_file(path).codes()


def test_the_cli_applies_the_type_ii_rules(tmp_path):
    f = base_feature()
    f["properties"].pop("ProducerCountry")
    path = write(tmp_path, json.dumps(collection(f)))
    assert main([str(path)]) == 0
    assert main([str(path), "--type", "II"]) == 1


# ── warnings, not errors ─────────────────────────────────────────────────

def test_point_without_area_warns_about_the_default():
    f = base_feature()
    f["properties"].pop("Area")
    report = validate_obj(collection(f))
    assert report.ok
    assert "G021" in {w.code for w in report.warnings}


def test_reversed_coordinates_warn_but_do_not_breach_the_spec():
    f = base_feature()
    f["geometry"]["coordinates"] = [6.895021, -6.430112]
    report = validate_obj(collection(f))
    assert report.ok, "a reversed pair is still a structurally valid position"
    assert "G026" in {w.code for w in report.warnings}


def test_declared_area_far_from_geometry_area_warns():
    f = base_feature()
    f["geometry"] = {
        "type": "Polygon",
        "coordinates": [[
            [-6.451830, 6.884120], [-6.449210, 6.884070],
            [-6.449150, 6.881830], [-6.451790, 6.881880],
            [-6.451830, 6.884120],
        ]],
    }
    f["properties"]["Area"] = 400.0
    report = validate_obj(collection(f))
    assert report.ok
    assert "G025" in {w.code for w in report.warnings}


# ── shipped fixtures ─────────────────────────────────────────────────────

def test_shipped_valid_fixture_is_conformant_and_meets_six_decimals():
    report = validate_file(DATA / "valid_plots.geojson")
    assert report.ok, [str(f) for f in report.errors]
    assert not {"G013", "G029"} & report.codes()
    assert validate_file(DATA / "valid_plots.geojson", file_type="II").ok


def test_shipped_edge_case_fixture_still_fails():
    """If this ever passes, the validator stopped working, not the file."""
    report = validate_file(DATA / "edge_cases.geojson")
    assert not report.ok
    assert {"G016", "G014", "G028", "G024", "G007"} <= {e.code for e in report.errors}


def test_edge_case_fixture_also_raises_the_reversed_coordinate_warning():
    report = validate_file(DATA / "edge_cases.geojson")
    assert "G026" in {w.code for w in report.warnings}
