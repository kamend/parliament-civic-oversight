"use client";

import { memo, useState } from "react";
import type { Source } from "@/lib/api";
import { TranscriptModal } from "./TranscriptModal";

/**
 * One retrieved turn, rendered as a record card in the right-hand apparatus.
 * Its `id` ("source-N") is the anchor the inline `[S#]` chips scroll to and
 * flag. Long turns clamp with a "разгърни" (expand) toggle.
 *
 * Memoized: during answer streaming the parent re-renders on every token, but
 * each `source` object keeps a stable identity (set once, never mutated), so
 * the shallow prop compare skips these cards instead of re-rendering all ~10.
 */
function SourceCardImpl({ source }: { source: Source }) {
  const [open, setOpen] = useState(false);
  const [viewing, setViewing] = useState(false);
  const long = source.text.length > 420;

  const meta = [
    source.party,
    source.role,
    source.date,
    source.sitting ? `заседание ${source.sitting}` : null,
  ].filter(Boolean) as string[];

  return (
    <article
      id={`source-${source.n}`}
      className="rise scroll-mt-28 border border-line bg-surface px-4 py-3.5 transition-colors"
      style={{ animationDelay: `${Math.min(source.n - 1, 8) * 55}ms` }}
    >
      <header className="flex items-baseline gap-3">
        <span className="font-mono text-[0.7rem] font-semibold leading-none text-surface bg-crimson px-1.5 py-1 rounded-[3px]">
          S{source.n}
        </span>
        <h3 className="font-display text-[1.06rem] font-semibold leading-snug text-ink flex-1">
          {source.speaker || source.speaker_raw || "Неизвестен говорител"}
        </h3>
      </header>

      <p
        className={`mt-2.5 font-display text-[0.95rem] leading-relaxed text-ink/90 ${
          long && !open ? "line-clamp-4" : ""
        }`}
      >
        {source.text}
      </p>

      <div className="mt-2 flex items-center gap-3">
        {long && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex cursor-pointer items-center gap-1 font-mono text-[0.66rem] uppercase tracking-wider text-crimson transition-colors hover:text-crimson-deep"
          >
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`h-3 w-3 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
            {open ? "свий" : "разгърни"}
          </button>
        )}
        {source.transcript_id && (
          <button
            type="button"
            onClick={() => setViewing(true)}
            className="group/btn ml-auto inline-flex cursor-pointer items-center gap-1.5 rounded-[3px] px-2 py-1 font-mono text-[0.66rem] uppercase tracking-wider text-ink-soft underline decoration-line decoration-dotted underline-offset-4 transition-colors hover:bg-crimson/10 hover:text-crimson hover:decoration-crimson"
            title="Отвори пълната стенограма и виж откъде идва репликата"
          >
            Към Пълната Стенограма
          </button>
        )}
      </div>

      {viewing && (
        <TranscriptModal source={source} onClose={() => setViewing(false)} />
      )}
    </article>
  );
}

export const SourceCard = memo(SourceCardImpl);
