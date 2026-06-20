"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  askStream,
  getFilters,
  type ClarifyEvent,
  type DoneEvent,
  type Filters,
  type Source,
} from "@/lib/api";
import { Masthead } from "@/components/Masthead";
import { Footer } from "@/components/Footer";
import { FilterBar, type QueryState } from "@/components/FilterBar";
import { AnswerView } from "@/components/AnswerView";
import { SourcesPanel } from "@/components/SourcesPanel";

type Phase =
  | "idle"
  | "retrieving"
  | "answering"
  | "done"
  | "clarify"
  | "error";

const EXAMPLES = [
  "Какво беше казано за бюджета и дефицита?",
  "Какви аргументи прозвучаха за еврозоната?",
  "Как се обсъждаше реформата в съдебната система?",
];

const INITIAL: QueryState = {
  question: "",
  party: "",
  speaker: "",
  since: "",
  until: "",
  k: 10,
};

export default function Home() {
  const [filters, setFilters] = useState<Filters | null>(null);
  const [q, setQ] = useState<QueryState>(INITIAL);

  const [sources, setSources] = useState<Source[]>([]);
  const [answer, setAnswer] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [done, setDone] = useState<DoneEvent | null>(null);
  const [clarify, setClarify] = useState<ClarifyEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // Load the filter options (parties, speakers, date bounds) once on mount.
  useEffect(() => {
    const ac = new AbortController();
    getFilters(ac.signal)
      .then(setFilters)
      .catch(() => {
        /* backend unreachable — filters stay empty; the form still works */
      });
    return () => ac.abort();
  }, []);

  const patch = useCallback(
    (p: Partial<QueryState>) => setQ((prev) => ({ ...prev, ...p })),
    [],
  );

  const validSources = useMemo(
    () => new Set(sources.map((s) => s.n)),
    [sources],
  );

  const busy = phase === "retrieving" || phase === "answering";

  const submit = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed) return;

      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      setSources([]);
      setAnswer("");
      setDone(null);
      setClarify(null);
      setError(null);
      setPhase("retrieving");

      askStream(
        {
          question: trimmed,
          party: q.party || undefined,
          speaker: q.speaker || undefined,
          since: q.since || undefined,
          until: q.until || undefined,
          k: q.k,
          rerank: true, // always on — reranking is no longer a user toggle
        },
        {
          onSources: (s) => {
            setSources(s);
            setPhase("answering");
          },
          onToken: (t) => setAnswer((prev) => prev + t),
          onClarify: (c) => {
            setClarify(c);
            setPhase("clarify");
          },
          onDone: (d) => {
            // A clarify event already set the terminal phase; don't overwrite it.
            setDone(d);
            setPhase((prev) => (prev === "clarify" ? prev : "done"));
          },
          onError: (stage, message) => {
            setError(`${message}`);
            setPhase("error");
          },
        },
        ac.signal,
      );
    },
    [q],
  );

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit(q.question);
  };

  const runExample = (text: string) => {
    setQ((prev) => ({ ...prev, question: text }));
    submit(text);
  };

  const showWelcome = phase === "idle" && !answer;

  return (
    <div className="relative z-10 flex flex-1 flex-col">
      <Masthead
        dateRange={
          filters ? { min: filters.min_date, max: filters.max_date } : undefined
        }
      />

      {/* Query bar */}
      <section className="relative z-10 border-b border-line bg-surface/50">
        <div className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6">
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex items-stretch gap-3">
              <div className="relative flex-1">
                <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 font-display text-xl text-crimson select-none">
                  ?
                </span>
                <input
                  autoFocus
                  value={q.question}
                  onChange={(e) => patch({ question: e.target.value })}
                  placeholder="Задайте своя въпрос…"
                  className="field w-full !text-[1.05rem] !py-3.5 !pl-10 !pr-14 font-display sm:!pr-4"
                />
                {/* Mobile: an arrow submit lives inside the field so the input can
                    run nearly full width. Hidden once the text button appears. */}
                <button
                  type="submit"
                  disabled={busy || !q.question.trim()}
                  aria-label="Питай"
                  className="absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center bg-ink text-paper transition-colors hover:bg-crimson disabled:cursor-not-allowed disabled:opacity-40 sm:hidden"
                >
                  {busy ? (
                    <span className="text-base leading-none">…</span>
                  ) : (
                    <svg
                      aria-hidden
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="h-4 w-4"
                    >
                      <path d="M5 12h14M13 6l6 6-6 6" />
                    </svg>
                  )}
                </button>
              </div>
              <button
                type="submit"
                disabled={busy || !q.question.trim()}
                className="hidden shrink-0 bg-ink px-7 font-mono text-[0.74rem] uppercase tracking-[0.18em] text-paper transition-colors hover:bg-crimson disabled:cursor-not-allowed disabled:opacity-40 sm:block"
              >
                {busy ? "…" : "Питай"}
              </button>
            </div>

            <FilterBar
              filters={filters}
              state={q}
              onChange={patch}
              disabled={busy}
            />
          </form>
        </div>
      </section>

      {/* Body: answer column + sources apparatus */}
      <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-8 sm:px-6">
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] lg:gap-10">
          {/* Answer */}
          <section className="min-w-0">
            {showWelcome ? (
              <Welcome onPick={runExample} disabled={busy} />
            ) : (
              <>
                <div className="mb-4 flex items-center justify-between border-b border-line pb-2">
                  <h2 className="eyebrow">Отговор</h2>
                  {phase === "retrieving" && (
                    <span className="font-mono text-[0.64rem] text-ink-faint">
                      издирване на източниците…
                    </span>
                  )}
                </div>

                {error && (
                  <div className="border-l-2 border-crimson bg-crimson/5 px-4 py-3 font-sans text-[0.9rem] text-crimson-deep">
                    {error}
                  </div>
                )}

                {phase === "clarify" && clarify && (
                  <ClarifyNotice clarify={clarify} onPick={runExample} disabled={busy} />
                )}

                {phase === "done" && done?.no_results && (
                  <p className="font-display italic text-[1.05rem] text-ink-soft">
                    Няма открити реплики по този въпрос с избраните филтри.
                  </p>
                )}

                {(answer || phase === "answering") && (
                  <AnswerView
                    text={answer}
                    streaming={phase === "answering"}
                    validSources={validSources}
                  />
                )}

                {answer && (
                  <p className="mt-5 flex items-start gap-2 border-l-2 border-amber bg-amber/5 px-3 py-2 font-sans text-[0.78rem] leading-relaxed text-ink-soft">
                    <span aria-hidden className="text-amber">
                      ⚠
                    </span>
                    <span>
                      Отговорът е генериран от изкуствен интелект и може да
                      съдържа неточности. Проверявайте важните твърдения в
                      цитираните източници.
                    </span>
                  </p>
                )}

                {done && !done.no_results && (
                  <p className="mt-7 border-t border-line pt-3 font-mono text-[0.62rem] text-ink-faint">
                    {done.model} · {done.input_tokens} вх. / {done.output_tokens} изх.
                    токена
                  </p>
                )}
              </>
            )}
          </section>

          {/* Sources */}
          <SourcesPanel sources={sources} loading={phase === "retrieving"} />
        </div>
      </main>

      <Footer />
    </div>
  );
}

