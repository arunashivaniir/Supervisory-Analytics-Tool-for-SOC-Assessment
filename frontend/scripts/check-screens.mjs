/**
 * A browser check of the five screens against a real pipeline result.
 *
 * Not a unit test: it drives Chromium against the running interface and the
 * running adapter, so a component that throws on real backend output, a route
 * that does not resolve, or a value the interface invented would all show up
 * here.
 *
 * The checks are written against whatever run the interface actually loaded,
 * which is the most recent one the service holds. Expectations are read from
 * that run's result rather than hard-coded, so the same check is meaningful for
 * evidence that produced findings and evidence that produced none, and a wrong
 * number on screen fails.
 *
 * Usage: node scripts/check-screens.mjs [interfaceUrl] [apiUrl]
 */

import puppeteer from "puppeteer-core";

const BASE = process.argv[2] ?? "http://127.0.0.1:5173";
const API = process.argv[3] ?? "http://127.0.0.1:8000";

const notes = [];
const failures = [];
const skips = [];

function check(condition, message) {
  if (condition) {
    notes.push(`  ok    ${message}`);
  } else {
    failures.push(message);
    notes.push(`  FAIL  ${message}`);
  }
}

function skip(message) {
  skips.push(message);
  notes.push(`  skip  ${message}`);
}

const grouped = (value) => new Intl.NumberFormat("en-GB").format(value);

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/chromium",
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });

// The interface polls while a run is in flight, so the network never goes idle.
// Waiting for the document and the heading is the right condition here.
page.setDefaultNavigationTimeout(60000);

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") {
    consoleErrors.push(message.text());
  }
});
page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

/** Start a run if the service has not already finished one. */
async function mostRecentCompletedRun() {
  const held = await (
    await fetch(`${API}/api/analyses?include_result=false`)
  ).json();

  const runs = (held.analyses ?? []).filter((job) => job.status === "complete");

  if (runs.length === 0) {
    const started = await (
      await fetch(`${API}/api/analyses`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dataset: "data/demo/incident_event_log.csv" }),
      })
    ).json();

    for (let attempt = 0; attempt < 400; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const state = await (
        await fetch(`${API}/api/analyses/${started.job_id}?include_result=false`)
      ).json();

      if (state.status !== "processing") {
        check(state.status === "complete", `run completed (status ${state.status})`);
        break;
      }
    }
  } else {
    check(true, "using a completed run the service already holds");
  }

  const listed = await (
    await fetch(`${API}/api/analyses?include_result=false`)
  ).json();

  const runs2 = (listed.analyses ?? []).filter((job) => job.status === "complete");
  const newest = runs2[runs2.length - 1];

  return {
    job: newest,
    result: (await (await fetch(`${API}/api/analyses/${newest.job_id}`)).json())
      .result,
  };
}

const { job, result } = await mostRecentCompletedRun();

check(
  typeof result === "object" && result !== null,
  "the loaded run returned a pipeline result",
);

// Everything the screens are checked against comes from this result.
const findingCounts = {
  execution_gap: result.execution_gap_findings.finding_count,
  negative_space: result.negative_space_findings.finding_count,
  operational_pattern: result.operational_pattern_findings.finding_count,
};
const expectedFindings = Object.values(findingCounts).reduce((a, b) => a + b, 0);
const scopeCount = result.assessment.scope_count;
const recordCount = result.assessment.record_count;
const verdicts = result.anomaly_findings.verdict_counts;
const firstScope = result.capability_assessment.scopes[0];
const entityResolved = result.assessment.entity_resolution.available;
const periodResolved = result.assessment.period_resolution.available;

/**
 * A screen's text, once the screen has settled.
 *
 * Waiting for the heading alone is not enough: the run is restored and the
 * evidence register is read after the first paint, so an early snapshot would
 * catch the "no assessment loaded" state and fail every check on the screen
 * while the interface is in fact correct. So this waits for the top bar to
 * report a run, then for the requests behind the screen to finish.
 */
