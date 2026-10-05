/**
 * Regression check for the demo dataset picker.
 *
 * A demonstration is judged on what it offers. The repository also holds
 * files that exist to prove the tool refuses bad input: `data.csv`,
 * `dataset_variant_1.csv`, `execution_gap_test.csv`, the UNSW validation
 * corpora, the synthetic `data/generated` set, the two ServiceNow files (one
 * of which carries a duplicate-alert-id error), and the 46 MB incident log.
 * Several of those preview as an unknown role or with a blocking validation
 * error, so offering them in front of an examiner makes the product look
 * broken rather than strict.
 *
 * This check therefore verifies the curated picker. It requires the backend
 * to be running in demo mode and says so if it is not, because the point of
 * the check is exactly that mode:
 *
 *   SATSA_DATASET_MODE=demo ./dev.sh          # then run this
 *
 * The rule under test belongs to the adapter, not the browser: the picker
 * renders `/api/datasets` and filters nothing itself. So the check asserts
 * the two agree — every dataset the endpoint offers appears in the picker,
 * and the picker offers nothing else — and that the curated set is the one
 * that was verified, with none of the files that fail preview admission.
 *
 * Usage: node scripts/check-demo-datasets.mjs [interfaceUrl] [apiUrl]
 */

import puppeteer from "puppeteer-core";

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";
const API = process.argv[3] ?? "http://127.0.0.1:8000";

/**
 * The curated set, as verified against the real preview of each file: a
 * detected role (not UNKNOWN), zero validation errors, and enough canonical
 * concepts mapped to be worth analysing. Kept here deliberately: a check that
 * asked the backend what it ought to contain would agree with any backend.
 */
const CURATED = [
  "soc_asset_inventory_q3_2026.csv",
  "splunk_style_soc_alerts_q3_2026.csv",
];

/** Files the curated set excludes, each for its own preview reason. */
const EXCLUDED = [
  "data.csv",
  "dataset_variant_1.csv",
  "dataset_variant_2.csv",
  "execution_gap_test.csv",
  "incident_event_log.csv",
  "servicenow_style_secops_cases_q3_2026.csv",
  "servicenow_style_workflow_events_q3_2026.csv",
  "SAT-SA_demo_Q3_2026.csv",
  "UNSW_NB15_testing-set.csv",
  "UNSW_NB15_training-set.csv",
  "dataset_noisy.csv",
  "anomaly_controlled",
];

const notes = [];
const failures = [];
let mode = "unknown";

function check(condition, message) {
  if (condition) {
    notes.push(`  ok    ${message}`);
  } else {
    failures.push(message);
  }
}

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
page.setDefaultNavigationTimeout(60000);

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") {
    consoleErrors.push(message.text());
  }
});
page.on("pageerror", (error) => consoleErrors.push(String(error)));

