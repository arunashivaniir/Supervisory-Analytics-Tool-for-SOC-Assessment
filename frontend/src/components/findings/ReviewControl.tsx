import { useState } from "react";

import {
  reviewLabel,
  REVIEW_VERDICTS,
  type FindingReview,
  type ReviewVerdict,
} from "../../app/reviews";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";

/**
 * The examiner's verdict on one finding.
 *
 * Read-only badge when there is no review yet; the control below it records
 * one. Review metadata lives in browser storage, never in the evidence, so
 * this component cannot alter what the pipeline reported.
 */

const TONE: Record<ReviewVerdict, string> = {
  confirmed_gap: "text-critical",
  false_positive: "text-text-tertiary",
  needs_review: "text-caution",
};

export function ReviewBadge({ review }: { review: FindingReview | null }) {
  if (!review) {
    return (
      <span className="text-text-tertiary italic">Not reviewed</span>
    );
  }

  return (
    <span className={cn("text-xs font-medium", TONE[review.verdict])}>
      {reviewLabel(review.verdict)}
    </span>
  );
}

export function ReviewControl({
  findingKey,
  review,
  onSave,
  onClear,
}: {
  findingKey: string;
  review: FindingReview | null;
  onSave: (findingKey: string, verdict: ReviewVerdict, note: string) => void;
  onClear: (findingKey: string) => void;
}) {
  const [verdict, setVerdict] = useState<ReviewVerdict>(
    review?.verdict ?? "needs_review",
  );
  const [note, setNote] = useState(review?.note ?? "");
  const [saved, setSaved] = useState(false);

  return (
    <div className="rounded-[8px] border border-border bg-subtle/50 px-3 py-2.5">
      <div className="section-label">Examiner review</div>

      <div
        className="mt-2 flex flex-wrap gap-1.5"
        role="radiogroup"
        aria-label="Review verdict"
      >
        {REVIEW_VERDICTS.map((option) => (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={verdict === option.id}
            onClick={() => {
              setVerdict(option.id);
              setSaved(false);
            }}
            className={cn(
              "rounded-[6px] border px-2 py-1 text-xs font-medium transition-colors duration-75",
              verdict === option.id
                ? "border-accent bg-accent-subtle text-accent"
                : "border-border bg-surface text-text-secondary hover:text-text",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <label className="mt-2 block">
        <span className="micro text-text-tertiary">Note (optional)</span>
        <textarea
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
            setSaved(false);
          }}
          rows={2}
          maxLength={2000}
          placeholder="What did you conclude, and on what basis?"
          className="mt-1 w-full rounded-[6px] border border-border bg-surface px-2 py-1.5 text-xs text-text placeholder:text-text-tertiary focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </label>

      <div className="mt-2 flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            onSave(findingKey, verdict, note.trim());
            setSaved(true);
          }}
        >
          Save review
        </Button>
        {review ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              onClear(findingKey);
              setSaved(false);
            }}
          >
            Clear
          </Button>
        ) : null}
        {saved ? (
          <span className="text-xs text-positive" role="status">
            Saved
          </span>
        ) : null}
      </div>

      <p className="mt-2 micro leading-relaxed text-text-tertiary">
        Reviews are examiner metadata kept in this browser. They do not modify
        the submitted evidence.
      </p>
    </div>
  );
}
