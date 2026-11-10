// Runs the validator's own Python in the browser, in Pyodide (CPython compiled
// to WebAssembly). The page hands this worker the file's bytes; they are written
// to Pyodide's in-memory file system, checked, and deleted. Nothing is sent out.
import { loadPyodide } from "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/pyodide.mjs";

// Pyodide 314.0.7 runs Python 3.14. The validator needs only the standard library.
const PYODIDE = "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/";
// The package's modules, which the Pages workflow serves next to this file.
const MODULES = ["__init__.py", "validate.py"];

// The same steps as eudr-validate --json: the report, plus strict, cattle and passed.
const CHECK = `
import json, sys
sys.path.insert(0, "/app")
from eudr_geojson_validator import validate as V

def about():
    return json.dumps({"version": V.VALIDATOR_VERSION, "specification": V.SPECIFICATION})

def check(path, file_type, cattle, strict):
    try:
        report = V.validate_file(path, file_type, cattle=cattle)
    except Exception as exc:      # a fault in the validator, not in the file
        return json.dumps({"internal_error": f"{type(exc).__name__}: {exc}"})
    out = report.as_dict()
    out.update({"strict": strict, "cattle": cattle,
                "passed": not (report.errors or (strict and report.warnings))})
    return json.dumps(out)
`;

let ready = null;

async function start() {
  const t0 = performance.now();
  const pyodide = await loadPyodide({ indexURL: PYODIDE });
  pyodide.FS.mkdirTree("/app/eudr_geojson_validator");
  for (const name of MODULES) {
    const response = await fetch(new URL(`eudr_geojson_validator/${name}`, self.location));
    if (!response.ok) {
      throw new Error(`the validator's source could not be loaded (${name}: ${response.status})`);
    }
    pyodide.FS.writeFile(`/app/eudr_geojson_validator/${name}`, await response.text());
  }
  pyodide.runPython(CHECK);
  const about = JSON.parse(pyodide.runPython("about()"));
  self.postMessage({ type: "ready", seconds: (performance.now() - t0) / 1000, ...about });
  return pyodide;
}

self.onmessage = async ({ data }) => {
  try {
    ready = ready || start();
    const pyodide = await ready;
    const t0 = performance.now();
    pyodide.FS.writeFile("/tmp/upload.geojson", new Uint8Array(data.bytes));
    const check = pyodide.globals.get("check");
    let result;
    try {
      result = check("/tmp/upload.geojson", data.fileType, data.cattle, data.strict);
    } finally {
      check.destroy();
      pyodide.FS.unlink("/tmp/upload.geojson");
    }
    self.postMessage({ type: "report", id: data.id, seconds: (performance.now() - t0) / 1000,
                       report: JSON.parse(result) });
  } catch (error) {
    ready = null;                 // start afresh with the next file
    self.postMessage({ type: "failure", id: data.id, message: String(error?.message || error) });
  }
};
