FROM node:22-alpine AS base

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# dev: hot-reload via next dev; source is bind-mounted at runtime
FROM base AS dev
ENV NEXT_TELEMETRY_DISABLED=1
CMD ["pnpm", "dev"]

# prod: build once, then serve the optimized output
FROM base AS prod
COPY . .
# next build bakes the /api/* rewrite destination, so API_URL must be set here
ARG API_URL=http://api:8000
ENV API_URL=$API_URL
RUN pnpm build
CMD ["pnpm", "start"]

EXPOSE 3000
CMD ["pnpm", "start"]
