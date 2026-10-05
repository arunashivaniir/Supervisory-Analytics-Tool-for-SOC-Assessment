/**
 * Regression checks for changing the dataset on screen.
 *
 * Six behaviours, each of which was a way for the interface to lose an
 * assessment that had already been produced:
 *
 *   1. the selector opens from the top bar;
 *   2. it lists the datasets the service can actually open;
 *   3. a dataset can be selected and a run started;
 *   4. a completed run replaces the loaded assessment on every screen;
 *   5. cancelling a switch leaves the loaded assessment untouched;
 *   6. a run that fails leaves the loaded assessment untouched.
 *
 * Driven through Chromium against the running interface and the running
 * adapter, because the thing being protected is a sequence of state changes
 * across a request: a unit test of the context would not show whether the
 * screens behind the dialog kept their result.
 *
 * The failure cases are produced by intercepting the adapter's own responses.
 * That is deliberate: it tests the two failure modes the interface can meet —
 * a run that cannot be started, and a run that reports an error — without
 * contriving a corrupt dataset in the workspace, and without waiting for a real
 * pipeline failure to occur by chance.
 *
 * Usage: node scripts/check-dataset-switching.mjs [interfaceUrl] [apiUrl]
 */

import puppeteer from "puppeteer-core";

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";
const API = process.argv[3] ?? "http://127.0.0.1:8000";

const notes = [];
const failures = [];

function check(condition, message) {
  if (condition) {
    notes.push(`  ok    ${message}`);
  } else {
    failures.push(message);
    notes.push(`  FAIL  ${message}`);
  }
}

/**
 * A check that cannot be made with the data at hand, and that would only be
 * able to pass by accident if it were made anyway. Skipped counts neither way.
 */
function skip(message) {
  notes.push(`  skip  ${message}`);
}

/**
 * Runs as the service recorded them, read directly from the service.
 *
 * The screens are checked against what the backend produced rather than against
 * a difference in wording, so that a screen that never changed is a failure and
 * a screen that changed for another reason is not a pass.
 */
const listRuns = async () => {
  const payload = await (await fetch(`${API}/api/analyses`)).json();
  return Array.isArray(payload) ? payload : payload.analyses;
};

const readRun = async (jobId) =>
  jobId ? await (await fetch(`${API}/api/analyses/${jobId}`)).json() : null;

/**
 * The dataset a switch is performed *to*.
 *
 * This is named rather than discovered, and that is the whole point of the
 * change.
 *
 * It used to be `DATASETS.find((path) => path !== first)` — the first entry in
 * the service's listing that is not the demo. On an unmodified workspace that
 * resolved to `data.csv`, a 56-byte file with a single column. The run finished
 * in tens of milliseconds, so the top bar never reached the `Assessing` state
 * these checks exist to observe, and the check failed on a timeout while
 * asserting nothing. The failure had nothing to do with the code under test:
 * the dataset simply did not take long enough to have a lifecycle.
 *
 * Listing order is a property of the filesystem, not of this check, so any
 * dataset it picked was incidental. A switching check must run against a
 * dataset whose analysis genuinely takes time and genuinely differs from the
 * loaded one, and those are properties of a specific file rather than of
 * whatever happens to sort first.
 *
 * `soc_asset_inventory_q3_2026.csv` was chosen because it satisfies every
 * property the checks below depend on:
 *
 *   - it is a real submission, not a fixture built to be slow. There is no
 *     delay in it and none was added; the time is the pipeline's own work
 *     across every layer (profiling, semantic inference, canonical mapping,
 *     feature evaluation, supervisory and entity assessment, peer benchmarking).
 *   - it takes long enough to be observed. Roughly 2.6s end to end against the
 *     demo's 200s+, which leaves the `Assessing` state on screen for long
 *     enough to be polled at 200ms without racing the run's completion.
 *   - it differs from the first dataset in every way a switch is supposed to
 *     change: a different schema and role (an ASSETS register against an alert
 *     submission), a different record count (3,970 against 23,630), a
 *     different scope count (8 against 6), and a different finding profile (no
 *     findings against 17). A switch that changed nothing would be invisible.
 *   - it passes validation with `error_count: 0`, so the run is permitted and a
 *     real assessment is promoted rather than refused.
 *   - it is small enough to be practical: about 686 KB, and a couple of seconds
 *     per run, against tens of megabytes and minutes for the larger
 *     submissions in the workspace.
 *
 * If it is replaced, those five properties are what must be preserved. The
 * absence of any fallback is deliberate: silently falling back to listing order
 * is precisely what made this check test nothing.
 */
