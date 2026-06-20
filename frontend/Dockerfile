# Parliament RAG frontend — Next.js chat UI.
#
# Multi-stage: install deps, build the standalone bundle, then ship only the
# traced output on a slim runtime image. The browser only talks to this app's
# own origin; `/api/*` is proxied server-side to BACKEND_ORIGIN (set in compose).
# corepack pins pnpm to the `packageManager` version in package.json, so the
# container matches local exactly. (Unpinned pnpm installs the latest major,
# which hard-fails frozen installs on ignored build scripts like sharp /
# unrs-resolver that 10.x silences via pnpm-workspace.yaml.)
FROM node:22-slim AS base
RUN corepack enable
WORKDIR /app

# ---- deps: cached unless the lockfile changes -------------------------------
FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# ---- builder: compile the standalone server bundle -------------------------
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ---- runner: minimal production image --------------------------------------
FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Run as the unprivileged user that ships with the node image.
USER node

# standalone/ has server.js + the traced node_modules; static + public are not
# copied into it automatically, so bring them alongside.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

EXPOSE 3000

CMD ["node", "server.js"]
