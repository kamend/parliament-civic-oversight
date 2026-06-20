"use client";

import { useMemo, useState } from "react";
import type { Filters } from "@/lib/api";
import { DatePicker } from "./DatePicker";

export interface QueryState {
  question: string;
  party: string;
  speaker: string;
  since: string;
  until: string;
  k: number;
}

/**
 * The query apparatus: party dropdown, speaker combobox (native datalist over
 * the known speakers), a date range bounded by the corpus, and the source
 * count. Fed by `/api/filters`; values flow up via `onChange`. Cross-encoder
 * reranking is always on, so it's not exposed as a control.
 */
export function FilterBar({
  filters,
  state,
  onChange,
  disabled,
}: {
  filters: Filters | null;
  state: QueryState;
  onChange: (patch: Partial<QueryState>) => void;
  disabled?: boolean;
}) {
  const minDate = filters?.min_date ?? undefined;
  const maxDate = filters?.max_date ?? undefined;
  const sittingDates = useMemo(
    () => new Set(filters?.sitting_dates ?? []),
    [filters?.sitting_dates],
  );

  // Mobile-only disclosure. Filters are a refinement most users skip, so they
  // stay collapsed on small screens to keep the answer high on the page; the
  // badge surfaces how many are set without expanding. Always open on sm+.
  const [open, setOpen] = useState(false);
  const activeCount =
    (state.party ? 1 : 0) +
    (state.speaker ? 1 : 0) +
    (state.since ? 1 : 0) +
    (state.until ? 1 : 0);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between border border-line bg-surface px-4 py-2.5 font-mono text-[0.7rem] uppercase tracking-wider text-ink-soft transition-colors hover:border-crimson sm:hidden"
      >
        <span className="flex items-center gap-2">
          Филтри
          {activeCount > 0 && (
            <span className="inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-crimson px-1 text-[0.6rem] font-semibold text-paper">
              {activeCount}
            </span>
          )}
        </span>
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`h-3.5 w-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      <div
        className={`${open ? "mt-3 flex" : "hidden"} flex-wrap items-end gap-x-4 gap-y-3 sm:mt-0 sm:flex sm:gap-x-5`}
      >
      {/* Party */}
      <label className="flex w-full flex-col gap-1 sm:w-auto">
        <span className="eyebrow">Партия</span>
        <select
          className="field w-full cursor-pointer sm:w-auto sm:min-w-[10rem]"
          value={state.party}
          disabled={disabled}
          onChange={(e) => onChange({ party: e.target.value })}
        >
          <option value="">Всички партии</option>
          {filters?.parties.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>

      {/* Speaker */}
      <label className="flex w-full flex-col gap-1 sm:w-auto">
        <span className="eyebrow">Говорител</span>
        <input
          className="field field-search w-full sm:w-auto sm:min-w-[12rem]"
          list="speaker-list"
          placeholder="всеки говорител"
          value={state.speaker}
          disabled={disabled}
          onChange={(e) => onChange({ speaker: e.target.value })}
        />
        <datalist id="speaker-list">
          {filters?.speakers.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </label>

      {/* Date range — custom calendars that mark which days had sittings */}
      <div className="flex w-full flex-col gap-1 sm:w-auto">
        <span className="eyebrow">От дата</span>
        <DatePicker
          value={state.since}
          onChange={(since) => onChange({ since })}
          min={minDate}
          max={maxDate}
          sittingDates={sittingDates}
          disabled={disabled}
          placeholder="от начало"
        />
      </div>
      <div className="flex w-full flex-col gap-1 sm:w-auto">
        <span className="eyebrow">До дата</span>
        <DatePicker
          value={state.until}
          onChange={(until) => onChange({ until })}
          min={minDate}
          max={maxDate}
          sittingDates={sittingDates}
          disabled={disabled}
          placeholder="до край"
        />
      </div>

      {/* Sources: most-relevant (10) vs the maximum (25) */}
      <label className="flex w-full flex-col gap-1 sm:w-auto">
        <span className="eyebrow">Източници</span>
        <select
          className="field w-full cursor-pointer sm:w-auto sm:min-w-[10rem]"
          value={state.k}
          disabled={disabled}
          onChange={(e) => onChange({ k: Number(e.target.value) })}
        >
          <option value={10}>Най-съответващи</option>
          <option value={25}>Максимален брой</option>
        </select>
      </label>
      </div>
    </div>
  );
}
