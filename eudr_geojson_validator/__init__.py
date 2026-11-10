"""Checks EUDR geolocation files against the European Commission's GeoJSON
File Description, with errors and warnings kept apart. The command is
eudr-validate; validate_file and validate_obj are the same checks from Python.
"""
from .validate import (SPECIFICATION, VALIDATOR_VERSION, Finding, Report, main,
                       validate_file, validate_obj)

__version__ = VALIDATOR_VERSION
__all__ = ["Finding", "Report", "SPECIFICATION", "main", "validate_file",
           "validate_obj", "__version__"]