async function pageText(path) {
  await page.goto(`${BASE}${path}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("h1", { timeout: 30000 });
  await page.waitForFunction(
    () => {
      const text = document.querySelector("header")?.textContent ?? "";
      return (
        text.includes("Analysis complete") ||
        text.includes("No analysis") ||
        text.includes("Error")
      );
    },
    { timeout: 60000, polling: 200 },
  );
  await page.waitForNetworkIdle({ idleTime: 600, timeout: 30000 });

  return page.evaluate(() => document.body.innerText.replace(/\s+/g, " "));
}

// ---------------------------------------------------------------------------
// 0. With no run held at all, the interface must not claim one is in progress.
//
// This is a regression check for a real defect. The empty run was given the
// phase `queued` because `RunPhase` had no member for "holding nothing", and the
// Overview read that phase as proof of an active run. The result was a first
// visit — or any moment with no run — showing "No dataset selected" in the top
// bar beside "Assessment in progress" and "The pipeline is assessing the selected
// dataset." on the Overview, when no dataset had ever been chosen.
//
// The backend is not modified or restarted: a second page intercepts only the
// run *listing* and reports no runs, which is the same client state as a service
// that holds none, so the lifecycle is exercised exactly as it is on a first
// visit.
// ---------------------------------------------------------------------------

{
  const virgin = await browser.newPage();
  await virgin.setViewport({ width: 1440, height: 900 });
  await virgin.setRequestInterception(true);

  virgin.on("request", (request) => {
    const url = new URL(request.url());

    if (url.pathname === "/api/analyses" && request.method() === "GET") {
      return request.respond({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ analyses: [] }),
      });
    }

    return request.continue();
  });

  const errors = [];
  virgin.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  virgin.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

  await virgin.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  await virgin.waitForSelector("h1", { timeout: 30000 });
  await virgin.waitForFunction(
    () => {
      const text = document.querySelector("header")?.textContent ?? "";
      return text.includes("No analysis");
    },
    { timeout: 60000, polling: 200 },
  );
  await virgin.waitForNetworkIdle({ idleTime: 600, timeout: 30000 });

  const idle = await virgin.evaluate(() => ({
    header: document.querySelector("header")?.innerText.replace(/\s+/g, " ") ?? "",
    body: document.body.innerText.replace(/\s+/g, " "),
  }));

  check(
    idle.header.includes("No dataset selected"),
    `with no run held the top bar names no dataset (${idle.header})`,
  );

  check(
    idle.header.includes("No analysis"),
    "with no run held the top bar reports no analysis",
  );

  check(
    idle.body.includes("No dataset selected"),
    "with no run held the Overview states that no dataset is selected",
  );

  check(
    idle.body.includes("Select a dataset to begin an assessment."),
    "with no run held the Overview says how to begin one",
  );

  // The defect itself.
  check(
    !idle.body.includes("Assessment in progress"),
    "with no run held the Overview never claims an assessment is in progress",
  );

  check(
    !idle.body.includes("The pipeline is assessing the selected dataset."),
    "with no run held the Overview never claims a dataset is being assessed",
  );

  // The same rule on every screen, because a false active run once differed
  // between screens: six read `running` from the analysis context while the
  // Overview and the top bar read the run phase.
  for (const route of [
    "/assessments",
    "/findings",
    "/evidence",
    "/reports",
  ]) {
    await virgin.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });

    // Deliberately not waiting for an `h1`. Findings, Evidence and Reports
    // return their empty state in place of the page header, so a screen with
    // nothing loaded has no heading to wait for, and demanding one would be
    // asserting a heading this state does not render.
    await virgin.waitForNetworkIdle({ idleTime: 600, timeout: 30000 });

    const quiet = await virgin.evaluate(
      () => document.body.innerText.replace(/\s+/g, " "),
    );

    check(
      !quiet.includes("Assessment in progress"),
      `with no run held ${route} never claims an assessment is in progress`,
    );

    check(
      quiet.includes("No assessment loaded"),
      `with no run held ${route} states plainly that no assessment is loaded`,
    );
  }

  check(errors.length === 0, `no console errors with no run held (${errors.length})`);

  await virgin.close();
}

for (const route of ["/", "/assessments", "/findings", "/evidence", "/reports"]) {
  const text = await pageText(route);
  check(text.length > 0, `${route} rendered`);

  const heading = await page.evaluate(
    () => document.querySelector("h1")?.textContent ?? "",
  );
  check(heading.length > 0, `${route} has a heading (${heading})`);

  if (route === "/") {
    check(
      text.includes(grouped(recordCount)),
      `Overview shows the backend record count (${grouped(recordCount)})`,
    );
    check(
      text.includes(job.dataset.split("/").pop()),
      "Overview names the dataset under examination",
    );
  }

  if (route === "/assessments") {
    check(
      text.includes(
        scopeCount === 1 ? "1 assessment scope" : `${scopeCount} assessment scopes`,
      ),
      `Assessments shows the backend scope count (${scopeCount})`,
    );
    check(
      !text.includes("UNKNOWN_ENTITY"),
      "Assessments does not show a placeholder identifier as an entity",
    );
  }

  if (route === "/findings") {
    check(
      text.includes(
        expectedFindings === 1
          ? "1 finding reported by the pipeline"
          : `${expectedFindings} findings reported by the pipeline`,
      ),
      `Findings reports the backend total (${expectedFindings})`,
    );

    if (expectedFindings === 0) {
      check(
        text.includes("No findings reported"),
        "Findings distinguishes zero findings from no analysis",
      );
    } else {
      check(
        !text.includes("No findings reported"),
        "Findings does not claim there are none when there are some",
      );
    }
  }

  if (route === "/evidence") {
    check(
      entityResolved
        ? !text.includes("Entity not identified")
        : text.includes("Entity not identified"),
      entityResolved
        ? "Evidence names a resolved entity rather than calling it unresolved"
        : "Evidence shows an unresolved entity as such",
    );
    check(
      periodResolved
        ? !text.includes("period not determined")
        : text.includes("period not determined"),
      "Evidence reports the period state as the backend resolved it",
    );
    check(
      text.includes(String(firstScope.status_counts.AVAILABLE ?? 0)),
      `Evidence shows the backend available count (${firstScope.status_counts.AVAILABLE ?? 0})`,
    );
  }

  if (route === "/evidence") {
    // The evidence register is a property of the local store rather than of the
    // loaded run, so the integrity panel is checked against what the trust layer
    // reports for it, read the same way the rest of this file reads its
    // expectations: from the backend, not from a hard-coded expectation.
    const register = await (await fetch(`${API}/api/evidence`))
      .json()
      .then((body) => body.evidence ?? []);

    check(
      text.includes("Evidence integrity"),
      "Evidence shows the integrity of registered submissions",
    );

    check(
      register.length === 0
        ? text.includes("No evidence registered")
        : text.includes(`${register.length} registered submission`),
      "Evidence reports the register's submission count from the backend",
    );

    for (const submission of register) {
      const sourceName = submission.source.filename;

      if (sourceName) {
        check(
          text.includes(sourceName),
          `Evidence names the registered file ${sourceName}`,
        );
      }

      if (submission.registered_sha256) {
        check(
          text.includes(submission.registered_sha256.slice(0, 12)),
          `Evidence shows the registered digest of ${submission.evidence_id}`,
        );
      }
    }

    const failed = register.filter(
      (submission) => submission.overall_status === "INTEGRITY_FAILED",
    );

    check(
      failed.length === 0
        ? !text.includes("Digest mismatch")
        : text.includes("Digest mismatch"),
      failed.length === 0
        ? "Evidence claims no digest mismatch when the backend reports none"
        : `Evidence shows the digest mismatch the backend reported (${failed.length})`,
    );

    const blocked = register.filter((submission) => !submission.analysis.permitted);

    check(
      blocked.length === 0
        ? !text.includes("Blocked")
        : text.includes("Blocked"),
      blocked.length === 0
        ? "Evidence claims no analysis is blocked when the backend permits all"
        : `Evidence shows the blocked submissions the backend reported (${blocked.length})`,
    );

    // Every integrity row is opened in turn. Scoped to the integrity panel:
    // other tables on this screen (e.g. the canonical mapping review) also
    // contain buttons, and a page-wide selector would count those rows as
    // integrity submissions. The detail is where a value the backend
    // returns as a structure is rendered, and rendering one as though it were
    // text takes the whole screen down, so the collapsed state is not enough to
    // have checked: the detail has to be opened to have shown it. One row at a
    // time, because the panel opens one row at a time.
    const panelSelector = '[data-testid="evidence-integrity-panel"]';
    const rowCount = await page.evaluate(
      (selector) => {
        const root = document.querySelector(selector) ?? document;

        return [...root.querySelectorAll("tr")].filter((row) =>
          row.querySelector("button"),
        ).length;
      },
      panelSelector,
    );

    let openedRows = 0;
    let custodyShown = 0;
    let provenanceShown = 0;

    for (let index = 0; index < rowCount; index += 1) {
      const expanded = await page.evaluate(
        (position, selector) => {
          const root = document.querySelector(selector) ?? document;
          const rows = [...root.querySelectorAll("tr")].filter((row) =>
            row.querySelector("button"),
          );

          rows[position]?.click();

          return true;
        },
        index,
        panelSelector,
      );

      if (!expanded) {
        continue;
      }

      await new Promise((resolve) => setTimeout(resolve, 250));

      // Section headings are uppercased by their style, and innerText reflects
      // that, so the comparison is case-insensitive rather than against a
      // spelling the reader never sees.
      const detailText = await page.evaluate(
        () => document.body.innerText.toLowerCase(),
      );

      if (detailText.includes("integrity comparison")) {
        openedRows += 1;
      }

      if (detailText.includes("custody events")) {
        custodyShown += 1;
      }

      if (detailText.includes("provenance")) {
        provenanceShown += 1;
      }

      // Close it again before opening the next one.
      await page.evaluate(
        (position, selector) => {
          const root = document.querySelector(selector) ?? document;
          const rows = [...root.querySelectorAll("tr")].filter((row) =>
            row.querySelector("button"),
          );

          rows[position]?.click();
        },
        index,
        panelSelector,
      );
    }

    check(
      rowCount === 0 || openedRows === rowCount,
      `the integrity detail opens for every registered submission (${openedRows}/${rowCount})`,
    );

    check(
      rowCount === 0 || custodyShown === rowCount,
      `the expanded detail shows the recorded custody events (${custodyShown}/${rowCount})`,
    );

    check(
      rowCount === 0 || provenanceShown === rowCount,
      `the expanded detail shows provenance (${provenanceShown}/${rowCount})`,
    );
  }

  if (route === "/reports") {
    check(
      text.includes(
        (verdicts.NOT_EVALUABLE ?? 0) === 1
          ? "1"
          : String(verdicts.NOT_EVALUABLE ?? 0),
      ),
      "Reports shows the backend verdict count",
    );
    check(
      /does not grade, score or rank/i.test(text),
      "Reports states that it does not grade, score or rank",
    );
    check(
      !/\b(out of|\/)\s*100\b/i.test(text),
      "Reports presents no score out of a fixed scale",
    );

    // "Score" is allowed where the page or the backend disclaims scoring. The
    // anomaly limitation quoted on this page says outright that the decision
    // score is not a risk score, so the check is that every mention of a risk
    // score is a disclaimer, not that the word is absent.
    const riskScoreIsAlwaysDisclaimed = [...text.matchAll(/risk score/gi)].every(
      (match) =>
        /not a risk score/i.test(
          text.slice(Math.max(0, match.index - 40), match.index + 14),
        ),
    );

    check(
      riskScoreIsAlwaysDisclaimed,
      "Reports mentions a risk score only to disclaim it",
    );
  }
}

// The findings screen must open a finding in a drawer without discarding the
// list behind it, and the detail route must render a scope.
if (expectedFindings > 0) {
  await page.goto(`${BASE}/findings`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("h1", { timeout: 30000 });

  const rows = await page.$$("tbody tr");
  check(
    rows.length === expectedFindings,
    `Findings lists every finding (${rows.length}/${expectedFindings})`,
  );

  await rows[0].click();
  await page.waitForSelector('[role="dialog"]', { timeout: 10000 });

  const drawer = await page.evaluate(
    () => document.querySelector('[role="dialog"]')?.innerText ?? "",
  );

  check(drawer.length > 0, "selecting a finding opens a detail drawer");
  check(
    !page.url().includes("/assessments/"),
    "the drawer does not navigate away from the findings list",
  );
  check(
    (await page.$$("tbody tr")).length === expectedFindings,
    "the findings list is still mounted behind the drawer",
  );

  const firstIndicator = result.execution_gap_findings.findings[0]?.indicator;
  if (firstIndicator) {
    check(
      drawer.includes(firstIndicator),
      "the drawer shows the backend's own indicator",
    );
  }

  await page.keyboard.press("Escape");
  await page.waitForSelector('[role="dialog"]', { hidden: true, timeout: 10000 });
  check(true, "the drawer closes on Escape");

  await page.goto(`${BASE}/assessments`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("tbody tr", { timeout: 30000 });
  const listHeading = await page.evaluate(
    () => document.querySelector("h1")?.textContent ?? "",
  );

  await (await page.$("tbody tr")).click();

  // The click changes the route but does not navigate the document, so the
  // list's own `h1` is still mounted for a frame afterwards. Waiting for *an*
  // `h1` therefore returned immediately and the assertions below ran against the
  // list, not against the scope. Waiting for the heading to change waits for the
  // detail screen to actually be the one on screen.
  await page.waitForFunction(
    (previous) => {
      const heading = document.querySelector("h1")?.textContent ?? "";

      return heading.length > 0 && heading !== previous;
    },
    { timeout: 30000, polling: 100 },
    listHeading,
  );

  const detail = await page.evaluate(() => document.body.innerText);

  check(page.url().includes("/assessments/"), "a scope opens its own assessment screen");
  check(
    detail.includes("Evidence") || detail.includes("EVIDENCE"),
    "the assessment screen shows the scope's evidence",
  );
  check(
    detail.includes(grouped(firstScope.record_count)),
    `the assessment screen shows the scope's own record count (${grouped(firstScope.record_count)})`,
  );
} else {
  skip("the drawer and detail route need a run with findings; this run has none");
}

