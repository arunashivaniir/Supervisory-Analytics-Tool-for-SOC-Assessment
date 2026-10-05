"""Headless-Chromium checks for a packaged SAT-SA executable.

Imported by packaging/verify.py. Every URL the page requests is recorded;
the offline requirement passes only if all of them stay on 127.0.0.1.
"""

from __future__ import annotations

import os


def run_browser_checks(base: str):
    import subprocess

    script = (
        r"""
import puppeteer from "puppeteer-core";
const BASE = "__SATSA_BASE__";
const out = [];
const check = (c, m) => out.push(JSON.stringify({ok: !!c, message: m}));
"""
        + r"""
const browser = await puppeteer.launch({
  executablePath: process.env.CHROMIUM || "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
page.setDefaultNavigationTimeout(60000);
const requested = new Set();
page.on("request", (r) => requested.add(new URL(r.url()).host));
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const text = () => page.evaluate(() => document.body.textContent);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

await page.goto(BASE + "/assessments/new", { waitUntil: "domcontentloaded" });
await page.waitForFunction(
  () => document.body.textContent.includes("Submission package"),
  { timeout: 60000 },
);
check(true, "/assessments/new renders");
// The frozen backend unpacks and warms up on first use; wait for the
// listing the UI itself depends on rather than a fixed delay.
await page.waitForFunction(
  async () => {
    try {
      const res = await fetch(BASE + "/api/datasets");
      const body = await res.json();
      return (body.datasets || []).length > 0;
    } catch {
      return false;
    }
  },
  { timeout: 120000, polling: 1000 },
);
await page.waitForFunction(
  () => document.body.textContent.includes("dataset_noisy.csv"),
  { timeout: 60000 },
);
await page.evaluate(() => {
  document.querySelector('input[aria-label="Select dataset_noisy.csv"]')?.click();
});
await sleep(400);
await page.evaluate(() => {
  [...document.querySelectorAll("button")]
    .find((b) => b.textContent.trim() === "Continue")
    ?.click();
});
await page.waitForFunction(
  () => document.body.textContent.includes("Dataset roles"),
  { timeout: 15000 },
);
await page.waitForFunction(
  () => !document.body.textContent.includes("Previewing…"),
  { timeout: 90000 },
);
await sleep(400);
let body = await text();
check(/ALERTS|CASES|WORKFLOW_EVENTS|ASSETS|UNKNOWN/.test(body), "role preview renders");
check(/\d+ of \d+ mapped/.test(body), "mapping summary renders");
await page.evaluate(() => {
  [...document.querySelectorAll("li button")]
    .find((b) => (b.getAttribute("aria-label") || "").startsWith("Review "))
    ?.click();
});
await sleep(800);
body = await text();
check(body.includes("Canonical mapping"), "canonical mapping renders");
check(body.includes("Validation"), "validation renders");
check(body.includes("Pipeline role"), "role detection renders");
const offsite = [...requested].filter((h) => h !== new URL(BASE).host);
check(offsite.length === 0, "all requests stay on localhost (" + [...requested].join(",") + ")");
check(errors.length === 0, "no page errors (" + errors.length + ")");
console.log(out.map((line) => {
  const { ok, message } = JSON.parse(line);
  return (ok ? "  ok   " : "  FAIL ") + message;
}).join("\n"));
await browser.close();
"""
    )
    script = script.replace("__SATSA_BASE__", base)
    env = dict(os.environ, SATSA_BASE=base)
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=helper,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    results = []

    for line in (proc.stdout or "").splitlines():
        text = line.strip()

        if text.startswith("  ok   ") or text.startswith("  FAIL "):
            results.append((text.startswith("  ok   "), text[7:]))

    if proc.returncode != 0 and not results:
        results.append((False, f"browser helper failed: {(proc.stderr or '')[:300]}"))

    return results
