/**
 * Regression checks for package-level gating in New Assessment.
 *
 * A package may hold several datasets, and their detected roles do not all
 * come out the same. The rule being protected here: a dataset the examiner
 * has not reviewed a role for is review required and is *skipped* by the run,
 * rather than holding back every other dataset in the package. Detection
 * itself is not the subject — `data.csv` is genuinely UNKNOWN — so the checks
 * drive the wizard with datasets whose roles the service already detects, plus
 * that one unknown file, and assert what the package gate and the Run step
 * then say.
 *
 * Six behaviours:
 *
 *   1. valid + UNKNOWN  -> Continue enabled, unknown shown as skipped;
 *   2. UNKNOWN only     -> Continue disabled, role confirmation required;
 *   3. valid + a dataset carrying a validation error -> Continue disabled;
 *   4. valid + warnings -> Continue enabled (warnings are not blockers);
 *   5. UNKNOWN + reviewer role -> the dataset becomes runnable;
 *   6. two valid datasets -> both runnable.
 *
 * and finally that a run started from a mixed package analyses the runnable
 * dataset, not the skipped one.
 *
 * Driven through Chromium against the running interface and the running
 * adapter, because the thing being protected is a sequence of state changes
 * across requests: a preview settling, a reviewer choosing a role, and a
 * package gate recomputing. Expectations are read from the previews the
 * service actually returns, so a dataset whose warnings or errors change is
 * still described correctly by the check.
 *
 * Usage: node scripts/check-role-gating.mjs [interfaceUrl] [apiUrl]
 */

import puppeteer from "puppeteer-core";

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";
const API = process.argv[3] ?? "http://127.0.0.1:8000";

// Detected ASSETS, no validation error (carries a warning).
const VALID_A = "soc_asset_inventory_q3_2026.csv";
// Detected ASSETS, no validation error (carries warnings). Larger, so its
// preview takes a few seconds — the checks below wait for real settling.
const VALID_B = "splunk_style_soc_alerts_q3_2026.csv";
// No role anchor: genuinely UNKNOWN, so a reviewer's choice is the only way in.
const UNKNOWN = "data.csv";
// Detected ALERTS but carrying a blocking validation error.
const INVALID = "servicenow_style_secops_cases_q3_2026.csv";

const PREVIEW_TIMEOUT = 240000;
const RUN_TIMEOUT = 300000;

const notes = [];
const failures = [];
const skips = [];
const consoleErrors = [];

function check(condition, message) {
  if (condition) {
    notes.push(`  ok    ${message}`);
  } else {
    failures.push(message);
  }
}

function skip(message) {
  skips.push(`  skip  ${message}`);
}

function filename(path) {
  return path.split("/").pop() ?? path;
}

async function previewsFor(paths) {
  const response = await fetch(`${API}/api/previews`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ datasets: paths }),
  });

  if (!response.ok) {
    throw new Error(`/api/previews answered ${response.status}`);
  }

  const body = await response.json();

  return new Map(body.previews.map((preview) => [preview.dataset, preview]));
}

/** The button whose label contains `label`, and whether it is disabled. */
function buttonState(page, label) {
  return page.evaluate((wanted) => {
    const button = [...document.querySelectorAll("button")].find((item) =>
      (item.textContent ?? "").includes(wanted),
    );

    return button
      ? { found: true, disabled: button.disabled }
      : { found: false, disabled: null };
  }, label);
}

async function clickButton(page, label) {
  const clicked = await page.evaluate((wanted) => {
    const button = [...document.querySelectorAll("button")].find(
      (item) => (item.textContent ?? "").includes(wanted) && !item.disabled,
    );

    if (!button) {
      return false;
    }

    button.click();

    return true;
  }, label);

  if (!clicked) {
    throw new Error(`no enabled "${label}" button to click`);
  }
}

function pageText(page) {
  return page.evaluate(() => document.body.innerText);
}