/** Shown when the answerability gate judged the question too broad to ground:
 * a soft prompt to narrow it, plus clickable example reformulations. */
function ClarifyNotice({
  clarify,
  onPick,
  disabled,
}: {
  clarify: ClarifyEvent;
  onPick: (q: string) => void;
  disabled?: boolean;
}) {
  const message =
    clarify.message?.trim() ||
    "Въпросът е твърде общ. Опитайте да попитате за конкретна тема, закон, събитие или лице.";
  return (
    <div className="border-l-2 border-amber bg-amber/5 px-5 py-4">
      <p className="eyebrow mb-2 text-amber">Уточнете въпроса</p>
      <p className="font-display text-[1.05rem] leading-relaxed text-ink">
        {message}
      </p>

      {clarify.suggestions.length > 0 && (
        <div className="mt-5">
          <p className="eyebrow mb-3">Например</p>
          <div className="flex flex-col gap-2">
            {clarify.suggestions.map((s) => (
              <button
                key={s}
                onClick={() => onPick(s)}
                disabled={disabled}
                className="group flex items-center gap-3 border border-line bg-surface px-4 py-3 text-left transition-all hover:border-crimson hover:bg-surface-2 disabled:opacity-50"
              >
                <span className="font-mono text-crimson transition-transform group-hover:translate-x-0.5">
                  →
                </span>
                <span className="font-display text-[1.02rem] text-ink">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** First-run state: the premise and example questions. */
function Welcome({
  onPick,
  disabled,
}: {
  onPick: (q: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="max-w-2xl">
      <h2 className="font-display text-[1.65rem] leading-[1.2] font-bold text-ink sm:text-[2.1rem] sm:leading-[1.18]">
        Питайте стенограмите.{" "}
        <span className="italic text-ink-soft">
          Всяко твърдение сочи към репликата, от която идва.
        </span>
      </h2>
      <p className="mt-4 font-sans text-[0.98rem] leading-relaxed text-ink-soft">
        Задайте въпрос за дебатите в Народното събрание и получете кратък, ясен
        отговор, опрян на официалните стенограми — с цитати{" "}
        <span className="cite-chip">S#</span>, които водят право към оригиналния
        запис.
      </p>

      <div className="mt-8">
        <p className="eyebrow mb-3">Опитайте</p>
        <div className="flex flex-col gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => onPick(ex)}
              disabled={disabled}
              className="group flex items-center gap-3 border border-line bg-surface px-4 py-3 text-left transition-all hover:border-crimson hover:bg-surface-2 disabled:opacity-50"
            >
              <span className="font-mono text-crimson transition-transform group-hover:translate-x-0.5">
                →
              </span>
              <span className="font-display text-[1.02rem] text-ink">{ex}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
