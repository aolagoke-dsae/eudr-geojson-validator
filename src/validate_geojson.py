"""The command of versions 1.0 to 1.2, `python -m src.validate_geojson`, kept
working from a checkout. The validator is the package eudr_geojson_validator;
installed, its command is eudr-validate.
"""
from eudr_geojson_validator.validate import *  # noqa: F401,F403
from eudr_geojson_validator.validate import main

if __name__ == "__main__":
    raise SystemExit(main())
