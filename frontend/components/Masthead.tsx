"use client";

import Link from "next/link";

/**
 * Newspaper-style masthead: the title set in serif, a dateline of the corpus
 * range, and the section nav. `current` flags which section we're in so the
 * nav can mark it active.
 */
export function Masthead({
  dateRange,
  current = "ask",
}: {
  dateRange?: { min: string | null; max: string | null };
  current?: "ask" | "sittings";
}) {
  return (
    <header className="relative z-10 border-t-[3px] border-t-crimson border-b border-b-line-strong bg-paper/70 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-end justify-between gap-x-6 gap-y-2 px-4 py-4 sm:px-6">
        <div>
          <p className="eyebrow mb-1">Стенографски архив · Народно събрание</p>
          <Link href="/" className="inline-block">
            <h1 className="font-display text-[1.5rem] leading-none font-extrabold tracking-tight text-ink py-3 sm:text-[1.9rem]">
              Граждански контрол
              <span className="text-crimson">.</span>
            </h1>
          </Link>
          <nav className="mt-2 flex items-center gap-4 font-mono text-[0.68rem] uppercase tracking-[0.14em]">
            <NavLink href="/" active={current === "ask"}>
              Запитване
            </NavLink>
            <NavLink href="/sittings" active={current === "sittings"}>
              Заседания
            </NavLink>
          </nav>
        </div>

        {/* {dateRange?.min && dateRange?.max && (
          <div className="flex flex-col items-end gap-1.5 pb-1">
            <span className="font-mono text-[0.64rem] text-ink-faint tabular-nums">
              {dateRange.min} → {dateRange.max}
            </span>
          </div>
        )} */}
      </div>
    </header>
  );
}

/** A masthead nav item: crimson underline when it's the current section. */
function NavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`border-b-2 pb-0.5 transition-colors ${
        active
          ? "border-crimson text-crimson"
          : "border-transparent text-ink-soft hover:text-ink"
      }`}
    >
      {children}
    </Link>
  );
}
