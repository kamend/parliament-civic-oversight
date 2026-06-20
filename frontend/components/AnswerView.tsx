"use client";

import { Children, cloneElement, Fragment, isValidElement, useMemo } from "react";
import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const CITE = /\[S(\d+)\]/g;

/** Scroll the matching source card into view and flag it briefly. */
function gotoSource(n: number) {
  const el = document.getElementById(`source-${n}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("is-flagged");
  void el.offsetWidth; // reflow so the animation re-triggers on repeat clicks
  el.classList.add("is-flagged");
}

/** Split a plain string on `[S#]`, turning live citations into clickable chips. */
function splitCitations(text: string, valid: Set<number>, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(CITE)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(<Fragment key={`${keyBase}-t${i}`}>{text.slice(last, idx)}</Fragment>);
    const n = Number(m[1]);
    // Only render a live chip if the source exists — otherwise leave the raw tag
    // as text so a model hallucination can't dangle a dead link.
    if (valid.has(n)) {
      out.push(
        <button
          key={`${keyBase}-c${i}`}
          className="cite-chip"
          onClick={() => gotoSource(n)}
          aria-label={`Източник ${n}`}
          title={`Към източник ${n}`}
        >
          {n}
        </button>,
      );
    } else {
      out.push(<Fragment key={`${keyBase}-r${i}`}>{m[0]}</Fragment>);
    }
    last = idx + m[0].length;
    i++;
  }
  if (last < text.length) out.push(<Fragment key={`${keyBase}-e`}>{text.slice(last)}</Fragment>);
  return out;
}

/**
 * Walk rendered Markdown children, replacing `[S#]` inside any string node with
 * a citation chip — recursing through inline elements (bold, italic, links) so a
 * citation works wherever it lands.
 */
function withCitations(children: ReactNode, valid: Set<number>, keyBase = "k"): ReactNode {
  return Children.map(children, (child, i) => {
    if (typeof child === "string") return splitCitations(child, valid, `${keyBase}-${i}`);
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return cloneElement(
        child,
        undefined,
        withCitations(child.props.children, valid, `${keyBase}-${i}`),
      );
    }
    return child;
  });
}

/**
 * Renders the streamed answer as Markdown set in the editorial serif, turning
 * every `[S#]` tag into a clickable crimson footnote chip. A blinking caret
 * trails the text while the answer is still streaming.
 */
export function AnswerView({
  text,
  streaming,
  validSources,
}: {
  text: string;
  streaming: boolean;
  validSources: Set<number>;
}) {
  // Build the components map once per source set; each text-bearing element runs
  // its children through the citation injector.
  const components = useMemo<Components>(() => {
    const cite = (children: ReactNode) => withCitations(children, validSources);
    return {
      p: ({ children }) => <p>{cite(children)}</p>,
      li: ({ children }) => <li>{cite(children)}</li>,
      h1: ({ children }) => <h2>{cite(children)}</h2>,
      h2: ({ children }) => <h2>{cite(children)}</h2>,
      h3: ({ children }) => <h3>{cite(children)}</h3>,
      h4: ({ children }) => <h4>{cite(children)}</h4>,
      blockquote: ({ children }) => <blockquote>{cite(children)}</blockquote>,
      td: ({ children }) => <td>{cite(children)}</td>,
      th: ({ children }) => <th>{cite(children)}</th>,
      // Links from the model shouldn't navigate away unexpectedly.
      a: ({ children, href }) => (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {cite(children)}
        </a>
      ),
    };
  }, [validSources]);

  return (
    <div className={`answer-md ${streaming ? "caret" : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
