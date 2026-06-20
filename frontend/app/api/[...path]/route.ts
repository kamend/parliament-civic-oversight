import { type NextRequest } from "next/server";

/**
 * Same-origin proxy for the FastAPI backend. The browser calls this app's own
 * `/api/*` paths and we forward them to BACKEND_ORIGIN, streaming the response
 * straight back.
 *
 * Why a Route Handler and not a next.config `rewrites` rule: rewrites *buffer*
 * the response, so the SSE stream from `/api/ask` only flushed once it closed —
 * the `sources` event and the whole answer arrived at once. Returning the
 * upstream `body` ReadableStream here streams it frame-by-frame, as intended.
 */

const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN?.replace(/\/$/, "") ?? "http://127.0.0.1:8077";

// Never cache or statically optimize the proxy — every request hits the backend.
export const dynamic = "force-dynamic";

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  const search = new URL(req.url).search;
  const target = `${BACKEND_ORIGIN}/api/${path.join("/")}${search}`;

  // Forward the incoming headers, minus ones that must not be proxied verbatim.
  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");

  const hasBody = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      // The request body (e.g. the small ask payload) is fully buffered here;
      // only the *response* needs to stream.
      body: hasBody ? await req.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return new Response("Backend unreachable", { status: 502 });
  }

  // Pass the body stream through untouched. Drop encoding/length headers that
  // describe the upstream transfer and don't survive re-framing.
  const respHeaders = new Headers(upstream.headers);
  respHeaders.delete("content-encoding");
  respHeaders.delete("content-length");
  respHeaders.delete("transfer-encoding");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(req, (await ctx.params).path);
}
