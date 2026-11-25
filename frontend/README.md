# AgentGuard frontend

Next.js 16 dashboard for AgentGuard (TypeScript, Tailwind CSS v4, React Flow, Recharts). See the [project README](../README.md).

```bash
npm install
npm run dev          # http://localhost:3000; proxies /api to http://127.0.0.1:8000
npm run lint
npm test             # Vitest unit tests
npm run build        # production build (standalone output, used by the Dockerfile)
npm run test:e2e     # Playwright; start the backend and frontend first
```

- `API_INTERNAL_URL` sets where `/api/*` is proxied (default `http://127.0.0.1:8000`). It is fixed at **build** time for production builds.
- Branding (colors) lives in `src/app/globals.css`; the product name and icon in `src/components/app-shell.tsx`.
- Requires Node.js 22.22+ or 24.15+.
