# OrbitSentinel frontend handoff

This package contains the complete frontend for:

https://github.com/utkarshKeshri11sketch/Space_debris_collision_predictor

The application is in `frontend/`. The package also contains repository-level setup instructions and ignore rules. It includes the latest dashboard and object inspector, persistent red satellite/orange debris markers, conjunction review and replay, streamed mock negotiation, Cascade Lab, mobile alerts, tests, assets, licenses, and the demo GIF.

## Run the app

Use Node.js 24 or Node.js 22.12 and later.

```sh
cd frontend
npm ci
npm run dev
```

No backend or API key is required for the sample-data demo. Keep sample mode enabled until the real API is ready. The full backend contract and environment variables are documented in `frontend/README.md`.

## Push with your connected Claude Code

Extract the ZIP outside an existing checkout. Open Claude Code with the extracted folder available, and give it this request:

> Add the complete OrbitSentinel frontend from this handoff package to https://github.com/utkarshKeshri11sketch/Space_debris_collision_predictor. Clone or update the repository first, and read its applicable AGENTS.md or CLAUDE.md instructions. Copy the package's frontend/ directory into the repository root. Merge the supplied root README.md and .gitignore additions with the existing files, preserving any backend code and other teammates' work. Keep frontend/.env.example, but exclude real .env files, node_modules/, dist/, .git/, and private hosting metadata. Run npm ci, npm run lint, npm test, and npm run build inside frontend/. Review the diff, commit the frontend and documentation, and push normally to the repository's main branch. Do not force-push. If branch rules require a pull request, push a frontend branch and open a PR instead. Report the final branch, commit, and link.

The supplied repository layout is:

```text
README.md
.gitignore
frontend/
  package.json
  package-lock.json
  .env.example
  src/
  public/
  docs/
  README.md
  DECISIONS.md
  ASSET_CREDITS.md
  ...Vite, TypeScript, ESLint, and formatting configuration
```

## Validation and provenance

The source matches prepared commit `0e29b72fc31803f89bcbf0c74e9d15f1fa3dd274`. Lint, all 17 tests, and the production build passed after copying it into the target repository layout. Dependencies reported zero vulnerabilities at preparation time.

This commit was not pushed from the original machine because its GitHub login had expired. This archive contains source files, not Git credentials or local Git history. Your authenticated account must have write access to the target repository.

Conjunction metrics, agent exchanges, and cascade outcomes are sample data. The OMM catalog uses real SGP4 propagation. Hardware FPS and load-time targets remain unmeasured. The included `frontend/docs/demo.gif` is a short screen tour.
