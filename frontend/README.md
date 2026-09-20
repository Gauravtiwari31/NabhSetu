# Nabhsetu dashboard

React + TypeScript operator UI for SIH26056. Every page inherits a persistent
banner for mock, live, or policy-denied data.

```bash
npm install
npm run dev
```

Local Vite proxies API routes to `http://127.0.0.1:8000`. Override with
`VITE_PROXY_TARGET` or set `VITE_API_BASE` to a full URL. Docker Compose bakes
`VITE_API_BASE=http://localhost:8000` into the preview image.

```bash
npm test
npm run build
```