const SWITCH_TARGET = "soc_asset_inventory_q3_2026.csv";

/** Every dataset the service can open, as the selector will offer them. */
const DATASETS = await (await fetch(`${API}/api/datasets`)).json()
  .then((body) => body.datasets ?? [])
  .then((datasets) => datasets.map((item) => item.path));

if (DATASETS.length < 2) {
  console.log("at least two datasets are required to check switching");
  process.exit(1);
}

if (!DATASETS.includes(SWITCH_TARGET)) {
  console.log(
    `the switch target ${SWITCH_TARGET} is not offered by the service.\n` +
      "These checks need a real second dataset whose analysis takes long enough\n" +
      "to observe and differs from the first; substituting an arbitrary one would\n" +
      "make the checks pass without testing anything. See SWITCH_TARGET above.",
  );
  process.exit(1);
}

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
page.setDefaultNavigationTimeout(60000);

/**
 * Console errors, except the ones a failure check asked for.
 *
 * A check that makes the adapter return 500, or that provokes a real 409
 * refusal, causes the browser to log a resource error. That is the behaviour
 * under test rather than a defect, so errors raised while a failure is expected
 * are not counted. The flag is set only for the duration of those checks.
 */
const consoleErrors = [];
let intercept = null;
let expectingFailure = false;

page.on("console", (message) => {
  if (message.type() === "error" && !expectingFailure) {
    consoleErrors.push(message.text());
  }
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

/**
 * Which adapter response, if any, is being replaced.
 *
 * Set immediately before a check that needs a failure, cleared straight after.
 * The handler is attached once: adding and removing request listeners mid-run
 * races with the interface's own polling.
 */
page.on("request", (request) => {
  if (intercept === "start-fails") {
    if (request.url().endsWith("/api/analyses") && request.method() === "POST") {
      void request.respond({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "run could not be started" }),
      });
      return;
    }
  }

  if (intercept === "run-fails") {
    // Only the run being polled is replaced. The listing the interface reads on
    // mount does not match, so it is served normally.
    if (/\/api\/analyses\/[0-9a-f]{8,}/.test(request.url()) && request.method() === "GET") {
      void request.respond({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: "interrupted",
          dataset: second,
          status: "error",
          created_at: new Date().toISOString(),
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          log: [],
          error: "RuntimeError: the pipeline could not complete this run",
          result: null,
        }),
      });
      return;
    }
  }

  void request.continue();
});

await page.setRequestInterception(true);

const bodyText = () => page.evaluate(() => document.body.innerText);

/** The dataset the top bar says is loaded. */
async function loadedDataset() {
  return page.evaluate(() => {
    const header = document.querySelector("header");
    const label = [...(header?.querySelectorAll("div") ?? [])].find(
      (node) => node.textContent.trim() === "Dataset",
    );
    return label?.nextElementSibling?.textContent?.trim() ?? null;
  });
}

async function openSelector() {
  // Any dialog already open is closed first.
  //
  // The selector stays open while a run is in flight, so a flow that follows
  // another can find one still on screen — parked on whichever step it was left
  // at, which is rarely the step that lists datasets. Opening "again" then found
  // a dialog rather than a new one and carried the previous flow's selection into
  // the next. Every flow now starts from the same place.
  if (
    await page.evaluate(() => Boolean(document.querySelector('[role="dialog"]')))
  ) {
    await closeSelector();
  }

  await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((node) =>
      /^(Change|Select) dataset$/.test(node.textContent.trim()),
    );
    button?.click();
  });

  await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
}

async function closeSelector() {
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), {
    timeout: 15000,
  });
}

