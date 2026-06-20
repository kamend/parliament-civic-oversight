"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const MONTHS = [
  "януари", "февруари", "март", "април", "май", "юни",
  "юли", "август", "септември", "октомври", "ноември", "декември",
];
// Bulgarian week starts on Monday.
const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"];

/** Zero-padded 'YYYY-MM-DD' from 1-based month/day. */
function iso(y: number, m: number, d: number): string {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function parseIso(s: string): { y: number; m: number; d: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
}

function daysInMonth(y: number, m: number): number {
  return new Date(y, m, 0).getDate(); // m is 1-based; day 0 of next month
}

/** Monday-first weekday index (0=Mon … 6=Sun) of the month's first day. */
function firstWeekday(y: number, m: number): number {
  return (new Date(y, m - 1, 1).getDay() + 6) % 7;
}

/** A month string "YYYY-MM" for cheap month-level comparisons. */
function monthKey(y: number, m: number): string {
  return `${y}-${String(m).padStart(2, "0")}`;
}

/**
 * A custom date picker bounded to the corpus, that marks which days actually had
 * a sitting. Days outside [min, max] aren't selectable; in-range days are always
 * selectable but a day with a sitting is rendered in crimson with a dot, so a
 * wider range can still be chosen while seeing where the record exists.
 */
export function DatePicker({
  value,
  onChange,
  min,
  max,
  sittingDates,
  disabled,
  placeholder = "избери дата",
  align = "left",
}: {
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  sittingDates: Set<string>;
  disabled?: boolean;
  placeholder?: string;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // The month currently shown in the grid. Defaults to the selected value, else
  // the max bound (newest sittings), else today.
  const initial = parseIso(value) ?? parseIso(max ?? "") ?? null;
  const [view, setView] = useState<{ y: number; m: number }>(() => {
    if (initial) return { y: initial.y, m: initial.m };
    const now = new Date();
    return { y: now.getFullYear(), m: now.getMonth() + 1 };
  });

  // Open the popover, re-centred on the selected value / max bound.
  const toggle = () => {
    setOpen((o) => {
      const next = !o;
      if (next) {
        const focus = parseIso(value) ?? parseIso(max ?? "");
        if (focus) setView({ y: focus.y, m: focus.m });
      }
      return next;
    });
  };

  // Close on outside click + Esc.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const minMonth = min ? min.slice(0, 7) : null;
  const maxMonth = max ? max.slice(0, 7) : null;
  const curMonth = monthKey(view.y, view.m);
  const canPrev = !minMonth || curMonth > minMonth;
  const canNext = !maxMonth || curMonth < maxMonth;

  const cells = useMemo(() => {
    const lead = firstWeekday(view.y, view.m);
    const total = daysInMonth(view.y, view.m);
    const out: (string | null)[] = [];
    for (let i = 0; i < lead; i++) out.push(null);
    for (let d = 1; d <= total; d++) out.push(iso(view.y, view.m, d));
    return out;
  }, [view]);

  const step = (delta: number) => {
    setView((v) => {
      const m = v.m + delta;
      if (m < 1) return { y: v.y - 1, m: 12 };
      if (m > 12) return { y: v.y + 1, m: 1 };
      return { y: v.y, m };
    });
  };

  const label = value
    ? (() => {
        const p = parseIso(value)!;
        return `${p.d} ${MONTHS[p.m - 1]} ${p.y}`;
      })()
    : placeholder;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={toggle}
        className={`field flex w-full min-w-[11rem] items-center justify-between gap-2 ${
          value ? "" : "text-ink-faint"
        } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
      >
        <span className="truncate font-sans">{label}</span>
        <span className="flex items-center gap-1.5">
          {value && !disabled && (
            <span
              role="button"
              tabIndex={0}
              aria-label="Изчисти датата"
              onClick={(e) => {
                e.stopPropagation();
                onChange("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onChange("");
                }
              }}
              className="text-ink-faint transition-colors hover:text-crimson"
            >
              ✕
            </span>
          )}
          <span aria-hidden className="text-ink-soft">▾</span>
        </span>
      </button>

      {open && (
        <div
          className={`absolute z-40 mt-1.5 w-[min(17.5rem,calc(100vw-2rem))] border border-line-strong bg-surface p-3 shadow-xl ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {/* Month header */}
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              onClick={() => step(-1)}
              disabled={!canPrev}
              aria-label="Предишен месец"
              className="flex h-7 w-7 items-center justify-center border border-line text-ink-soft transition-colors hover:border-crimson hover:text-crimson disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-line disabled:hover:text-ink-soft"
            >
              ‹
            </button>
            <span className="font-display text-[0.95rem] font-semibold text-ink">
              {MONTHS[view.m - 1]} {view.y}
            </span>
            <button
              type="button"
              onClick={() => step(1)}
              disabled={!canNext}
              aria-label="Следващ месец"
              className="flex h-7 w-7 items-center justify-center border border-line text-ink-soft transition-colors hover:border-crimson hover:text-crimson disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:border-line disabled:hover:text-ink-soft"
            >
              ›
            </button>
          </div>

          {/* Weekday row */}
          <div className="grid grid-cols-7 gap-0.5">
            {WEEKDAYS.map((w) => (
              <span
                key={w}
                className="flex h-6 items-center justify-center font-mono text-[0.58rem] uppercase tracking-wide text-ink-faint"
              >
                {w}
              </span>
            ))}
          </div>

          {/* Day grid */}
          <div className="mt-0.5 grid grid-cols-7 gap-0.5">
            {cells.map((d, i) => {
              if (!d) return <span key={`b${i}`} />;
              const day = +d.slice(8, 10);
              const inRange = (!min || d >= min) && (!max || d <= max);
              const isSitting = sittingDates.has(d);
              const isSelected = d === value;
              return (
                <button
                  key={d}
                  type="button"
                  disabled={!inRange}
                  onClick={() => {
                    onChange(d);
                    setOpen(false);
                  }}
                  title={isSitting ? "Заседание" : inRange ? "Няма заседание" : undefined}
                  className={`relative flex h-8 items-center justify-center rounded-sm text-[0.82rem] tabular-nums transition-colors ${
                    isSelected
                      ? "bg-crimson font-semibold text-surface"
                      : !inRange
                        ? "cursor-not-allowed text-ink-faint/40"
                        : isSitting
                          ? "font-semibold text-crimson hover:bg-crimson/10"
                          : "text-ink-soft hover:bg-surface-2"
                  }`}
                >
                  {day}
                  {isSitting && !isSelected && (
                    <span className="absolute bottom-1 h-1 w-1 rounded-full bg-crimson" />
                  )}
                </button>
              );
            })}
          </div>

          {/* Legend */}
          <div className="mt-2.5 flex items-center gap-3 border-t border-line pt-2 font-mono text-[0.58rem] uppercase tracking-wide text-ink-faint">
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-crimson" /> заседание
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-line-strong" /> няма
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
