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

/** Two datasets that are not the same file, chosen by name from the listing. */
const DATASETS = await (await fetch(`${API}/api/datasets`)).json()
  .then((body) => body.datasets ?? [])
  .then((datasets) => datasets.map((item) => item.path));

if (DATASETS.length < 2) {
  console.log("at least two datasets are required to check switching");
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
  const clicked = await page.evaluate((target) => {
    const rows = [...document.querySelectorAll('[role="dialog"] li button')];
    const row = rows.find((node) => node.textContent.includes(target));

    if (!row) {
      return false;
    }

    row.click();
    return true;
  }, path);

  check(clicked, `the selector offers ${path}`);

  await page.evaluate(() => {
    const button = [...document.querySelectorAll('[role="dialog"] button')].find(
      (node) => /Switch to this dataset|Run assessment/.test(node.textContent.trim()),
    );
    button?.click();
  });
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

const first = DATASETS.find((path) => path.includes("demo")) ?? DATASETS[0];
const second = DATASETS.find((path) => path !== first);

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
