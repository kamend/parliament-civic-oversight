"use client";

import type { Source } from "@/lib/api";
import { SourceCard } from "./SourceCard";

/**
 * The apparatus column: the reranked turns the answer is grounded on. Sticky
 * heading with a count; empty until a question is asked.
 */
export function SourcesPanel({
  sources,
  loading,
}: {
  sources: Source[];
  loading: boolean;
}) {
  return (
    <aside className="flex flex-col">
      <div className="flex items-baseline justify-between border-b border-line pb-2">
        <h2 className="eyebrow">Източници</h2>
        {sources.length > 0 && (
          <span className="font-mono text-[0.64rem] text-ink-faint tabular-nums">
            {sources.length} {sources.length === 1 ? "запис" : "записа"}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-col gap-3">
        {sources.length === 0 && loading && (
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-28 animate-pulse border border-line bg-surface/60"
                style={{ animationDelay: `${i * 120}ms` }}
              />
            ))}
          </div>
        )}

        {sources.length === 0 && !loading && (
          <p className="font-display italic text-[0.95rem] leading-relaxed text-ink-soft pt-2">
            Източниците, върху които стъпва отговорът, ще се появят тук — всеки с
            говорител, партия и дата. Маркерите{" "}
            <span className="cite-chip">S#</span> в текста сочат към тях.
          </p>
        )}

        {sources.map((s) => (
          <SourceCard key={s.id} source={s} />
        ))}
      </div>
    </aside>
  );
}
