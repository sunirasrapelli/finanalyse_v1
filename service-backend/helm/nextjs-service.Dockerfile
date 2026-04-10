# Multi-stage build for Next.js applications
FROM node:22-alpine AS base
ARG ORG_YARNRC
ARG BUILD_ENV=dev
ARG CI=true

# Install dependencies only when needed
FROM base AS deps
# Check https://github.com/nodejs/docker-node/tree/b4117f9333da4138b03a546ec926ef50a31506c3#nodealpine to understand why libc6-compat might be needed.
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Install dependencies based on the preferred package manager
COPY package.json yarn.lock* package-lock.json* pnpm-lock.yaml* ./
RUN corepack enable

# Debug: Check what files were copied
RUN echo "Files copied to /app:" && ls -la

RUN echo "//npm.pkg.github.com/:_authToken=${ORG_YARNRC}" > .npmrc && \
  echo "@nurixlabs:registry=https://npm.pkg.github.com" >> .npmrc && \
  echo "npmScopes:" > .yarnrc.yml && \
  echo "  nurixlabs:" >> .yarnrc.yml && \
  echo "    npmAuthToken: '${ORG_YARNRC}'" >> .yarnrc.yml && \
  echo "    npmAlwaysAuth: true" >> .yarnrc.yml && \
  echo "    npmRegistryServer: 'https://npm.pkg.github.com'" >> .yarnrc.yml && \
  echo "nodeLinker: node-modules" >> .yarnrc.yml && \
  echo "enableGlobalCache: false" >> .yarnrc.yml

RUN \
  echo "Checking for lockfiles..." && \
  ls -la && \
  # Set CI environment variable so is-ci package can detect CI environment
  export CI=${CI} && \
  echo "CI environment variable set to: $CI" && \
  if [ -f yarn.lock ]; then \
    echo "Found yarn.lock, installing with yarn..." && \
    yarn install; \
  elif [ -f package-lock.json ]; then \
    echo "Found package-lock.json, installing with npm..." && \
    npm ci; \
  elif [ -f pnpm-lock.yaml ]; then \
    echo "Found pnpm-lock.yaml, installing with pnpm..." && \
    corepack enable pnpm && pnpm i --frozen-lockfile; \
  elif [ -f package.json ]; then \
    echo "No lockfile found, but package.json exists. Installing with yarn..." && \
    yarn install; \
  else \
    echo "No package.json or lockfile found. Available files:" && \
    ls -la && \
    exit 1; \
  fi

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/.yarnrc.yml ./.yarnrc.yml
# This brings all the files to the builder stage
COPY . .

# Next.js collects completely anonymous telemetry data about general usage.
# Learn more here: https://nextjs.org/telemetry
# Uncomment the following line in case you want to disable telemetry during the build.
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
# Build for the specified environment
RUN echo "Building for environment: ${BUILD_ENV}" && \
    echo "Available .env files:" && \
    ls -la .env* || echo "No .env files found" && \
    if [ -f ".env.${BUILD_ENV}" ]; then \
      echo "Using .env.${BUILD_ENV} file" && \
      echo "Environment file contents (first 5 lines):" && \
      head -5 .env.${BUILD_ENV} && \
      cp .env.${BUILD_ENV} .env.local && \
      # echo 'module.exports = { output: "standalone" };' > next.config.js && \
      yarn build; \
    else \
      echo "No .env.${BUILD_ENV} file found, using default environment variables" && \
      # echo 'module.exports = { output: "standalone" };' > next.config.js && \
      yarn build; \
    fi

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app
RUN corepack enable

ENV NODE_ENV=production
# Uncomment the following line in case you want to disable telemetry during runtime.
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Automatically leverage output traces to reduce image size
# https://nextjs.org/docs/advanced-features/output-file-tracing
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Create necessary directories and ensure proper ownership
RUN mkdir -p /app/.next/cache /app/.next/server /app/tmp && \
    chown -R nextjs:nodejs /app/.next && \
    chown -R nextjs:nodejs /app/tmp && \
    chown nextjs:nodejs /app && \
    chmod 755 /app/.next && \
    chmod 755 /app/.next/cache && \
    echo "Verifying permissions:" && \
    ls -la /app/ && \
    ls -la /app/.next/

USER nextjs

EXPOSE 3000

ENV PORT=3000
# set hostname to localhost
ENV HOSTNAME="0.0.0.0"

# server.js is created by next build from the standalone output
# https://nextjs.org/docs/pages/api-reference/next-config-js/output
CMD ["node", "server.js"]

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/api || exit 1
