"""Deterministic scale fixtures for SAT-SA Phase 2.

Generates flat Pipeline 1 + Pipeline 2 CSVs (alert rows, case rows and
workflow-event rows in one file, sparse columns) with known ground
truth written to a sibling manifest. Seeded: the same size always
produces the same bytes, so benchmarks and tests compare against fixed
expectations.

Row mix per file: ~50% alerts, ~30% cases, ~20% workflow events.
Built-in data-quality texture: orphan cases (~2% of cases), unmatched
alerts (~40% of alerts have no case), impossible chronology (~0.5% of
cases), unknown severities (~0.5% of alerts), duplicate alert rows
(~0.1%, exact copies).

Usage::

    python framework/tests/scale/make_fixtures.py --rows 100000 --out data/scale
    python framework/tests/scale/make_fixtures.py --rows 1000000 --out data/scale
    python framework/tests/scale/make_fixtures.py --rows 5000000 --out data/scale   # slow

Output is gitignored (data/scale/). Never commit generated fixtures.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from datetime import datetime, timedelta, timezone

HEADER = [
    "alert_id", "event_id", "triggered_at", "alert_name", "category",
    "severity", "asset_id", "asset_type", "network_zone", "source_system",
    "case_id", "case_alert", "acknowledged_at", "closed_at", "analyst_id",
    "escalation_status", "closure_disposition", "investigation_notes",
    "event_case", "event_type", "event_at", "actor", "tier",
]

ALERT_NAMES = [
    "Impossible travel", "Mass download", "Privilege escalation",
    "C2 beaconing", "Phishing delivery", "Lateral movement",
    "Data staging", "Persistence install",
]
CATEGORIES = ["exfiltration", "intrusion", "malware", "phishing", "misuse"]
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
SEV_WEIGHTS = [5, 20, 45, 30]
ASSET_TYPES = ["server", "workstation", "database", "firewall"]
ZONES = ["dmz", "core", "branch", "cloud"]
SOURCES = ["siem-main", "siem-dr", "edr-cloud"]
ANALYSTS = ["A-%02d" % index for index in range(1, 26)]
DISPOSITIONS = ["closed", "false_positive", "duplicate", "open"]
NOTES = [
    "Root cause identified, host reimaged.",
    "Confirmed benign admin activity.",
    "Containment applied, awaiting closure.",
    "Corroborated with firewall logs.",
    "Escalated to incident response.",
]
EVENT_TYPES = ["acknowledged", "escalated", "note_added", "closed"]

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def generate(path: str, total_rows: int, seed: int = 20260928) -> dict:
    """Write the fixture and return its ground-truth manifest."""

    rng = random.Random(seed)
    counts = {
        "rows": 0, "alerts": 0, "cases": 0, "workflow_events": 0,
        "linked_cases": 0, "orphan_cases": 0, "alerts_without_case": 0,
    }
    alert_ids: list = []
    case_ids: list = []
    linked_alerts: set = set()
    orphan_case_ids: list = []
    manifest_extra = {"seed": seed}

    n_alerts = total_rows // 2
    n_cases = total_rows * 3 // 10
    n_events = total_rows - n_alerts - n_cases

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)

        # -- alert rows -------------------------------------------------
        for index in range(1, n_alerts + 1):
            alert_id = "A-%07d" % index
            alert_ids.append(alert_id)
            triggered = BASE + timedelta(
                seconds=rng.randrange(0, 90 * 86400)
            )
            severity = rng.choices(SEVERITIES, SEV_WEIGHTS)[0]

            if rng.random() < 0.005:
                severity = "URGENT"

            asset = rng.randrange(1, 201)
            writer.writerow([
                alert_id,
                "E-%07d" % index,
                _iso(triggered),
                rng.choice(ALERT_NAMES),
                rng.choice(CATEGORIES),
                severity,
                "HOST-%03d" % asset,
                rng.choice(ASSET_TYPES),
                rng.choice(ZONES),
                rng.choice(SOURCES),
            ] + [""] * 13)
            counts["alerts"] += 1

        # -- case rows --------------------------------------------------
        n_linked = int(n_cases * 0.60)
        n_orphan = max(1, int(n_cases * 0.02))

        for index in range(1, n_cases + 1):
            case_id = "C-%07d" % index
            case_ids.append(case_id)

            if index <= n_linked:
                target = rng.choice(alert_ids)
                linked_alerts.add(target)
                counts["linked_cases"] += 1
            elif index <= n_linked + n_orphan:
                target = "A-9999999"
                orphan_case_ids.append(case_id)
                counts["orphan_cases"] += 1
            else:
                target = ""

            ack = BASE + timedelta(seconds=rng.randrange(0, 90 * 86400))
            closed = ack + timedelta(seconds=rng.randrange(3600, 72 * 3600))

            if rng.random() < 0.005:
                ack, closed = closed, ack

            writer.writerow(
                [""] * 10
                + [
                    case_id,
                    target,
                    _iso(ack),
                    _iso(closed),
                    rng.choice(ANALYSTS),
                    rng.choice(["escalated", "not_escalated"]),
                    rng.choice(DISPOSITIONS),
                    rng.choice(NOTES),
                ]
                + [""] * 5
            )
            counts["cases"] += 1

        # -- workflow event rows ----------------------------------------
        event_cases = case_ids[: max(1, len(case_ids) // 2)]

        for index in range(n_events):
            case_id = rng.choice(event_cases)
            at = BASE + timedelta(seconds=rng.randrange(0, 90 * 86400))
            writer.writerow(
                [""] * 18
                + [
                    case_id,
                    rng.choice(EVENT_TYPES),
                    _iso(at),
                    rng.choice(ANALYSTS),
                    rng.choice(["L1", "L2", "L3"]),
                ]
            )
            counts["workflow_events"] += 1

        # -- exact duplicate alert rows ---------------------------------
        n_dupes = max(1, total_rows // 1000)
        writer.writerow([
            alert_ids[0], "E-0000001", _iso(BASE), ALERT_NAMES[0],
            CATEGORIES[0], "HIGH", "HOST-001", ASSET_TYPES[0], ZONES[0],
            SOURCES[0],
        ] + [""] * 13)

        for _ in range(n_dupes - 1):
            writer.writerow([
                alert_ids[0], "E-0000001", _iso(BASE), ALERT_NAMES[0],
                CATEGORIES[0], "HIGH", "HOST-001", ASSET_TYPES[0],
                ZONES[0], SOURCES[0],
            ] + [""] * 13)

    counts["rows"] = n_alerts + n_cases + n_events + n_dupes
    counts["alerts_without_case"] = len(set(alert_ids) - linked_alerts)
    counts["orphan_case_ids"] = orphan_case_ids[:5]
    manifest_extra.update(counts)

    manifest_path = os.path.splitext(path)[0] + ".manifest.json"

    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest_extra, handle, indent=2, sort_keys=True)

    return manifest_extra


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--out", default="data/scale")
    parser.add_argument("--seed", type=int, default=20260928)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    name = "scale_%d.csv" % args.rows
    path = os.path.join(args.out, name)

    if args.rows >= 1000000:
        print("Generating %d rows (slow, be patient) ..." % args.rows)

    manifest = generate(path, args.rows, seed=args.seed)
    size = os.path.getsize(path)
    print("wrote %s (%d bytes)" % (path, size))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
