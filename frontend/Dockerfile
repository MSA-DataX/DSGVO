# Multi-stage build — runtime image carries only the Next.js
# `standalone` output + static assets. No node_modules, no .next/cache,
# ~150 MB final size instead of 1+ GB.

# --- Stage 1: install dependencies (cache key = lockfile) -----------------
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- Stage 2: build the app -----------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app
# NEXT_PUBLIC_* values are inlined at BUILD time, not runtime. Whatever
# the operator sets here is what the browser bundle will see forever.
# docker-compose.prod.yml passes these through via `build.args`.
ARG NEXT_PUBLIC_BACKEND_URL=http://localhost:8080
ARG NEXT_PUBLIC_SCAN_MODE=sync
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL \
    NEXT_PUBLIC_SCAN_MODE=$NEXT_PUBLIC_SCAN_MODE \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# --- Stage 3: runtime -----------------------------------------------------
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Drop privileges. `node` is the built-in user in the Alpine image.
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# Public assets are not part of the standalone output; copy them over.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
# .next/standalone is the minimal server bundle, .next/static the build
# artefacts the server references. Both owned by the non-root user.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# The standalone output ships its own `server.js` entry point.
CMD ["node", "server.js"]
