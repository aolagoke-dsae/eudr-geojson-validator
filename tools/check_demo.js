// Checks the browser demo against the command line, in headless Chromium.
//
//     npm install --no-save playwright pyodide@314.0.7 && npx playwright install chromium
//     node tools/check_demo.js
//
// Assembles the site as .github/workflows/pages.yml does, serves it on
// 127.0.0.1, and answers the page's requests for Pyodide from node_modules
// instead of jsDelivr; any other request outside the site is recorded and
// refused. Then: Python must load as the page opens, before any file is
// chosen; the file with seven breaches must give the command line's findings,
// word for word, and its downloaded report must equal `eudr-validate --json`;
// the conformant file must pass, and fail under --strict; --cattle must drop
// G024; nesting past 100 levels must be G001 and not a crash; and no request
// may carry a body or leave the site and jsDelivr. Exits 0 when every check
// passes. PYTHON names the interpreter (default python3, or python on
// Windows).
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const PYODIDE = path.dirname(require.resolve("pyodide/package.json"));
const CDN = "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/";
const BASE = "/eudr-geojson-validator/";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript",
  ".py": "text/x-python; charset=utf-8", ".geojson": "application/geo+json", ".json": "application/json",
  ".wasm": "application/wasm", ".zip": "application/zip" };

let failures = 0;
function expect(name, ok, detail = "") {
  if (!ok) failures += 1;
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail && !ok ? `: ${detail}` : ""}`);
}

function assemble() {
  const site = fs.mkdtempSync(path.join(os.tmpdir(), "eudr-demo-"));
  const copy = (from, to) => {
    fs.mkdirSync(path.dirname(path.join(site, to)), { recursive: true });
    fs.copyFileSync(path.join(ROOT, from), path.join(site, to));
  };
  copy("web/index.html", "index.html");
  copy("web/worker.js", "worker.js");
  for (const name of ["__init__.py", "validate.py"]) copy(`eudr_geojson_validator/${name}`, `eudr_geojson_validator/${name}`);
  for (const name of ["valid_plots.geojson", "edge_cases.geojson"]) copy(`data/${name}`, `data/${name}`);
  return site;
}

function cliReport(file) {
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  try {
    return JSON.parse(execFileSync(python, ["-m", "eudr_geojson_validator", file, "--json"], { cwd: ROOT }));
  } catch (error) {                     // exit code 1: the file breaches the specification
    if (error.status === 1) return JSON.parse(error.stdout);
    throw error;
  }
}

(async () => {
  const site = assemble();
  const cli = cliReport("data/edge_cases.geojson");
  const served = [], refused = [], errors = [];
  const server = http.createServer((req, res) => {
    let body = 0;
    req.on("data", (chunk) => { body += chunk.length; });
    req.on("end", () => {
      served.push({ method: req.method, body });
      const url = decodeURIComponent(req.url.split("?")[0]);
      const file = path.join(site, url.startsWith(BASE) ? url.slice(BASE.length) || "index.html" : "\0");
      if (!file.startsWith(site) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(404);
        res.end();
        return;
      }
      res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
      res.end(fs.readFileSync(file));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;

  const browser = await chromium.launch();
  const context = await browser.newContext({ acceptDownloads: true });
  await context.route((url) => !url.href.startsWith(origin), (route) => {
    refused.push(route.request().url());
    route.abort();
  });
  await context.route(`${CDN}**`, (route) => {     // registered last, so tried first
    const name = new URL(route.request().url()).pathname.split("/").pop();
    if (route.request().method() !== "GET") refused.push(route.request().url());
    route.fulfill({ status: 200, path: path.join(PYODIDE, name),
      headers: { "content-type": TYPES[path.extname(name)] || "application/octet-stream",
                 "access-control-allow-origin": "*" } });
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(origin + BASE);

  // The status line is set to a mark; the page replaces it with "Checking..." and then the outcome.
  const act = async (action, timeout = 120000) => {
    await page.evaluate(() => { document.getElementById("status").textContent = "…"; });
    await action();
    await page.waitForFunction(() => /Checked |could not|limit/.test(document.getElementById("status").textContent),
      null, { timeout });
  };
  const verdict = async () => (await page.locator("#verdict").innerText()).replace(/\s+/g, " ").trim();
  const rows = () => page.$$eval("#findings tr", (trs) => trs.map((tr) => [...tr.children].map((td) => td.innerText.trim())));
  const upload = (name, text) => act(() => page.setInputFiles("#file",
    { name, mimeType: "application/geo+json", buffer: Buffer.from(text) }));

  await page.waitForFunction(() => document.getElementById("status").textContent.startsWith("Python is ready"),
    null, { timeout: 180000 });
  expect("Python loads as the page opens, before any file is chosen", true);
  await act(() => page.click("text=a file with seven breaches"));
  let found = await rows();
  expect("seven breaches: 7 errors, 2 warnings", (await verdict()).startsWith("✕ Not conformant 7 errors, 2 warnings"));
  expect("the command line's findings, in its order", JSON.stringify(found.map((r) => [r[1], r[2], r[3]]))
    === JSON.stringify(cli.findings.map((f) => [f.code, f.where, f.message])));
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("#download")]);
  const saved = path.join(site, "report.json");
  await download.saveAs(saved);
  expect("the downloaded report equals eudr-validate --json",
    JSON.stringify(JSON.parse(fs.readFileSync(saved, "utf8"))) === JSON.stringify(cli));
  expect("the map's first view leaves out the latitude-first plot, and says so",
    /^features\[7\] lies outside this view/.test(await page.locator("#map-note").innerText()));

  await act(() => page.check("#cattle"));
  found = await rows();
  expect("--cattle drops G024", (await verdict()).includes("6 errors") && !found.some((r) => r[1] === "G024"));
  await act(() => page.uncheck("#cattle"));

  await act(() => page.click("text=a conformant file"));
  expect("the conformant file passes", (await verdict()).startsWith("✓ Conformant"));
  await act(() => page.check("#strict"));
  expect("and fails under --strict", (await verdict()).startsWith("! Conformant, but rejected under strict"));
  await act(() => page.uncheck("#strict"));

  const nested = (k) => '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, '
    + '"geometry": {"type": "Polygon", "coordinates": ' + "[".repeat(k) + "1.5, 2.5" + "]".repeat(k) + "}}]}";
  for (const [name, text, code] of [["100 levels, the limit", nested(96), "G009"], ["101 levels", nested(97), "G001"],
    ["1,500 levels of objects", '{"a":'.repeat(1500) + "1" + "}".repeat(1500), "G001"],
    ["100,000 levels", "[".repeat(100000) + "]".repeat(100000), "G001"]]) {
    await upload("nested.geojson", text);
    const status = await page.locator("#status").innerText();
    found = await rows();
    expect(`nesting ${name}: ${code}`, status.startsWith("Checked") && found.length === 1 && found[0][1] === code,
      `${status} ${found.map((r) => r[1]).join(", ")}`);
  }
  await upload("text.geojson", "not JSON");
  expect("text that is not JSON: G001", (await page.locator("#status").innerText()).startsWith("Checked")
    && (await rows()).map((r) => r[1]).join() === "G001");

  expect("every request a GET, none with a body", served.every((s) => s.method === "GET" && s.body === 0));
  expect("nothing asked for beyond the site and jsDelivr", refused.length === 0, refused.join(", "));
  expect("no error in the page", errors.length === 0, errors.join(" | "));
  await browser.close();
  server.close();
  fs.rmSync(site, { recursive: true, force: true });
  console.log(failures ? `\n${failures} check(s) failed` : "\nevery check passed");
  process.exit(failures ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(2); });