/** Page text with wrapping collapsed, so a note reads as one string. */
async function flatText(page) {
  return (await pageText(page)).replace(/\s+/g, " ");
}

/**
 * Wait until the Run step is on screen and every named dataset has a row of
 * its own, so a row is never read or clicked while the step is still
 * rendering.
 */
function waitForRunStep(page, paths) {
  return page.waitForFunction(
    (wanted) => {
      const rows = [...document.querySelectorAll("li")];

      return wanted.every((path) => {
        const row = rows.find((item) =>
          item.innerText.includes(path.split("/").pop()),
        );

        return (
          row !== undefined &&
          /records/.test(row.innerText) &&
          [...row.querySelectorAll("button")].some(
            (button) => button.textContent.trim() === "Run",
          )
        );
      });
    },
    { timeout: 30000 },
    paths,
  );
}

/** What the Run step currently shows for the selected datasets. */
function runStepDiagnostics(page) {
  return page.evaluate(() => {
    const rows = [...document.querySelectorAll("li")]
      .map((item) => item.innerText.replace(/\s+/g, " ").trim())
      .filter((text) => /records/.test(text));

    const flat = document.body.innerText.replace(/\s+/g, " ");

    return `${JSON.stringify(rows)}${
      /already in flight/.test(flat) ? " [a run was in flight]" : ""
    }`;
  });
}

/**
 * Whether one dataset's Run button reaches enabled, read after it has settled.
 * Returns the reason it did not, so a failure says what was on screen.
 */
async function runEnabled(page, path) {
  try {
    await page.waitForFunction(
      (wanted) => {
        const row = [...document.querySelectorAll("li")].find((item) =>
          item.innerText.includes(wanted.split("/").pop()),
        );

        if (!row) {
          return false;
        }

        const run = [...row.querySelectorAll("button")].find(
          (button) => button.textContent.trim() === "Run",
        );

        return run !== undefined && !run.disabled;
      },
      { timeout: 30000 },
      path,
    );

    return true;
  } catch {
    return false;
  }
}

/** The Run step's row for one dataset, as displayed. */
function runRow(page, path) {
  return page.evaluate((wanted) => {
    const row = [...document.querySelectorAll("li")].find((item) =>
      item.innerText.includes(wanted),
    );

    if (!row) {
      return null;
    }

    const run = [...row.querySelectorAll("button")].find(
      (button) => button.textContent.trim() === "Run",
    );

    return {
      text: row.innerText,
      runDisabled: run ? run.disabled : null,
    };
  }, filename(path));
}

/** Fresh wizard at Data, with the given datasets ticked. */
async function startPackage(page, paths) {
  await page.goto(`${BASE}/assessments/new`, { waitUntil: "networkidle2" });
  await page.waitForFunction(
    () => document.body.innerText.includes("Available assessment data"),
    { timeout: 30000 },
  );

  for (const path of paths) {
    const ticked = await page.evaluate((wanted) => {
      const box = document.querySelector(`input[aria-label="Select ${wanted}"]`);

      if (!box || box.checked) {
        return false;
      }

      box.click();

      return true;
    }, path);

    if (!ticked) {
      throw new Error(`${path} is not offered by the available listing`);
    }
  }

  await clickButton(page, "Continue to Review");

  // Wait for every selected dataset's own preview to settle: the row summary
  // only reports records once a preview has been stored for it.
  await page.waitForFunction(
    (wanted) => {
      const names = wanted.map((item) => item.split("/").pop());

      return names.every((name) => {
        const row = [...document.querySelectorAll("li")].find((item) =>
          item.innerText.includes(name),
        );

        return row !== undefined && /records/.test(row.innerText);
      });
    },
    { timeout: PREVIEW_TIMEOUT },
    paths,
  );
}

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
page.setDefaultNavigationTimeout(60000);

