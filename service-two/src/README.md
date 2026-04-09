# service-two — Next.js

> **Example service.** Delete this folder if your team doesn't need a Next.js frontend,
> or keep it and replace the source code with your own.

## Source layout

```
service-two/
├── config/
│   ├── deploy.yaml       ← pipeline + Helm config (edit this)
│   └── secrets.json      ← GitHub secret mappings (edit this)
├── src/                  ← your Next.js source (place files here or at service root)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── api/
│   │       └── health/
│   │           └── route.ts   ← required health check endpoint
│   └── public/
├── next.config.ts              ← must include output: "standalone"
├── package.json                ← place at service root (next to Dockerfile)
└── yarn.lock
```

## Required `next.config.ts`

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",   // required — Dockerfile copies .next/standalone
};

export default nextConfig;
```

## Health check (`app/api/health/route.ts`)

```ts
import { NextResponse } from "next/server";

export const GET = () => NextResponse.json({ status: "ok" });
```

## Local dev

```bash
yarn install
yarn dev   # http://localhost:3000
```

## Private `@nurixlabs` packages

Create a `ORG_YARNRC` repo secret (GitHub token with `read:packages` scope).
The pipeline injects it automatically as `--build-arg ORG_YARNRC`.

## To rename this service

1. Rename the folder: `mv service-two service-my-name`
2. Update `config/deploy.yaml`: set `helmReleaseName`, `namespace`, and the ingress host
