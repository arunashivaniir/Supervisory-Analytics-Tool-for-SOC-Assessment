import { useEffect, useState } from "react";

import { fetchEvidenceIntegrity } from "./api";
import type { EvidenceIntegrity } from "../types/evidence";

/**
 * The evidence register, for screens that only need its summary.
 *
 * A failure to read the register never blocks the screen: the caller gets
 * `items: null` and renders the integrity state as not available, rather
 * than the screen failing because an adjacent register could not be read.
 */
export function useEvidenceRegister() {
  const [items, setItems] = useState<EvidenceIntegrity[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetchEvidenceIntegrity()
      .then((registered) => {
        if (!cancelled) {
          setItems(registered);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setItems(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { items };
}

/**
 * The register entry for the dataset on screen, matched by filename.
 *
 * Null when nothing registered matches: the dataset may predate the
 * register or have been placed in the workspace directly, and the interface
 * says so instead of attributing another submission's digest to it.
 */
export function entryForDataset(
  items: EvidenceIntegrity[] | null,
  dataset: string,
): EvidenceIntegrity | null {
  if (!items) {
    return null;
  }

  const filename = dataset.split("/").pop() ?? dataset;

  return (
    items.find((item) => item.source.filename === filename) ?? null
  );
}

/** First eight hex characters of a digest, for dense status strips. */
export function shortHash(digest: string | null): string {
  if (!digest) {
    return "Not registered";
  }

  return digest.slice(0, 8);
}

/**
 * A run timestamp as `YYYY-MM-DD HH:MM`, in the backend's own timezone.
 *
 * The adapter records ISO-8601 instants. Slicing the date and the
 * hour-minute is formatting, not conversion: no timezone is applied and
 * none is implied.
 */
export function formatRunTime(instant: string | null | undefined): string {
  if (!instant) {
    return "Not recorded";
  }

  const date = instant.slice(0, 10);
  const time = instant.slice(11, 16);

  if (!date) {
    return "Not recorded";
  }

  return time ? `${date} ${time}` : date;
}
