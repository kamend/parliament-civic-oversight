"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Footer } from "@/components/Footer";
import {
  getTranscript,
  type Transcript,
  type TranscriptTurn,
} from "@/lib/api";

/** "2026-05-22" → "22 май 2026". */
function dateLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  if (!y || !m || !d) return date;
  return new Date(y, m - 1, d).toLocaleDateString("bg-BG", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/**
 * Full-page reading view of one plenary sitting: the whole transcript laid out
 * as formatted speaker turns. Unlike {@link TranscriptModal}, there's no cited
 * turn to flag — this is plain browsing reached from the sittings archive.
 */
export function SittingReader({ id }: { id: string }) {
  const [data, setData] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getTranscript(id, ac.signal)
      .then(setData)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError("Стенограмата не може да бъде заредена.");
      });
    return () => ac.abort();
  }, [id]);

  return (
    <div className="relative z-10 flex flex-1 flex-col">
      {/* Sticky reading header with a route back to the archive. */}
      <header className="sticky top-0 z-20 border-b border-line-strong bg-paper/85 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[860px] items-start gap-4 px-4 py-4 sm:px-6">
          <Link
            href="/sittings"
            className="mt-1 flex shrink-0 items-center gap-1.5 font-mono text-[0.66rem] uppercase tracking-wider text-ink-soft transition-colors hover:text-crimson"
          >
            <span className="text-crimson">←</span> Архив
          </Link>
          <div className="min-w-0 flex-1">
            <p className="eyebrow">
              Стенограма · {data ? dateLabel(data.date) : "—"}
            </p>
            <h1 className="mt-1 font-display text-[1.2rem] font-semibold leading-snug text-ink">
              {data?.sitting ?? data?.header ?? "Пленарно заседание"}
            </h1>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[760px] flex-1 px-4 py-8 sm:px-10">
        {error && (
          <p className="border-l-2 border-crimson bg-crimson/5 px-4 py-3 font-sans text-[0.9rem] text-crimson-deep">
            {error}
          </p>
        )}

        {!error && !data && <ReaderSkeleton />}

        {/* Protocol not published yet — the sitting exists but has no transcript. */}
        {data && !data.has_transcript && <PendingNotice date={data.date} />}

        {data &&
          data.has_transcript &&
          data.turns.map((turn) => <TurnBlock key={turn.index} turn={turn} />)}
      </main>

      <Footer>
        <Link href="/sittings" className="transition-colors hover:text-crimson">
          ← Към всички заседания
        </Link>
      </Footer>
    </div>
  );
}

/** Shown when a sitting exists but its stenographic protocol isn't published yet. */
function PendingNotice({ date }: { date: string }) {
  return (
    <div className="mt-2 border border-amber/40 bg-amber/[0.07] px-6 py-8 text-center">
      <p className="font-mono text-[0.62rem] uppercase tracking-[0.18em] text-amber">
        Очаква се стенограма
      </p>
      <h2 className="mt-3 font-display text-[1.4rem] font-semibold leading-snug text-ink">
        Стенограмата още не е публикувана.
      </h2>
      <p className="mx-auto mt-3 max-w-[44ch] font-sans text-[0.92rem] leading-relaxed text-ink-soft">
        Заседанието от {dateLabel(date)} се е провело, но стенографският протокол
        все още не е качен. По правилника на Народното събрание протоколите се
        публикуват в срок до 7 дни след заседанието — върнете се по-късно.
      </p>
    </div>
  );
}

/** One speaker turn, rendered for plain reading (no citation rail). */
function TurnBlock({ turn }: { turn: TranscriptTurn }) {
  const meta = [turn.party, turn.modifier].filter(Boolean) as string[];

  return (
    <article id={`turn-${turn.index}`} className="scroll-mt-24 py-3.5">
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

      <div className="mt-1.5 whitespace-pre-wrap font-display text-[1.02rem] leading-relaxed text-ink/90">
        {turn.text}
      </div>
    </article>
  );
}

function ReaderSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="flex flex-col gap-2">
          <div className="h-3.5 w-40 animate-pulse bg-surface-2" />
          <div
            className="h-16 animate-pulse bg-surface-2"
            style={{ animationDelay: `${i * 90}ms` }}
          />
        </div>
      ))}
    </div>
  );
}
