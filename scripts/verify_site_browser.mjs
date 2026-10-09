// Local browser qualification only. This script never registers or deploys a site.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";

if (process.argv[2] === "--help") {
  process.stdout.write("Usage: node scripts/verify_site_browser.mjs [BUILD_OUTPUT] [QA_EVIDENCE_AND_TOOLS]\nRequires Google Chrome and the locked website/qa dependencies installed in QA_EVIDENCE_AND_TOOLS.\n");
  process.exit(0);
}
const output = path.resolve(process.argv[2] || "artifacts/site");
const evidence = path.resolve(process.argv[3] || "artifacts/site-qa");
const require = createRequire(path.join(evidence, "package.json"));
const { chromium } = require("playwright");
const axe = require.resolve("axe-core/axe.min.js");
const manifest = JSON.parse(await fs.readFile(path.join(output, "build-manifest.json"), "utf8"));
const external = [];
const failures = [];
const reports = [];
const mobileReports = [];
const mime = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".txt": "text/plain" };
const headers = Object.fromEntries((await fs.readFile(path.join(output, "www/_headers"), "utf8")).split("\n").filter(line => line.startsWith("  ")).map(line => {
  const split = line.indexOf(":");
  return [line.slice(0, split).trim(), line.slice(split + 1).trim()];
}));
const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    let file = path.resolve(output, "." + decodeURIComponent(url.pathname));
    if (!file.startsWith(output + path.sep)) throw new Error("Out of scope");
    if ((await fs.stat(file)).isDirectory()) file = path.join(file, "index.html");
    const bytes = await fs.readFile(file);
    response.writeHead(200, { ...headers, "Content-Type": mime[path.extname(file)] || "application/octet-stream" });
    response.end(bytes);
  } catch {
    response.writeHead(404, { ...headers, "Content-Type": "text/plain" });
    response.end("Not found");
  }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ["clipboard-read", "clipboard-write"] });
  await context.route("**/*", async route => {
    if (!route.request().url().startsWith(origin + "/")) {
      external.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.on("pageerror", error => failures.push(error.message));
  page.on("response", response => { if (response.status() >= 400) failures.push(`${response.status()} ${response.url()}`); });
  const pages = Object.keys(manifest.files).filter(name => name.endsWith(".html"));
  for (const name of pages) {
    await page.goto(`${origin}/${name}`, { waitUntil: "networkidle" });
    await page.evaluate(await fs.readFile(axe, "utf8"));
    const result = await page.evaluate(async () => window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } }));
    assert.equal(result.violations.length, 0, `${name}: ${JSON.stringify(result.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })))}`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `${name}: horizontal page overflow`);
    reports.push({ page: name, violations: result.violations.length, checks: result.passes.length });
  }
  await page.goto(`${origin}/www/`, { waitUntil: "networkidle" });
  for (const image of await page.locator("img").all()) await image.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => [...document.querySelectorAll("img")].every(image => image.complete && image.naturalWidth > 0));
  assert.equal(await page.locator("img").evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0)), true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press("Tab");
  assert.equal(await page.locator(":focus").textContent(), "Skip to content");
  await page.keyboard.press("Enter");
  assert.equal(await page.locator(":focus").getAttribute("id"), "main");
  await page.evaluate(() => document.activeElement.blur());
  await page.screenshot({ path: path.join(evidence, "landing-desktop.png"), fullPage: true });
  await page.screenshot({ path: path.join(evidence, "landing-desktop-viewport.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of pages) {
    await page.goto(`${origin}/${name}`, { waitUntil: "networkidle" });
    await page.evaluate(await fs.readFile(axe, "utf8"));
    const result = await page.evaluate(async () => window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } }));
    assert.equal(result.violations.length, 0, `Mobile ${name}: ${JSON.stringify(result.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })))}`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Mobile ${name}: horizontal page overflow`);
    mobileReports.push({ page: name, violations: result.violations.length, checks: result.passes.length });
  }

  await page.goto(`${origin}/www/`, { waitUntil: "networkidle" });
  for (const image of await page.locator("img").all()) await image.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => [...document.querySelectorAll("img")].every(image => image.complete && image.naturalWidth > 0));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(await fs.readFile(axe, "utf8"));
  const mobile = await page.evaluate(async () => window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } }));
  assert.equal(mobile.violations.length, 0, JSON.stringify(mobile.violations));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: path.join(evidence, "landing-mobile.png"), fullPage: true });
  await page.goto(`${origin}/www/docs/quickstart.html`, { waitUntil: "networkidle" });
  assert.equal(await page.locator(".docs-menu").getAttribute("open"), null);
  await page.locator(".docs-menu > summary").focus();
  await page.keyboard.press("Enter");
  assert.notEqual(await page.locator(".docs-menu").getAttribute("open"), null);
  await page.getByRole("navigation", { name: "Documentation", exact: true }).getByRole("link", { name: "Resource registry", exact: true }).click();
  assert.match(await page.getByRole("heading", { level: 1 }).textContent(), /Resource reference/);
  await page.goto(`${origin}/www/docs/quickstart.html`, { waitUntil: "networkidle" });
  await page.locator(".copy-button").first().click();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), await page.locator("pre code").first().textContent());
  assert.match(await page.locator("#copy-status").textContent(), /copied/);
  await page.evaluate(await fs.readFile(axe, "utf8"));
  const mobileDocs = await page.evaluate(async () => window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } }));
  assert.equal(mobileDocs.violations.length, 0, JSON.stringify(mobileDocs.violations));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); });
  await page.screenshot({ path: path.join(evidence, "docs-mobile.png"), fullPage: true });
  await page.screenshot({ path: path.join(evidence, "docs-mobile-viewport.png") });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${origin}/www/docs/quickstart.html`, { waitUntil: "networkidle" });
  assert.notEqual(await page.locator(".docs-menu").getAttribute("open"), null);
  await page.screenshot({ path: path.join(evidence, "docs-desktop.png"), fullPage: true });
  await page.screenshot({ path: path.join(evidence, "docs-desktop-viewport.png") });
  await page.setViewportSize({ width: 320, height: 720 });
  for (const name of ["www/index.html", "docs/cli-reference.html", "docs/resource-reference.html"]) {
    await page.goto(`${origin}/${name}`, { waitUntil: "networkidle" });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `320px ${name}: horizontal page overflow`);
  }
  const denied = await context.newPage();
  await denied.addInitScript(() => { navigator.clipboard.writeText = async () => { throw new Error("Owned denied clipboard"); }; });
  await denied.goto(`${origin}/docs/quickstart.html`, { waitUntil: "networkidle" });
  await denied.locator(".copy-button").first().click();
  assert.match(await denied.locator("#copy-status").textContent(), /unavailable/);
  await denied.close();
  const noJs = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const staticPage = await noJs.newPage();
  await staticPage.goto(`${origin}/www/`);
  await staticPage.getByRole("link", { name: "Read the quickstart" }).click();
  assert.match(await staticPage.getByRole("heading", { level: 1 }).textContent(), /installation and trial/i);
  await staticPage.getByRole("navigation", { name: "Documentation", exact: true }).getByRole("link", { name: "Command-line options", exact: true }).click();
  assert.match(await staticPage.getByRole("heading", { level: 1 }).textContent(), /Command-line reference/);
  await noJs.close();
  assert.deepEqual(external, [], "External runtime requests");
  assert.deepEqual(failures, [], "Browser failures");
  const report = { browser: browser.version(), playwright: require("playwright/package.json").version, axe: require("axe-core/package.json").version, build_manifest_sha256: createHash("sha256").update(await fs.readFile(path.join(output, "build-manifest.json"))).digest("hex"), desktop_pages: reports, mobile_pages: mobileReports, mobile_keyboard_menu: true, narrow_320px_overflow: true, mobile_landing_violations: mobile.violations.length, mobile_docs_violations: mobileDocs.violations.length, keyboard_skip_link: true, clipboard_success_and_denial: true, no_javascript_navigation: true, external_requests: external, browser_failures: failures, publication_performed: false };
  await fs.writeFile(path.join(evidence, "browser-report.json"), JSON.stringify(report, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ pages: reports.length, violations: 0, evidence }) + "\n");
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