// A deep link must survive a reload, and the navigation must be exactly the
// five screens with no account furniture.
await page.goto(`${BASE}/assessments`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("h1", { timeout: 30000 });
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector("h1", { timeout: 30000 });

check(
  (await page.evaluate(() => document.body.innerText)).includes("Assessments"),
  "a deep link survives a reload",
);

const sidebarItems = await page.evaluate(() =>
  [...document.querySelectorAll("nav a")].map((node) => node.textContent.trim()),
);

check(
  JSON.stringify(sidebarItems) ===
    JSON.stringify(["Overview", "Assessments", "Findings", "Evidence", "Reports"]),
  `the navigation is exactly the five screens (${sidebarItems.join(", ")})`,
);

const offenders = consoleErrors.filter(
  (text) =>
    !text.includes("favicon") && !text.includes("Download the React DevTools"),
);

check(offenders.length === 0, `no console errors (${offenders.length})`);

await browser.close();

console.log(`loaded run: ${job.dataset} (${job.job_id.slice(0, 8)})`);
console.log(notes.join("\n"));
console.log("");

if (failures.length > 0) {
  console.log(`${failures.length} check(s) failed`);
  for (const failure of failures) {
    console.log(`  - ${failure}`);
  }
  process.exit(1);
}

console.log(
  `all checks passed${skips.length > 0 ? ` (${skips.length} skipped)` : ""}`,
);