page.on("console", (message) => {
  if (message.type() === "error") {
    consoleErrors.push(message.text());
  }
});
page.on("pageerror", (error) => consoleErrors.push(String(error)));

try {
  // -----------------------------------------------------------------------
  // Read what the service actually says about each dataset, so the expected
  // outcome of each scenario is derived rather than assumed.
  // -----------------------------------------------------------------------
  const previews = await previewsFor([VALID_A, VALID_B, UNKNOWN, INVALID]);
  const warningOnly = [...previews.values()].filter(
    (preview) =>
      preview.detected_role.role !== "UNKNOWN" &&
      (preview.validation.error_count ?? 0) === 0 &&
      (preview.validation.warning_count ?? 0) > 0,
  );

  check(
    previews.get(UNKNOWN)?.detected_role.role === "UNKNOWN",
    `${UNKNOWN} is UNKNOWN in the service, so it is the review-required case`,
  );
  check(
    previews.get(INVALID)?.validation.error_count > 0,
    `${INVALID} carries a blocking validation error`,
  );
  check(
    previews.get(VALID_A)?.validation.error_count === 0 &&
      previews.get(VALID_A)?.detected_role.role !== "UNKNOWN",
    `${VALID_A} is detected and free of validation errors`,
  );

  if (warningOnly.length === 0) {
    skip("no detected dataset with warnings but no errors; the warning case is not covered");
  }

  // -----------------------------------------------------------------------
  // 1. A valid dataset and an unreviewed one: the package continues, and the
  //    unknown dataset is reported as skipped rather than silently dropped.
  // -----------------------------------------------------------------------
  await startPackage(page, [VALID_A, UNKNOWN]);

  const continueMixed = await buttonState(page, "Continue to Run");
  check(
    continueMixed.found && !continueMixed.disabled,
    "valid + UNKNOWN: Continue to Run is enabled",
  );

  const reviewText = await flatText(page);
  check(
    reviewText.includes(
      `1 dataset is review required and will be skipped rather than run: ${UNKNOWN}`,
    ),
    "Review names the unreviewed dataset and says it will be skipped",
  );

  await clickButton(page, "Continue to Run");
  await waitForRunStep(page, [VALID_A, UNKNOWN]);

  const unknownRow = await runRow(page, UNKNOWN);
  const validRow = await runRow(page, VALID_A);

  check(
    unknownRow?.runDisabled === true,
    "the unreviewed dataset's Run is disabled in the Run step",
  );
  check(
    (unknownRow?.text ?? "").includes("Skipped"),
    "the unreviewed dataset is labelled Skipped, not silently ignored",
  );
  check(
    (unknownRow?.text ?? "").replace(/\s+/g, " ").includes(
      `Confirm the dataset role for ${UNKNOWN} to include it`,
    ),
    "the skipped dataset says which role would include it",
  );
  check(
    await runEnabled(page, VALID_A),
    `the valid dataset's Run is enabled in the same package (${await runStepDiagnostics(page)})`,
  );

  const runStepText = await flatText(page);
  check(
    runStepText.includes("1 of 2 selected datasets ready to run."),
    "the Run step says how many selected datasets are ready",
  );
  check(
    runStepText.includes(`1 dataset is skipped and will not be analysed: ${UNKNOWN}.`),
    "the Run step names the dataset it is skipping",
  );

  // -----------------------------------------------------------------------
  // 2. Only unreviewed roles: nothing to run, and the reason says so.
  // -----------------------------------------------------------------------
  await startPackage(page, [UNKNOWN]);

  const continueUnknownOnly = await buttonState(page, "Continue to Run");
  check(
    continueUnknownOnly.found && continueUnknownOnly.disabled,
    "UNKNOWN only: Continue to Run is disabled",
  );
  check(
    (await flatText(page)).includes(`Confirm the dataset role for ${UNKNOWN}`),
    "UNKNOWN only: the gate explains that role confirmation is required",
  );

  // -----------------------------------------------------------------------
  // 3. A validation error on a dataset that would otherwise be run is still a
  //    hard blocker, even when another dataset is runnable.
  // -----------------------------------------------------------------------
  await startPackage(page, [VALID_A, INVALID]);

  const continueInvalid = await buttonState(page, "Continue to Run");
  check(
    continueInvalid.found && continueInvalid.disabled,
    "valid + validation error: Continue to Run is disabled",
  );
  check(
    (await flatText(page)).includes(
      `Resolve the blocking validation error in ${INVALID}`,
    ),
    "valid + validation error: the gate names the validation error to resolve",
  );

  // -----------------------------------------------------------------------
  // 4. Warnings are not blockers.
  // -----------------------------------------------------------------------
  const warningDataset = warningOnly[0]?.dataset;

  if (warningDataset) {
    await startPackage(page, [warningDataset]);

    const warningPreview = previews.get(warningDataset);
    const continueWarnings = await buttonState(page, "Continue to Run");
    check(
      continueWarnings.found && !continueWarnings.disabled,
      `warnings without validation errors: Continue to Run is enabled for ${warningDataset}`,
    );
    check(
      (warningPreview?.validation.warning_count ?? 0) > 0 &&
        (warningPreview?.validation.error_count ?? 0) === 0,
      `the dataset that case used carries ${warningPreview?.validation.warning_count ?? "?"} warning(s) and no error`,
    );
  }

  // -----------------------------------------------------------------------
  // 5. A reviewer role turns an unreviewed dataset into a runnable one.
  // -----------------------------------------------------------------------
  await startPackage(page, [VALID_A, UNKNOWN]);

  await page.evaluate((wanted) => {
    const row = [...document.querySelectorAll("li")].find((item) =>
      item.innerText.includes(wanted.split("/").pop()),
    );

    row.querySelector("button").click();
  }, UNKNOWN);

  await page.waitForFunction(
    (wanted) => document.getElementById(`role-select-${wanted}`) !== null,
    { timeout: 15000 },
    UNKNOWN,
  );

  await page.evaluate((wanted) => {
    const select = document.getElementById(`role-select-${wanted}`);

    select.value = "ALERTS";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }, UNKNOWN);

  // Choosing a role marks that dataset stale until its preview is refreshed:
  // the dataset is not runnable yet, and it does not hold back the package.
  const staleText = await flatText(page);
  check(
    staleText.includes("Stale") && staleText.includes("Mapping changed"),
    "a chosen role marks the dataset stale until its preview is refreshed",
  );

  const continueStale = await buttonState(page, "Continue to Run");
  check(
    continueStale.found && !continueStale.disabled,
    "one stale dataset does not hold back the rest of the package",
  );

  await clickButton(page, "Refresh preview");
  // The refresh control only exists while the preview is stale, so its
  // disappearance is the preview settling.
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll("button")].some(
        (button) => button.textContent.trim() === "Refresh preview",
      ),
    { timeout: PREVIEW_TIMEOUT },
  );

  const continueOverridden = await buttonState(page, "Continue to Run");
  check(
    continueOverridden.found && !continueOverridden.disabled,
    "UNKNOWN + reviewer role: Continue to Run is enabled",
  );
  check(
    (await flatText(page)).includes("Ready"),
    "UNKNOWN + reviewer role: the refreshed preview is ready",
  );

  await clickButton(page, "Continue to Run");
  await waitForRunStep(page, [VALID_A, UNKNOWN]);
  check(
    await runEnabled(page, UNKNOWN),
    `UNKNOWN + reviewer role: the dataset is runnable, not skipped (${await runStepDiagnostics(page)})`,
  );
  const overriddenRow = await runRow(page, UNKNOWN);
  check(
    overriddenRow?.runDisabled === false,
    "UNKNOWN + reviewer role: its Run button reads as enabled",
  );
  check(
    !(overriddenRow?.text ?? "").includes("Skipped"),
    "UNKNOWN + reviewer role: the dataset is no longer labelled skipped",
  );

  // -----------------------------------------------------------------------
  // 6. Two valid datasets: both are runnable.
  // -----------------------------------------------------------------------
  await startPackage(page, [VALID_A, VALID_B]);

  const continueBoth = await buttonState(page, "Continue to Run");
  check(
    continueBoth.found && !continueBoth.disabled,
    "two valid datasets: Continue to Run is enabled",
  );

  await clickButton(page, "Continue to Run");
  await waitForRunStep(page, [VALID_A, VALID_B]);
  const bothEnabled = (
    await Promise.all([runEnabled(page, VALID_A), runEnabled(page, VALID_B)])
  ).every(Boolean);
  check(
    bothEnabled,
    `two valid datasets: both Run buttons are enabled (${await runStepDiagnostics(page)})`,
  );
  check(
    (await flatText(page)).includes("2 of 2 selected datasets ready to run."),
    "two valid datasets: both are counted as ready",
  );

  // -----------------------------------------------------------------------
  // Finally: a run started from a mixed package analyses the runnable dataset.
  // Done last, because it leaves a run in flight in the service.
  // -----------------------------------------------------------------------
  await startPackage(page, [VALID_A, UNKNOWN]);
  await clickButton(page, "Continue to Run");
  await waitForRunStep(page, [VALID_A, UNKNOWN]);

  const before = new Set(
    (await (await fetch(`${API}/api/analyses`)).json()).analyses.map(
      (item) => item.job_id,
    ),
  );

  // Click the runnable dataset's Run, waiting for it to be clickable: the
  // interface disables it while a run is in flight.
  await runEnabled(page, VALID_A);
  await page.evaluate((wanted) => {
    const row = [...document.querySelectorAll("li")].find((item) =>
      item.innerText.includes(wanted.split("/").pop()),
    );

    [...row.querySelectorAll("button")]
      .find((button) => button.textContent.trim() === "Run")
      .click();
  }, VALID_A);

  await page.waitForFunction(() => window.location.pathname === "/", {
    timeout: 60000,
  });

  const run = await (async () => {
    const deadline = Date.now() + RUN_TIMEOUT;

    while (Date.now() < deadline) {
      const analyses = (await (await fetch(`${API}/api/analyses`)).json())
        .analyses;
      const started = analyses.filter((item) => !before.has(item.job_id));

      if (started.length > 0) {
        return started[started.length - 1];
      }

      await new Promise((resolve) => setTimeout(resolve, 1000));
    }

    return null;
  })();

  check(
    run !== null && run.dataset === VALID_A,
    `the run analysed ${VALID_A} (got ${run ? run.dataset : "no new run"})`,
  );
  check(
    run !== null && run.dataset !== UNKNOWN,
    "the skipped dataset was not analysed",
  );

  // Leave the service idle so the check does not leave a run in flight.
  if (run && ["processing", "pending", "running"].includes(run.status)) {
    const deadline = Date.now() + RUN_TIMEOUT;

    while (Date.now() < deadline) {
      const latest = await (
        await fetch(`${API}/api/analyses/${encodeURIComponent(run.job_id)}`)
      ).json();

      if (!["processing", "pending", "running"].includes(latest.status)) {
        break;
      }

      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
} catch (error) {
  failures.push(`the check could not finish: ${error.message}`);
} finally {
  await browser.close();
}

// ---------------------------------------------------------------------------

const offenders = consoleErrors.filter(
  (text) =>
    !text.includes("favicon") && !text.includes("Download the React DevTools"),
);

check(
  offenders.length === 0,
  `no console errors (${offenders.length})${offenders.length ? `: ${offenders.join(" | ")}` : ""}`,
);

if (skips.length > 0) {
  console.log(skips.join("\n"));
}
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