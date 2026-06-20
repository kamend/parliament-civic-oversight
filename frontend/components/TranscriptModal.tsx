"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  getTranscript,
  type Source,
  type Transcript,
  type TranscriptTurn,
} from "@/lib/api";

/**
 * A full-screen reading view of the whole plenary sitting a citation came from.
 *
 * Opened from a {@link SourceCard}; it fetches the parsed transcript, renders it
 * as formatted speaker turns, then scrolls to and flags the cited turn — and,
 * within it, the exact stretch of text the source quoted. Closing it (Esc, the
 * backdrop, or the ✕) just unmounts the overlay, so the page underneath is left
 * exactly where it was.
 */
export function TranscriptModal({
  source,
  onClose,
}: {
  source: Source;
  onClose: () => void;
}) {
  const [data, setData] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLElement>(null);
  // The element that had focus before we opened, so we can hand it back on close.
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  // No transcript id means nothing to fetch — derived, not stored, so the
  // effect below never has to set state synchronously.
  const noTranscript = !source.transcript_id;

  // Fetch the transcript for this citation.
  useEffect(() => {
    if (!source.transcript_id) return;
    const ac = new AbortController();
    getTranscript(source.transcript_id, ac.signal)
      .then(setData)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError("Стенограмата не може да бъде заредена.");
      });
    return () => ac.abort();
  }, [source.transcript_id]);

  // Esc to close + lock the page scroll behind the overlay while it's open.
  useEffect(() => {
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      restoreFocusRef.current?.focus?.();
    };
  }, [onClose]);

  // Once the turns are on screen, bring the cited one into view and flag it.
  useEffect(() => {
    if (!data) return;
    const el = targetRef.current;
    if (!el) return;
    // rAF so the scroll runs after layout settles.
    const id = requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => cancelAnimationFrame(id);
  }, [data]);

  const stop = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col bg-ink/55 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Пълна стенограма"
      onClick={onClose}
    >
      {/* The sheet */}
      <div
        className="mx-auto flex h-full w-full max-w-[920px] flex-col bg-paper shadow-2xl"
        onClick={stop}
      >
        <ModalHeader source={source} data={data} onClose={onClose} />

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[760px] px-4 py-8 sm:px-10">
            {(error || noTranscript) && (
              <p className="border-l-2 border-crimson bg-crimson/5 px-4 py-3 font-sans text-[0.9rem] text-crimson-deep">
                {error ?? "Тази реплика няма свързана стенограма."}
              </p>
            )}

            {!error && !noTranscript && !data && <TranscriptSkeleton />}

            {data &&
              data.turns.map((turn) => (
                <TurnBlock
                  key={turn.index}
                  turn={turn}
                  cited={turn.index === source.turn_index}
                  quote={turn.index === source.turn_index ? source.text : null}
                  innerRef={turn.index === source.turn_index ? targetRef : undefined}
                />
              ))}

            {data && data.turns.length === 0 && (
              <p className="font-display italic text-ink-soft">
                Стенограмата не съдържа разпознати реплики.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** Sticky header: sitting title + date, a jump-back-to-citation control, ✕. */
function ModalHeader({
  source,
  data,
  onClose,
}: {
  source: Source;
  data: Transcript | null;
  onClose: () => void;
}) {
  const jumpToCitation = () => {
    const el = document.getElementById(`turn-${source.turn_index}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <header className="flex items-start gap-4 border-b border-line bg-surface px-4 py-4 sm:px-10">
      <div className="min-w-0 flex-1">
        <p className="eyebrow">Стенограма · {data?.date ?? source.date ?? "—"}</p>
        <h2 className="mt-1 truncate font-display text-[1.15rem] font-semibold leading-snug text-ink">
          {data?.sitting ?? data?.header ?? "Пленарно заседание"}
        </h2>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <button
          onClick={jumpToCitation}
          disabled={!data}
          className="hidden items-center gap-1.5 border border-line-strong bg-surface px-3 py-1.5 font-mono text-[0.64rem] uppercase tracking-wider text-crimson transition-colors hover:border-crimson hover:bg-surface-2 disabled:opacity-40 sm:inline-flex"
          title="Към цитираната реплика"
        >
          <span className="font-mono text-[0.62rem] font-semibold text-surface bg-crimson px-1 py-0.5 rounded-[2px] leading-none">
            S{source.n}
          </span>
          към цитата
        </button>
        <button
          onClick={onClose}
          aria-label="Затвори"
          className="flex h-9 w-9 items-center justify-center border border-line-strong bg-surface text-ink-soft transition-colors hover:border-crimson hover:bg-crimson hover:text-surface"
        >
          <span className="text-lg leading-none">✕</span>
        </button>
      </div>
    </header>
  );
}

/** One speaker turn. The cited turn gets a crimson rail + a flagged wash, and
 * the quoted stretch within it is wrapped in a `<mark>`. */
function TurnBlock({
  turn,
  cited,
  quote,
  innerRef,
}: {
  turn: TranscriptTurn;
  cited: boolean;
  quote: string | null;
  innerRef?: React.Ref<HTMLElement>;
}) {
  const meta = [turn.party, turn.modifier].filter(Boolean) as string[];

  return (
    <article
      id={`turn-${turn.index}`}
      ref={innerRef}
      className={`scroll-mt-24 py-3.5 transition-colors ${
        cited ? "-mx-4 rounded-sm border-l-[3px] border-crimson bg-crimson/[0.06] px-4" : ""
      }`}
    >
      <header className="flex items-baseline gap-2">
        <h3 className="font-display text-[1rem] font-semibold leading-snug text-ink">
          {turn.speaker || turn.speaker_raw || "Неизвестен говорител"}
        </h3>
        {turn.role && (
          <span className="font-mono text-[0.6rem] uppercase tracking-wider text-ink-faint">
            {turn.role.toLowerCase()}
          </span>
        )}
        {meta.length > 0 && (
          <span className="font-mono text-[0.62rem] text-ink-soft">
            {meta.join(" · ")}
          </span>
        )}
      </header>

      <div className="mt-2 flex flex-col gap-2.5 font-display text-[1.02rem] leading-[1.72] text-ink/90">
        {renderParagraphs(turn.text, quote)}
      </div>
    </article>
  );
}

/**
 * Render a turn's text as spaced paragraphs. The source text breaks every
 * utterance onto its own line with single `\n`s, which reads as a tight wall;
 * we split on those newlines and render each as its own `<p>` so the speech
 * breathes.
 *
 * When a `quote` is supplied (the cited turn) we wrap the matching stretch in a
 * `<mark>`. The quote can span several lines, so we resolve its character range
 * against the full text once, then mark only the part that falls inside each
 * paragraph. Whole-turn chunks match exactly; windowed sub-chunks (which carry a
 * little overlap) may not — then we leave the turn un-marked rather than
 * highlight the wrong span. The turn's crimson rail still marks where it came from.
 */
function renderParagraphs(text: string, quote: string | null) {
  const q = quote?.trim();
  const at = q ? text.indexOf(q) : -1;
  const range: [number, number] | null = at >= 0 ? [at, at + q!.length] : null;

  const paragraphs: { text: string; start: number }[] = [];
  let offset = 0;
  for (const line of text.split("\n")) {
    paragraphs.push({ text: line, start: offset });
    offset += line.length + 1; // +1 for the consumed "\n"
  }

  return paragraphs
    .filter((p) => p.text.trim() !== "")
    .map((p, i) => (
      <p key={i}>{renderParagraph(p.text, p.start, range)}</p>
    ));
}

/** Wrap the slice of a single paragraph that overlaps the highlight `range`. */
function renderParagraph(
  text: string,
  start: number,
  range: [number, number] | null,
) {
  const end = start + text.length;
  if (!range || range[0] >= end || range[1] <= start) return text;

  const a = Math.max(range[0], start) - start;
  const b = Math.min(range[1], end) - start;
  return (
    <>
      {text.slice(0, a)}
      <mark className="rounded-[2px] bg-amber/25 px-0.5 text-ink decoration-clone">
        {text.slice(a, b)}
      </mark>
      {text.slice(b)}
    </>
  );
}

function TranscriptSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="h-3.5 w-40 animate-pulse bg-surface-2" />
          <div className="h-16 animate-pulse bg-surface-2" style={{ animationDelay: `${i * 90}ms` }} />
        </div>
      ))}
    </div>
  );
}
