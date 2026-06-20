/**
 * Client for the Parliament RAG FastAPI backend.
 *
 * The interesting part is `askStream`: `/api/ask` is Server-Sent Events served
 * over a POST, which `EventSource` can't do (it's GET-only). So we POST with
 * `fetch`, read the body as a stream, and parse the `event:` / `data:` frames
 * by hand — the same wire format the backend's `_sse()` emits.
 */

// Empty by default = same-origin: the browser hits this app's own `/api/*`
// paths, which the Next.js server proxies to the backend (see the `rewrites` in
// next.config.ts). Set NEXT_PUBLIC_API_BASE only to make the browser call a
// backend directly instead of going through the proxy — then that backend must
// allow this origin via CORS.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "";

// ── Wire types (mirror backend/app/schemas.py) ──────────────────────────────
export interface Source {
  n: number;
  id: string;
  text: string;
  speaker?: string | null;
  speaker_raw?: string | null;
  role?: string | null;
  party?: string | null;
  date?: string | null;
  transcript_id?: string | null;
  sitting?: string | null;
  turn_index?: number | null;
  score: number;
  hybrid_score: number;
  reranked: boolean;
  prior_rank?: number | null;
}

// One speaker turn in the full-transcript viewer. `index` matches a Source's
// `turn_index`, so the viewer can scroll to and highlight the cited turn.
export interface TranscriptTurn {
  index: number;
  speaker: string;
  speaker_raw: string;
  role?: string | null;
  party?: string | null;
  modifier?: string | null;
  text: string;
}

export interface Transcript {
  id: string;
  date: string;
  header: string;
  sitting?: string | null;
  // False when the protocol isn't published yet — the sitting has no turns.
  has_transcript: boolean;
  turns: TranscriptTurn[];
}

// One plenary sitting in the browse list — metadata only; the full record is
// fetched on demand via `getTranscript`.
export interface Sitting {
  id: string;
  date: string;
  month: string; // 'YYYY-MM'
  title?: string | null;
  // False when the stenographic protocol isn't published yet (placeholder only).
  has_transcript: boolean;
}

export interface SittingsResponse {
  sittings: Sitting[];
  months: string[]; // distinct 'YYYY-MM', newest first
}

export interface Filters {
  parties: string[];
  speakers: string[];
  min_date: string | null;
  max_date: string | null;
  // Distinct 'YYYY-MM-DD' dates that actually have sittings, for the calendar.
  sitting_dates: string[];
}

export interface AskParams {
  question: string;
  party?: string;
  speaker?: string;
  since?: string;
  until?: string;
  date?: string;
  k?: number;
  rerank?: boolean;
  // Run the answerability gate first (default true server-side). Too-broad
  // questions get a `clarify` event instead of retrieval + an answer.
  route?: boolean;
}

export interface DoneEvent {
  answer: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  no_results?: boolean;
  // True when the stream ended because the answerability gate asked the user to
  // narrow the question (a `clarify` event preceded this `done`).
  needs_clarification?: boolean;
}

// Emitted instead of `sources`/`token` when the question is too broad to ground:
// a soft prompt to be more specific, plus example reformulations to click.
export interface ClarifyEvent {
  message: string | null;
  suggestions: string[];
  reason?: string;
}

/** Callbacks for the lifecycle of one `/api/ask` stream. */
export interface AskHandlers {
  onSources?: (sources: Source[]) => void;
  onToken?: (text: string) => void;
  onClarify?: (clarify: ClarifyEvent) => void;
  onDone?: (done: DoneEvent) => void;
  onError?: (stage: string, message: string) => void;
}

// ── Plain JSON endpoints ─────────────────────────────────────────────────────
export async function getFilters(signal?: AbortSignal): Promise<Filters> {
  const res = await fetch(`${API_BASE}/api/filters`, { signal });
  if (!res.ok) throw new Error(`filters: HTTP ${res.status}`);
  return res.json();
}

/** List every plenary sitting (newest first) plus the distinct months, for the
 * browse-all-sittings page. */
export async function getSittings(signal?: AbortSignal): Promise<SittingsResponse> {
  const res = await fetch(`${API_BASE}/api/sittings`, { signal });
  if (!res.ok) throw new Error(`sittings: HTTP ${res.status}`);
  return res.json();
}

/** Fetch a full plenary sitting, parsed into ordered speaker turns, for the
 * full-screen transcript viewer. */
export async function getTranscript(
  transcriptId: string,
  signal?: AbortSignal,
): Promise<Transcript> {
  const res = await fetch(`${API_BASE}/api/transcript/${transcriptId}`, { signal });
  if (!res.ok) throw new Error(`transcript: HTTP ${res.status}`);
  return res.json();
}

// ── The streaming ask ────────────────────────────────────────────────────────
/**
 * POST a question and dispatch each SSE frame to `handlers`. Pass an
 * `AbortSignal` to cancel an in-flight stream (e.g. the user asks again).
 */
export async function askStream(
  params: AskParams,
  handlers: AskHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    handlers.onError?.("network", "Сървърът е недостъпен.");
    return;
  }

  if (!res.ok || !res.body) {
    handlers.onError?.("http", `HTTP ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line.
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        dispatchFrame(frame, handlers);
      }
    }
  } catch (e) {
    if ((e as Error).name !== "AbortError") {
      handlers.onError?.("stream", (e as Error).message);
    }
  }
}

/** Parse one `event:` / `data:` frame and route it to the right handler. */
function dispatchFrame(frame: string, handlers: AskHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return;

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    return; // ignore unparseable frames (e.g. keep-alives)
  }

  switch (event) {
    case "sources":
      handlers.onSources?.((data as { sources: Source[] }).sources);
      break;
    case "token":
      handlers.onToken?.((data as { text: string }).text);
      break;
    case "clarify":
      handlers.onClarify?.(data as ClarifyEvent);
      break;
    case "done":
      handlers.onDone?.(data as DoneEvent);
      break;
    case "error": {
      const d = data as { stage?: string; message?: string };
      handlers.onError?.(d.stage ?? "error", d.message ?? "Грешка");
      break;
    }
  }
}