/** Choose a dataset in the dialog and start the run. */
async function selectAndRun(path) {
  // Matched on the full path, which the row shows beneath the file name. A file
  // name on its own is not unique: `execution_gap_test.csv` contains
  // `test.csv`, and choosing the wrong row would test the wrong thing.
  //
  // The row is waited for rather than looked for once. The dialog fetches the
  // list when it opens, and refetches it after a run fails, so a single attempt
  // made this depend on which flow ran before: the list had not arrived, the row
  // was never clicked, and the walk below then continued on whatever dataset was
  // still selected — starting a run for the wrong file and passing the checks
  // that follow. Absence is now a recorded failure instead of a silent
  // substitution.
  let clicked = false;

  try {
    await page.waitForFunction(
      (target) =>
        [...document.querySelectorAll('[role="dialog"] li button')].some(
          (node) => node.textContent.includes(target),
        ),
      { timeout: 15000, polling: 100 },
      path,
    );

    clicked = await page.evaluate((target) => {
      const rows = [...document.querySelectorAll('[role="dialog"] li button')];
      const row = rows.find((node) => node.textContent.includes(target));

      if (!row) {
        return false;
      }

      row.click();
      return true;
    }, path);
  } catch {
    clicked = false;
  }

  check(clicked, `the selector offers ${path}`);

  if (!clicked) {
    // Nothing was chosen, so the dataset still selected in the dialog is the one
    // that was loaded. Walking on to start a run would launch that instead and
    // report the result as though it belonged to the dataset under test.
    check(false, `the selector can start a run for ${path}`);
    return;
  }

  // Walk the wizard the way an examiner does.
  //
  // The selector is a four-step flow: choose a dataset, validate, review the
  // mapping, confirm. The run button only exists on the final step, so it has
  // to be reached by pressing Continue until it appears.
  //
  // This used to click the run button once, immediately, and tolerate its
  // absence with `button?.click()`. On the first step no such button exists, so
  // nothing was clicked, no run was started, and every check after this one was
  // reasoning about a run that never happened: the silence of `?.` made a broken
  // check look like a passing one. The click is now confirmed, so a selector
  // that cannot start a run fails here rather than quietly invalidating the
  // sequence behind it.
  //
  // Each press waits for the step to change before the next one. React captures
  // `step` in a closure, so pressing Continue several times inside one tick
  // advances a single step; without the wait the walk stalls on step two and
  // never reaches the run button.
  const runButtonShown = () =>
    page.evaluate(() =>
      [...(document.querySelector('[role="dialog"]')?.querySelectorAll("button") ?? [])].some(
        (node) =>
          /Switch to this dataset|Run assessment/.test(
            node.textContent.trim(),
          ),
      ),
    );

  const activeStep = () =>
    page.evaluate(() => {
      const current = document.querySelector(
        '[role="dialog"] [aria-current="step"]',
      );

      return current?.textContent?.trim() ?? null;
    });

  let confirmed = false;

  // Bounded by the wizard's own length, so a selector that never reaches a run
  // button fails here instead of spinning.
  for (let step = 0; step < 8; step += 1) {
    if (await runButtonShown()) {
      confirmed = await page.evaluate(() => {
        const run = [
          ...(document.querySelector('[role="dialog"]')?.querySelectorAll("button") ?? []),
        ].find((node) =>
          /Switch to this dataset|Run assessment/.test(
            node.textContent.trim(),
          ),
        );

        if (!run) {
          return false;
        }

        run.click();
        return true;
      });

      break;
    }

    const from = await activeStep();

    const advanced = await page.evaluate(() => {
      const next = [
        ...(document.querySelector('[role="dialog"]')?.querySelectorAll("button") ?? []),
      ].find((node) => node.textContent.trim() === "Continue");

      if (!next) {
        return false;
      }

      next.click();
      return true;
    });

    if (!advanced) {
      break;
    }

    await page.waitForFunction(
      (previous) => {
        const dialog = document.querySelector('[role="dialog"]');

        if (!dialog) {
          return false;
        }

        const reachedRun = [...dialog.querySelectorAll("button")].some((node) =>
          /Switch to this dataset|Run assessment/.test(
            node.textContent.trim(),
          ),
        );

        const current = dialog.querySelector('[aria-current="step"]');

        return reachedRun || (current?.textContent?.trim() ?? null) !== previous;
      },
      { timeout: 15000, polling: 100 },
      from,
    );
  }

  check(confirmed, `the selector can start a run for ${path}`);
}

/** Wait until the top bar no longer shows a run in progress. */
async function waitForIdle(timeout = 240000) {
  await page.waitForFunction(
    () => {
      const text = document.querySelector("header")?.textContent ?? "";
      return !text.includes("Assessing") && !text.includes("Processing");
    },
    { timeout, polling: 500 },
  );
}