try {
  const body = await (await fetch(`${API}/api/datasets`)).json();
  const offered = body.datasets.map((item) => item.path);

  mode = body.mode ?? "unstated";

  if (body.mode !== "demo") {
    failures.push(
      `the backend is in "${body.mode}" mode, so this check cannot say anything about the demo picker — start it with SATSA_DATASET_MODE=demo`,
    );
  } else {
    check(
      !body.missing || body.missing.length === 0,
      `the curated set is complete${
        body.missing ? ` (missing: ${body.missing.join(", ")})` : ""
      }`,
    );

  check(
      offered.length === CURATED.length &&
        CURATED.every((path) => offered.includes(path)),
      `the endpoint offers exactly the curated set (${offered.join(", ") || "nothing"})`,
    );

    for (const path of EXCLUDED) {
      check(
        !offered.some((item) => item === path || item.endsWith(`/${path}`)),
        `the endpoint does not offer ${path}`,
      );
    }
  }

  await page.goto(`${BASE}/assessments/new`, { waitUntil: "networkidle2" });
  await page.waitForFunction(
    () => document.body.innerText.includes("Available assessment data"),
    { timeout: 30000 },
  );

  // Scoped to the "Available assessment data" section, so the selected-files
  // list above it cannot be mistaken for the picker.
  const picker = await page.evaluate(() => {
    const heading = [...document.querySelectorAll("h2")].find((item) =>
      item.textContent.includes("Available assessment data"),
    );

    const section = heading?.closest("section");

    return [...(section?.querySelectorAll("input[type=checkbox]") ?? [])].map(
      (box) => box.getAttribute("aria-label") ?? "",
    );
  });

  const offeredInPicker = picker
    .map((label) => label.replace(/^Select /, ""))
    .filter(Boolean);

  check(
    offeredInPicker.length === body.datasets.length,
    `the picker shows one row per offered dataset (${offeredInPicker.length} shown, ${body.datasets.length} offered)`,
  );

  for (const item of body.datasets) {
    check(
      offeredInPicker.includes(item.path),
      `the picker shows ${item.path}`,
    );
  }

  for (const path of CURATED) {
    check(
      offeredInPicker.includes(path),
      `the picker shows the curated dataset ${path}`,
    );
  }

  for (const path of EXCLUDED) {
    check(
      !offeredInPicker.some((item) => item === path || item.endsWith(`/${path}`)),
      `the picker does not show ${path}`,
    );
  }

  // A curated dataset that no longer previews cleanly would put a "Review
  // required" or "Blocked" row back in front of the examiner. That is the
  // failure this whole mode exists to prevent, so it is checked rather than
  // assumed: select the curated set and read what the review step says.
  for (const path of offered) {
    const ticked = await page.evaluate((wanted) => {
      const box = document.querySelector(`input[aria-label="Select ${wanted}"]`);

      if (!box || box.checked) {
        return false;
      }

      box.click();

      return true;
    }, path);

    check(ticked, `the picker offers ${path} for selection`);
  }

  const reviewed = await page.evaluate((wanted) => {
    const button = [...document.querySelectorAll("button")].find(
      (item) => (item.textContent ?? "").includes("Continue to Review"),
    );

    if (!button || button.disabled) {
      return null;
    }

    button.click();

    return true;
  });

  check(reviewed, "the curated set can be continued to review");

  if (reviewed) {
    // The row summary only reports records once a preview has settled, so this
    // waits for the previews rather than assuming a timing.
    await page.waitForFunction(
      (expected) =>
        expected.every((path) => {
          const row = [...document.querySelectorAll("li")].find((item) =>
            item.innerText.includes(path.split("/").pop()),
          );

          return row !== undefined && /records/.test(row.innerText);
        }),
      { timeout: 240000 },
      offered,
    );

    for (const path of offered) {
      const row = await page.evaluate((wanted) => {
        const found = [...document.querySelectorAll("li")].find((item) =>
          item.innerText.includes(wanted.split("/").pop()),
        );

        return found ? found.innerText.replace(/\s+/g, " ").trim() : "";
      }, path);

      check(
        /E0 /.test(row),
        `${path} previews with no validation error (${row.slice(0, 120)})`,
      );
      check(
        !row.includes("UNKNOWN"),
        `${path} previews with a detected role, not UNKNOWN`,
      );
      check(
        !row.includes("Review required") && !row.includes("Blocked"),
        `${path} is neither review required nor blocked`,
      );
    }

    const continueRun = await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((item) =>
        (item.textContent ?? "").includes("Continue to Run"),
      );

      return button ? !button.disabled : null;
    });

    check(
      continueRun === true,
      "the curated package can continue to Run",
    );
  }

  const offenders = consoleErrors.filter(
    (text) =>
      !text.includes("favicon") && !text.includes("Download the React DevTools"),
  );

  check(
    offenders.length === 0,
    `no console errors (${offenders.length})${offenders.length ? `: ${offenders.join(" | ")}` : ""}`,
  );
} catch (error) {
  failures.push(`the check could not finish: ${error.message}`);
} finally {
  await browser.close();
}

console.log(`mode under test: ${mode}`);
console.log(notes.join("\n"));
console.log("");

if (failures.length > 0) {
  console.log(`${failures.length} check(s) failed`);
  for (const failure of failures) {
    console.log(`  - ${failure}`);
  }
  process.exit(1);
}

console.log("all checks passed");