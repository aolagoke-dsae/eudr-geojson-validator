"""Sixty-nine tests.

Most hold the specification and the Regulation, each beside the text it
follows. Version 1.0 got two rules backwards: it rejected coordinates with
more than six decimals, although Regulation (EU) 2023/1115 asks for AT LEAST
six and the EU system truncates longer ones; and it required ProducerName and
ProducerCountry in every file, although the EC lists both as optional except
ProducerCountry in a Type II file. Version 1.1 left eight error classes
unchecked and said so; the version 1.2 tests hold each of them, beside the
item of the EC's list of errors it comes from.

The rest hold the warning layer, which catches files that are structurally
perfect and still wrong; the area computation, against a closed-form area;
the command line and its exit codes; and the shipped fixtures, including the
assertion that the deliberately broken file stays broken -- a validator that
quietly stops catching things is worse than no validator, because it is
trusted.
"""
import json
import math
from pathlib import Path

import pytest

from src.validate_geojson import (
    EARTH_RADIUS_M, _measured_area_ha, main, validate_file, validate_obj,
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


def polygon(ring, area=None):
    f = base_feature()
    f["properties"].pop("Area")
    if area is not None:
        f["properties"]["Area"] = area
    f["geometry"] = {"type": "Polygon", "coordinates": [ring]}
    return f


def grid_ring(*xy):
    """A closed ring on a 0.001-degree grid near Daloa, Côte d'Ivoire."""
    pts = [[round(-6.450 + x / 1000, 6), round(6.880 + y / 1000, 6)] for x, y in xy]
    return pts + [pts[0]]


def rectangle(lon1, lon2, lat1, lat2):
    return [[lon1, lat1], [lon2, lat1], [lon2, lat2], [lon1, lat2], [lon1, lat1]]


SQUARE = grid_ring((0, 0), (3, 0), (3, 3), (0, 3))


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
    found = [w.message for w in report.warnings if w.code == "G026"]
    assert found and "latitude-first" in found[0]


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
    assert {"G016", "G014", "G028", "G024", "G007", "G031", "G019"} <= {
        e.code for e in report.errors}


def test_edge_case_fixture_also_raises_the_reversed_coordinate_warning():
    report = validate_file(DATA / "edge_cases.geojson")
    assert "G026" in {w.code for w in report.warnings}


# ── v1.2: rings, the EC's list of errors items 1, 2 and 6 ─────────────────

def test_a_figure_eight_ring_is_a_breach():
    """Item 1: "crossing coordinate lines", such as a figure eight."""
    assert "G031" in errors(collection(polygon(grid_ring((0, 0), (2, 2), (2, 0), (0, 2)))))


def test_a_ring_that_touches_itself_is_a_breach():
    """Two triangles joined at one position: the ring passes it twice."""
    ring = grid_ring((0, 0), (4, 0), (2, 2), (4, 4), (0, 4), (2, 2))
    assert "G031" in errors(collection(polygon(ring)))


def test_sides_that_fold_back_are_a_breach():
    """Item 2: overlapping sides, including inward-folding ones."""
    ring = grid_ring((0, 0), (4, 0), (4, 4), (2, 4), (2, 6), (2, 5), (0, 4))
    found = [e.message for e in validate_obj(collection(polygon(ring))).errors
             if e.code == "G031"]
    assert found and "folds back" in found[0]


def test_positions_on_one_line_enclose_no_area():
    """Item 6: "coordinates that represent straight lines"."""
    assert "G032" in errors(collection(polygon(grid_ring((0, 0), (1, 0), (3, 0)))))


NECK = """{{"type": "FeatureCollection", "features": [{{"type": "Feature",
"properties": {{}}, "geometry": {{"type": "Polygon", "coordinates": [[
[-6.449909, 6.880049], [-6.446909, 6.881049], [-6.446909, 6.884049],
[-6.448409, {lat}], [-6.449909, 6.884049], [-6.449909, 6.880049]]]}}}}]}}"""


def test_a_position_exactly_on_a_side_touches_it(tmp_path):
    """(-6.448409, 6.880549) is the midpoint of the first side as written. In
    binary floating point it lies just above that side, on the inside, so a
    test in floats alone finds no touch; only the exact test sees it."""
    path = write(tmp_path, NECK.format(lat="6.880549"))
    assert "G031" in validate_file(path).codes()


def test_a_position_a_millionth_of_a_degree_off_the_side_misses_it(tmp_path):
    path = write(tmp_path, NECK.format(lat="6.880550"))
    assert not {"G031", "G032"} & validate_file(path).codes()


def test_concave_and_straight_sided_rings_are_not_crossings():
    l_shape = grid_ring((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4))
    extra_vertex_on_a_side = grid_ring((0, 0), (2, 0), (4, 0), (4, 4), (0, 4))
    for ring in (l_shape, extra_vertex_on_a_side, SQUARE):
        assert not {"G031", "G032"} & codes(collection(polygon(ring)))


def test_every_member_of_a_multipolygon_is_checked():
    f = base_feature()
    f["properties"].pop("Area")
    bow_tie = grid_ring((10, 0), (12, 2), (12, 0), (10, 2))
    f["geometry"] = {"type": "MultiPolygon", "coordinates": [[SQUARE], [bow_tie]]}
    found = [e for e in validate_obj(collection(f)).errors if e.code == "G031"]
    assert found and found[0].where.endswith("polygon[1]")


# ── v1.2: properties, items 9, 12 and 14 ─────────────────────────────────

def test_a_country_code_must_be_assigned_not_just_well_formed():
    """Item 12: "an invalid producer country ISO2 code". v1.1 checked the
    form, so XX passed, and its regex let a trailing newline through."""
    for code in ("XX", "AA", "CI\n"):
        f = base_feature()
        f["properties"]["ProducerCountry"] = code
        assert "G019" in errors(collection(f)), repr(code)


def test_the_eus_own_codes_for_greece_and_the_uk_point_to_iso():
    for eu, iso in (("EL", "GR"), ("UK", "GB")):
        f = base_feature()
        f["properties"]["ProducerCountry"] = eu
        found = [e.message for e in validate_obj(collection(f)).errors if e.code == "G019"]
        assert found and f"writes {iso}" in found[0]


def test_kosovo_is_a_warning_not_a_breach():
    """XK is user-assigned, outside ISO 3166-1, and the code the EU uses."""
    f = base_feature()
    f["properties"]["ProducerCountry"] = "XK"
    report = validate_obj(collection(f))
    assert report.ok
    assert "G034" in {w.code for w in report.warnings}


def test_property_names_are_case_sensitive():
    """Item 9: "productionplace" is an invalid property name."""
    f = base_feature()
    f["properties"]["productionplace"] = f["properties"].pop("ProductionPlace")
    assert "G033" in errors(collection(f))


def test_a_wrongly_cased_country_is_also_a_missing_one_in_type_ii():
    f = base_feature()
    f["properties"]["producerCountry"] = f["properties"].pop("ProducerCountry")
    assert {"G033", "G018"} <= errors(collection(f), file_type="II")


def test_other_property_names_are_ignored():
    """The EC: other syntactically valid properties are ignored."""
    f = base_feature()
    f["properties"]["FarmId"] = "x-17"
    report = validate_obj(collection(f))
    assert report.ok and "G033" not in report.codes()


def test_a_polygons_area_must_be_positive():
    """v1.1 checked a polygon's Area for being a number only."""
    for bad in (-5, 0):
        assert "G023" in errors(collection(polygon(SQUARE, area=bad))), bad


def test_a_quoted_area_is_not_a_number():
    """Item 14: "Area": "3" yields an area of 0."""
    found = [e.message for e in validate_obj(collection(polygon(SQUARE, area="3"))).errors
             if e.code == "G022"]
    assert found and "item 14" in found[0]


def test_a_nan_area_passed_from_python_is_not_a_number():
    f = base_feature()
    f["properties"]["Area"] = float("nan")
    assert "G022" in errors(collection(f))


# ── v1.2: structure that used to crash or pass ───────────────────────────

def test_coordinates_at_the_wrong_depth_are_a_finding_not_a_crash():
    """v1.1 stopped with a TypeError on a Polygon given [5]."""
    cases = (("Polygon", [5]), ("Polygon", [[[[-6.43, 6.89]]]]),
             ("MultiPolygon", [[[-6.43, 6.89]]]), ("MultiPoint", [-6.43, 6.89]))
    for gtype, coords in cases:
        f = base_feature()
        f["properties"].pop("Area")
        f["geometry"] = {"type": gtype, "coordinates": coords}
        assert "G009" in errors(collection(f)), (gtype, coords)


def test_a_point_written_as_an_array_of_positions_is_flagged():
    """Item 14: point coordinates should be a single array."""
    f = base_feature()
    f["geometry"]["coordinates"] = [[-6.430112, 6.895021]]
    found = [e.message for e in validate_obj(collection(f)).errors if e.code == "G009"]
    assert found and "item 14" in found[0]


def test_an_empty_multi_geometry_gives_no_location():
    for gtype in ("MultiPoint", "MultiPolygon"):
        f = base_feature()
        f["properties"].pop("Area")
        f["geometry"] = {"type": gtype, "coordinates": []}
        assert "G008" in errors(collection(f)), gtype


def test_every_member_of_a_multipoint_is_checked():
    f = base_feature()
    f["geometry"] = {"type": "MultiPoint",
                     "coordinates": [[-6.430112, 6.895021], [181.000000, 6.500000]]}
    assert "G011" in errors(collection(f))


# ── v1.2: the four-hectare rule is the Regulation's, and spares cattle ────

def test_four_hectares_exactly_may_be_a_point():
    """Art. 2(28): polygons for plots of MORE than four hectares."""
    f = base_feature()
    f["properties"]["Area"] = 4.0
    assert "G024" not in codes(collection(f))
    f["properties"]["Area"] = 4.000001
    assert "G024" in errors(collection(f))


def test_g024_cites_the_regulation_and_spares_cattle():
    f = base_feature()
    f["properties"]["Area"] = 30.0
    found = [e.message for e in validate_obj(collection(f)).errors if e.code == "G024"]
    assert found and "Art. 2(28)" in found[0] and "--cattle" in found[0]
    assert validate_obj(collection(f), cattle=True).ok


def test_g024_applies_to_a_point_not_to_a_multipoint():
    """The EC defines Area for a Point; for a MultiPoint it says nothing."""
    f = base_feature()
    f["properties"]["Area"] = 30.0
    f["geometry"] = {"type": "MultiPoint",
                     "coordinates": [[-6.430112, 6.895021], [-6.431112, 6.896021]]}
    assert "G024" not in codes(collection(f))


# ── area ─────────────────────────────────────────────────────────────────

RECT = rectangle(-6.452, -6.449, 6.881, 6.884)


def test_the_area_of_a_known_rectangle():
    """A rectangle between two meridians and two parallels has a closed-form
    area on the sphere, R² · Δλ · (sin φ2 − sin φ1). v1.0's area had no
    effective test: multiplying it by ten passed the suite."""
    want = (EARTH_RADIUS_M ** 2 * math.radians(0.003)
            * (math.sin(math.radians(6.884)) - math.sin(math.radians(6.881)))) / 10_000
    got = _measured_area_ha({"type": "Polygon", "coordinates": [RECT]})
    assert got == pytest.approx(want, rel=1e-9)
    assert 11.0 < got < 11.2


def test_g025_fires_beyond_a_factor_of_two_and_not_within_it():
    measured = _measured_area_ha({"type": "Polygon", "coordinates": [RECT]})

    def g025(area):
        return "G025" in codes(collection(polygon(RECT, area=area)))

    assert not g025(measured * 1.99) and g025(measured * 2.01)
    assert not g025(measured / 1.99) and g025(measured / 2.01)


def test_a_multipolygons_area_is_the_sum_of_its_members():
    small = rectangle(-6.452, -6.449, 6.881, 6.884)
    large = rectangle(-6.440, -6.431, 6.881, 6.884)    # three times as wide
    geometry = {"type": "MultiPolygon", "coordinates": [[small], [large]]}
    total = _measured_area_ha(geometry)
    assert total == pytest.approx(4 * _measured_area_ha({"type": "Polygon",
                                                         "coordinates": [small]}), rel=1e-3)
    f = base_feature()
    f["properties"]["Area"] = total
    f["geometry"] = geometry
    assert "G025" not in codes(collection(f))


# ── command line ─────────────────────────────────────────────────────────

def test_strict_mode_says_why_it_rejects_a_conformant_file(capsys):
    """v1.1 printed "conformant" and exited 1."""
    assert main([str(DATA / "valid_plots.geojson"), "--strict"]) == 1
    assert "conformant, but rejected under --strict: 1 warning(s)" in capsys.readouterr().out
    assert main([str(DATA / "valid_plots.geojson")]) == 0
    assert capsys.readouterr().out.rstrip().endswith("\nconformant")


def test_exit_codes(tmp_path, capsys):
    assert main([str(DATA / "valid_plots.geojson")]) == 0
    assert main([str(DATA / "edge_cases.geojson")]) == 1
    assert main([str(tmp_path / "missing.geojson")]) == 2
    assert "cannot read" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main(["--type", "III", "x.geojson"])
    assert exc.value.code == 2


def test_json_output_states_the_verdict(capsys):
    main([str(DATA / "valid_plots.geojson"), "--json", "--strict"])
    out = json.loads(capsys.readouterr().out)
    assert out["conformant"] is True and out["passed"] is False
    assert out["strict"] is True and out["validator_version"] == "1.2"


def test_the_cli_applies_the_cattle_exemption(tmp_path):
    f = base_feature()
    f["properties"]["Area"] = 30.0
    path = write(tmp_path, json.dumps(collection(f)))
    assert main([str(path)]) == 1
    assert main([str(path), "--cattle"]) == 0


# ── rules v1.1 already had, without a test that could fail ────────────────

def test_a_ring_needs_four_positions():
    """A closed ring repeats its first position, so a triangle has four."""
    assert "G015" in errors(collection(polygon(grid_ring((0, 0), (2, 0)))))


def test_a_position_must_hold_numbers():
    f = base_feature()
    f["geometry"]["coordinates"] = ["-6.430112", "6.895021"]
    assert "G010" in errors(collection(f))


def test_a_repeated_geometry_warns():
    report = validate_obj(collection(base_feature(), base_feature()))
    assert report.ok
    assert [w.where for w in report.warnings if w.code == "G027"] == ["features[1]"]


def test_a_file_above_the_size_limit_is_refused(tmp_path, monkeypatch):
    """A smaller limit stands in for the 25 MB one here."""
    import src.validate_geojson as V
    monkeypatch.setattr(V, "MAX_FILE_BYTES", 100)
    path = write(tmp_path, json.dumps(collection(base_feature())))
    assert path.stat().st_size > 100
    assert V.validate_file(path).codes() == {"G000"}


def test_the_size_limit_is_25_megabytes():
    import src.validate_geojson as V
    assert V.MAX_FILE_BYTES == 25 * 1024 * 1024