// ---------------------------------------------------------------------------
// A loaded assessment to protect. Started through the adapter, so the
// interface is looking at a real result when the checks begin.
// ---------------------------------------------------------------------------

// The run these checks protect: the demo submission, chosen by name because it
// is the workspace's reference assessment and produces a result rich enough to
// tell apart from the one that replaces it.
const first = DATASETS.find((path) => path.includes("demo")) ?? DATASETS[0];

// The run performed against it. See SWITCH_TARGET for why this is named rather
// than taken from listing order.
const second = SWITCH_TARGET;

check(
  first !== second,
  `the switch target differs from the loaded dataset (${first} -> ${second})`,
);

const started = await (
  await fetch(`${API}/api/analyses`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ dataset: first }),
  })
).json();

for (let attempt = 0; attempt < 600; attempt += 1) {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const state = await (
    await fetch(`${API}/api/analyses/${started.job_id}?include_result=false`)
  ).json();

  if (state.status !== "processing") {
    check(
      state.status === "complete",
      `the starting run completed (status ${state.status})`,
    );
    break;
  }
}

await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
await page.waitForFunction(
  () => document.querySelector("header")?.textContent?.includes("complete"),
  { timeout: 60000, polling: 500 },
);

const before = await loadedDataset();
check(Boolean(before), `an assessment is loaded (${before})`);

// ---------------------------------------------------------------------------
// 1. the selector opens
// ---------------------------------------------------------------------------

await openSelector();
check(
  (await page.$('[role="dialog"]')) !== null,
  "the dataset selector opens from the top bar",
);

// ---------------------------------------------------------------------------
// 2. it lists the datasets the service can open
// ---------------------------------------------------------------------------

const listed = await page.evaluate(() =>
  [...document.querySelectorAll('[role="dialog"] li button')].map((node) =>
    node.textContent.trim(),
  ),
);

for (const path of DATASETS) {
  check(
    listed.some((row) => row.includes(path.split("/").pop())),
    `the selector lists ${path}`,
  );
}

check(
  listed.some((row) => row.includes("data/")) ||
    DATASETS.every((path) => !path.includes("data/")),
  "dataset paths are shown, so the file can be identified before it is run",
);

// ---------------------------------------------------------------------------
// 5. cancelling a switch leaves the loaded assessment untouched
// ---------------------------------------------------------------------------

await page.evaluate(() => {
  const button = [...document.querySelectorAll('[role="dialog"] button')].find(
    (node) => /^Cancel$/.test(node.textContent.trim()),
  );
  button?.click();
});

await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), {
  timeout: 15000,
});

check(
  (await loadedDataset()) === before,
  `cancelling the selector preserves the loaded dataset (${before})`,
);

check(
  !(await bodyText()).includes("No assessment loaded"),
  "cancelling does not leave the screens without an assessment",
);

// The same must hold for cancelling a switch that is already under way.
await openSelector();
await selectAndRun(second);
await page.waitForFunction(
  () => (document.querySelector("header")?.textContent ?? "").includes("Assessing"),
  { timeout: 30000, polling: 200 },
);

const duringSwitch = await loadedDataset();
check(
  duringSwitch === before,
  `a switch in progress keeps the loaded dataset on screen (${duringSwitch})`,
);

check(
  (await bodyText()).includes(before),
  "the loaded assessment is still rendered while another is being produced",
);

await page.evaluate(() => {
  const button = [...document.querySelectorAll('[role="dialog"] button')].find(
    (node) => /Cancel switch/.test(node.textContent.trim()),
  );
  button?.click();
});

await closeSelector();
await waitForIdle();

check(
  (await loadedDataset()) === before,
  "cancelling a running switch preserves the loaded dataset",
);

check(
  !(await bodyText()).includes("No assessment loaded"),
  "cancelling a running switch does not blank the screens",
);

// ---------------------------------------------------------------------------
// 6a. a run that cannot be started leaves the loaded assessment untouched
// ---------------------------------------------------------------------------

intercept = "start-fails";
expectingFailure = true;

await openSelector();
await selectAndRun(second);
await page.waitForFunction(
  () => (document.body.innerText ?? "").includes("run could not be started"),
  { timeout: 20000, polling: 200 },
);

