# Web dashboard

Next.js (App Router, TypeScript). See `docs/phase6.md` in the repo root.

* `src/lib/bff-core.ts` : the proxy, cookie and token-refresh logic (pure, fully unit-tested)
* `src/app/bff/[...path]` : forwards browser requests to the API with the token attached
* `src/app/auth/*` : login and logout
* `src/app/(app)/*` : the screens (dashboard, customers, import)

```bash
npm install
npm run typecheck
npm test
npm run build
```

`API_URL` (default `http://api:8000`) is the address of the API as seen from this container.
