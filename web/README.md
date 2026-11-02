# regwatch web

Node 22, pnpm 9 (pinned through `packageManager`; `corepack enable` once), Vite 6, React 18, strict TypeScript.

```
pnpm install
pnpm dev        # http://localhost:5173 (or http://localhost through the proxy with make dev)
pnpm lint && pnpm typecheck
pnpm test -- --coverage
```

Themes: `src/styles/tokens.css` defines the tokens from `docs/contracts/screens.md`; `html[data-theme]` selects `light`, `dark` or `high-contrast`. Tailwind utilities map to the tokens (`bg-surface`, `text-text-muted`, `border-border`, `min-h-hit`).
