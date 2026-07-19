# syntax=docker/dockerfile:1
# Multi-stage build for the Sentinel SPA: compile the static bundle with
# pnpm/Vite, then serve it from nginx. nginx also reverse-proxies /api → the
# backend "web" service, so the app is a single origin — no CORS, and the S9a
# Bearer token never appears in a URL.

# ---- builder: produce the static dist/ --------------------------------------
FROM node:22-bookworm-slim AS builder
WORKDIR /app

# Pin pnpm via corepack to match the committed lockfile toolchain.
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

# Dependency layer first (cached until the manifest / lockfile change).
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Source, then build: `tsc --noEmit && vite build` → /app/dist.
# VITE_API_BASE_URL defaults to "/api/v1" (same-origin), which nginx proxies —
# no token is baked in (a deployed build reads it from localStorage).
COPY . .
RUN pnpm build

# ---- runtime: nginx serving the SPA + proxying /api -------------------------
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
