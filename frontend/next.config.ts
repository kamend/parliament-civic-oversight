import type { NextConfig } from "next";

// `/api/*` is proxied to the FastAPI backend by a Route Handler
// (app/api/[...path]/route.ts), not a `rewrites` rule — rewrites buffer the SSE
// response and break token-by-token streaming. The backend host lives there, in
// BACKEND_ORIGIN. The browser only ever talks to this app's own origin.
const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.68.69"],
  // Emit a self-contained server bundle (.next/standalone) so the Docker
  // runtime image ships only the traced files, not the full node_modules.
  output: "standalone",
  // Pin the workspace root to this app. Otherwise Turbopack walks up the tree,
  // finds stray lockfiles (e.g. ~/pnpm-lock.yaml), and guesses the wrong root.
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