check(
  (await loadedDataset()) === before,
  "a run that could not be started preserves the loaded dataset",
);

check(
  !(await bodyText()).includes("No assessment loaded"),
  "a run that could not be started does not blank the screens",
);

intercept = null;
expectingFailure = false;

// ---------------------------------------------------------------------------
// 6b. a run that reports an error leaves the loaded assessment untouched
// ---------------------------------------------------------------------------

intercept = "run-fails";
expectingFailure = true;

await openSelector();
await selectAndRun(second);
await page.waitForFunction(
  () => (document.body.innerText ?? "").includes("could not complete this run"),
  { timeout: 30000, polling: 200 },
);

check(
  (await loadedDataset()) === before,
  "a run that reports an error preserves the loaded dataset",
);

check(
  !(await bodyText()).includes("No assessment loaded"),
  "a run that reports an error does not blank the screens",
);

intercept = null;
expectingFailure = false;
await closeSelector();

// ---------------------------------------------------------------------------
// 6c. evidence that does not verify cannot be analysed
// ---------------------------------------------------------------------------
//
// Checked through the interface, because the requirement is that the *run* does
// not happen: the trust layer's comparison has to reach the examiner as a
// refusal, and the loaded assessment has to survive being refused.

const register = await (
  await fetch(`${API}/api/evidence`)
).json().then((body) => body.evidence ?? []);

// A refused submission has no analysis target, because the trust layer stops
// before resolving one. Its working copy is still a file the selector offers, so
// the check needs its path in order to attempt the run the examiner could
// attempt. The path is composed from what the register reports, not guessed:
// the evidence ID names the directory and the manifest names the stored file.
const workingCopyOf = (submission) =>
  [
    "data/evidence/working",
    submission.evidence_id,
    "dataset",
    submission.source.stored_name,
  ].join("/");

const unverifiable = register.find((item) => !item.analysis.permitted);

const blockedPath = unverifiable
  ? (unverifiable.analysis.target_path ?? workingCopyOf(unverifiable))
  : null;

if (!unverifiable || !blockedPath) {
  notes.push(
    "  skip  no unverifiable submission in the local evidence register to attempt",
  );
} else {
  expectingFailure = true;

  await openSelector();
  await selectAndRun(blockedPath);

  const refused = await page
    .waitForFunction(
      (expected) => (document.body.innerText ?? "").includes(expected),
      { timeout: 30000, polling: 200 },
      unverifiable.analysis.blocked_reason ?? "",
    )
    .then(() => true)
    .catch(() => false);

  check(
    refused,
    `the interface reports why ${unverifiable.evidence_id} may not be analysed`,
  );

  check(
    (await loadedDataset()) === before,
    "a refused run preserves the loaded dataset",
  );

  check(
    !(await bodyText()).includes("No assessment loaded"),
    "a refused run does not blank the screens",
  );

  const held = await (
    await fetch(`${API}/api/analyses?include_result=false`)
  ).json();

  check(
    (held.analyses ?? []).every((job) => job.dataset !== blockedPath),
    `no run was started for ${blockedPath}`,
  );

  expectingFailure = false;
}

// ---------------------------------------------------------------------------
// 3 + 4. selecting a dataset, and the run replacing the assessment everywhere
// ---------------------------------------------------------------------------

const recordCount = async (route) => {
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("h1", { timeout: 30000 });
  return page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
};

const beforeEvidence = await recordCount("/evidence");
const beforeReports = await recordCount("/reports");
const beforeOverview = await recordCount("/");
const beforeAssessments = await recordCount("/assessments");
const beforeFindings = await recordCount("/findings");

// The run these checks have protected from the start, and the one still on
// screen: every switch that failed above left it there. This is compared
// against rather than the newest run in the store, because cancelling a switch
// stops the interface watching a run without stopping the run, and a run
// completed in the background would otherwise be mistaken for the one the
// screens were showing.
const beforeRun = await readRun(started.job_id);

await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
await page.waitForFunction(
  () => document.querySelector("header")?.textContent?.includes("complete"),
  { timeout: 60000, polling: 500 },
);

await openSelector();
await selectAndRun(second);
check(true, "a dataset can be selected and a run started from the selector");

await closeSelector();
await waitForIdle();

