"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getSittings, type Sitting } from "@/lib/api";
import { Masthead } from "@/components/Masthead";
import { Footer } from "@/components/Footer";

/** "2026-05" → "май 2026" (Bulgarian month + year). */
function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("bg-BG", {
    month: "long",
    year: "numeric",
  });
}

/** "2026-05-22" → "22 май 2026". */
function dateLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("bg-BG", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** "2026-05-22" → "петък" (weekday). */
function weekdayLabel(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("bg-BG", { weekday: "long" });
}

export default function SittingsPage() {
  const [sittings, setSittings] = useState<Sitting[] | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState<string>(""); // "" = all months
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    getSittings(ac.signal)
      .then((r) => {
        setSittings(r.sittings);
        setMonths(r.months);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError("Заседанията не могат да бъдат заредени.");
      });
    return () => ac.abort();
  }, []);

  const visible = useMemo(
    () => (sittings ?? []).filter((s) => !month || s.month === month),
    [sittings, month],
  );

  return (
    <div className="relative z-10 flex flex-1 flex-col">
      <Masthead
        current="sittings"
        dateRange={
          months.length
            ? { min: months[months.length - 1], max: months[0] }
            : undefined
        }
      />

      <main className="mx-auto w-full max-w-[1100px] flex-1 px-4 py-8 sm:px-6">
        <div className="mb-6 border-b border-line pb-4">
          <p className="eyebrow mb-2">Архив на пленарните заседания</p>
          <h2 className="font-display text-[1.5rem] leading-tight font-bold text-ink sm:text-[2rem]">
            Всички заседания.{" "}
            <span className="italic text-ink-soft">
              Прегледайте стенограмите в пълен вид.
            </span>
          </h2>
        </div>

        {/* Month filter */}
        {months.length > 0 && (
          <label className="mb-7 flex w-full flex-col gap-1 sm:w-fit">
            <span className="eyebrow">Месец</span>
            <select
              className="field w-full cursor-pointer sm:w-auto"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            >
              <option value="">Всички месеци</option>
              {months.map((m) => (
                <option key={m} value={m}>
                  {monthLabel(m)}
                </option>
              ))}
            </select>
          </label>
        )}

        {error && (
          <div className="border-l-2 border-crimson bg-crimson/5 px-4 py-3 font-sans text-[0.9rem] text-crimson-deep">
            {error}
          </div>
        )}

        {!error && sittings === null && <ListSkeleton />}

        {sittings !== null && visible.length === 0 && !error && (
          <p className="font-display italic text-ink-soft">
            Няма заседания за избрания месец.
          </p>
        )}

        {visible.length > 0 && (
          <>
            <p className="mb-3 font-mono text-[0.64rem] text-ink-faint tabular-nums">
              {visible.length.toLocaleString("bg-BG")}{" "}
              {visible.length === 1 ? "заседание" : "заседания"}
            </p>
            <ul className="flex flex-col divide-y divide-line border-y border-line">
              {visible.map((s) => (
                <SittingRow key={s.id} sitting={s} />
              ))}
            </ul>
          </>
        )}
      </main>

      <Footer>Пълни стенограми от пленарните заседания на Народното събрание</Footer>
    </div>
  );
}

function SittingRow({ sitting }: { sitting: Sitting }) {
  const pending = !sitting.has_transcript;
  return (
    <li>
      <Link
        href={`/sittings/${sitting.id}`}
        className="group flex items-baseline gap-4 px-1 py-4 transition-colors hover:bg-surface/60 sm:gap-5"
      >
        <div className="w-[6.5rem] shrink-0 sm:w-[7.5rem]">
          <div
            className={`font-mono text-[0.82rem] font-semibold tabular-nums ${
              pending ? "text-ink-faint" : "text-crimson"
            }`}
          >
            {dateLabel(sitting.date)}
          </div>
          <div className="font-mono text-[0.62rem] uppercase tracking-wider text-ink-faint">
            {weekdayLabel(sitting.date)}
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <p
            className={`font-display text-[1.05rem] leading-snug ${
              pending ? "italic text-ink-soft" : "text-ink"
            }`}
          >
            {sitting.title ?? "Пленарно заседание"}
          </p>
          {pending && (
            <span className="mt-1 inline-flex items-center gap-1.5 border border-amber/40 bg-amber/10 px-2 py-0.5 font-mono text-[0.6rem] uppercase tracking-wider text-amber">
              Очаква се стенограма
            </span>
          )}
        </div>
        <span className="shrink-0 self-center font-mono text-crimson opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100">
          →
        </span>
      </Link>
    </li>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col divide-y divide-line border-y border-line">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="flex items-center gap-5 px-1 py-4">
          <div className="h-8 w-[7.5rem] shrink-0 animate-pulse bg-surface-2" />
          <div
            className="h-5 flex-1 animate-pulse bg-surface-2"
            style={{ animationDelay: `${i * 80}ms` }}
          />
        </div>
      ))}
    </div>
  );
}
