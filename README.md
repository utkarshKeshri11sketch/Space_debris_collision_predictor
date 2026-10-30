# Space_debris_collision_predictor
Space debris is growing fast, but satellite operators lack a clear, early way to predict collisions, decide who should move, and understand the long-term risk of a single breakup.

## OrbitSentinel frontend

The complete React and TypeScript frontend is in [`frontend/`](frontend/). It runs standalone with sample data and includes a persistent 3D Earth, a 33,482-object OMM catalog, conjunction analysis, operator negotiation, Cascade Lab, mobile alerts, and object inspection.

### Run locally

Use Node.js 24 or Node.js 22.12 and later.

```sh
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite. No backend or API key is needed for the sample-data demo.

```sh
npm run lint
npm test
npm run build
```

The production build is written to `frontend/dist/`. For a real backend, create `frontend/.env.local` from [`.env.example`](frontend/.env.example), set `VITE_USE_MOCKS=false` and `VITE_API_BASE_URL`, then restart or rebuild.

- [Frontend setup, API contract, architecture, and three-minute demo guide](frontend/README.md)
- [Engineering decisions and model limitations](frontend/DECISIONS.md)
- [Texture and font credits](frontend/ASSET_CREDITS.md)
- [Demo walkthrough GIF](frontend/docs/demo.gif)

The demo uses synthetic conjunction metrics, agent messages, and cascade outcomes. Real SGP4 propagation renders the synthetic OMM catalog; mock mode sends no operator messages or spacecraft commands.