// The top bar names a dataset by its stem, as every other screen does.
const after = await loadedDataset();
check(
  after === second.split("/").pop().replace(/\.[^.]+$/, ""),
  `the new dataset is the one loaded (${after})`,
);

check(
  !(await bodyText()).includes("No assessment loaded"),
  "the assessment is present after the switch",
);

// Every screen must now describe the new run. Waiting for the top bar to name
// the promoted dataset before reading a screen matters: a screen read while the
// new run is still loading still shows the previous one, and would otherwise
// pass a "did anything change" test without ever having shown the new run.
const screenOfPromotedRun = async (route) => {
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("h1", { timeout: 30000 });

  if (after) {
    await page.waitForFunction(
      (dataset) => document.querySelector("header")?.textContent?.includes(dataset),
      { timeout: 60000, polling: 250 },
      after,
    );
  }

  return page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
};

const afterOverview = await screenOfPromotedRun("/");
const afterAssessments = await screenOfPromotedRun("/assessments");
const afterFindings = await screenOfPromotedRun("/findings");
const afterEvidence = await screenOfPromotedRun("/evidence");
const afterReports = await screenOfPromotedRun("/reports");

// The figures the promoted run and the run it replaced actually carry, so each
// screen is checked against the backend's own values rather than against a
// difference in wording.
const thousands = (value) => Number(value).toLocaleString("en-US");

const promotedRunId = (await listRuns()).slice(-1)[0]?.job_id ?? null;
const promotedRun = await readRun(promotedRunId);

const promotedRecords = thousands(promotedRun?.result?.ingestion?.record_count);
const previousRecords = beforeRun?.result?.ingestion?.record_count === undefined
  ? null
  : thousands(beforeRun.result.ingestion.record_count);

// A count of a few digits is present on any page by accident, so it is only
// used to show a figure is present when it is long enough to mean something.
const distinctive = promotedRecords !== null && promotedRecords.length >= 5;
const comparable = previousRecords !== null && previousRecords !== promotedRecords;

// Which screens present the run's ingestion record count at all. The findings
// screen is a triage list of findings and has never carried one; demanding it
// there would be asserting a figure the screen is not built to show. That
// screen is instead held to a positive assertion on what it does render, and
// the stale-count check below still applies to every screen including it.
const screensWithRecordCount = new Set([
  "overview",
  "assessments",
  "evidence",
  "reports",
]);

for (const [route, now] of [
  ["overview", afterOverview],
  ["assessments", afterAssessments],
  ["findings", afterFindings],
  ["evidence", afterEvidence],
  ["reports", afterReports],
]) {
  check(
    now !== undefined && now.length > 0,
    `${route} rendered after the switch`,
  );

  if (screensWithRecordCount.has(route)) {
    if (distinctive) {
      check(
        now.includes(promotedRecords),
        `${route} shows the promoted run's record count (${promotedRecords})`,
      );
    } else {
      skip(
        `${route} record count (${promotedRecords}) is too short to prove the run changed`,
      );
    }
  } else if (distinctive && after) {
    check(
      now.includes(after),
      `${route} names the promoted run's dataset (${after})`,
    );
  }

  if (comparable) {
    check(
      !now.includes(previousRecords),
      `${route} no longer shows the previous run's record count (${previousRecords})`,
    );
  }
}

check(
  afterEvidence.includes(after) || !after,
  "the evidence screen names the newly selected dataset",
);

check(
  afterFindings.includes(after) || !after,
  "the findings screen names the newly selected dataset",
);

const changed = (before, now) => before !== now;
check(
  changed(beforeOverview, afterOverview) ||
    changed(beforeAssessments, afterAssessments) ||
    changed(beforeFindings, afterFindings) ||
    changed(beforeEvidence, afterEvidence) ||
    changed(beforeReports, afterReports),
  "the screens are showing the new run rather than the previous one",
);

// ---------------------------------------------------------------------------

const offenders = consoleErrors.filter(
  (text) =>
    !text.includes("favicon") && !text.includes("Download the React DevTools"),
);

check(
  offenders.length === 0,
  `no console errors (${offenders.length})${offenders.length ? `: ${offenders.join(" | ")}` : ""}`,
);

await browser.close();

console.log(`protected dataset: ${before} -> ${after}`);
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
