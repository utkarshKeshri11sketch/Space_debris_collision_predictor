# OrbitSentinel

A standalone mission operations frontend for the Anvathon demo: a persistent Earth scene, a 33,482-object orbital catalog, conjunction analysis, streamed operator negotiation and an illustrative debris cascade.

**The default experience uses sample data.** Catalog entries, conjunctions, collision probabilities, burns, agent messages and cascade outcomes are synthetic demonstration fixtures. Real SGP4 propagation renders the synthetic OMM catalog. No live screening, Amazon Bedrock call, operator message or spacecraft command occurs in mock mode.

## Run locally

Use Node.js 22.12 or later (or Node.js 24+) and npm. From this directory:

```sh
npm install
npm run dev
```

Open the Local URL printed by Vite. No backend, API keys or environment file is required. Dependencies must be downloaded once; the running demo then uses bundled fonts, textures and MSW responses. This is not an installable offline PWA.

```sh
npm run build       # TypeScript strict check + static production bundle in dist/
npm run preview     # Serve the built bundle locally
npm test            # Vitest unit and contract tests
npm run lint        # ESLint
npm run format      # Format source with Prettier
```

The MSW service worker is committed at `public/mockServiceWorker.js`. If upgrading MSW, refresh it with `npx msw init public`.

## Demo in three minutes

Use a desktop browser with WebGL enabled. For a repeatable narration, leave the global clock at 1× until demonstrating time controls.

| Time | Action | What to explain |
| --- | --- | --- |
| 0:00–0:20 | Open `/` in a fresh browser session; allow the intro or use **Skip intro**. | One shared orbital environment; 33,482 synthetic OMM objects. |
| 0:20–0:45 | Toggle satellites/debris, compare LEO/MEO/GEO, then restore **All**. | Red payloads, orange debris and pale rocket bodies. Search `25544` with Ctrl/⌘+K to select ISS. |
| 0:45–1:20 | Open the critical ISS row: `/conjunctions/iss-cosmos`. Press **Replay encounter**, then select **Option A**. | 412 m miss, Pc 3.1 × 10⁻⁴, 14.2 km/s relative speed. The sample 0.42 m/s burn raises modeled miss distance to 4.2 km. Display geometry is magnified for legibility. |
| 1:20–2:05 | Open `/conjunctions/starlink-oneweb`; choose **Start operator negotiation**. Alternatively use the **Negotiator** tab. | Both objects can maneuver. Watch the sample SSE debate, weighted scores and signed recommendation. Open **Human override** to show operator control. |
| 2:05–2:45 | Open **Cascade Lab** (`/cascade`). Choose **SL-16 R/B**, **Collision**, **25 years**, then **Run simulation**. | An illustrative fragment cloud becomes a debris band. Scrub through year 8.4 and 17.2 to show secondary events; compare the tracked-population curves. |
| 2:45–3:00 | Open **Ask Sentinel**, enter “Is the ISS safe this week?” and press Enter. | A sample answer streams from the same API boundary the real backend will implement. Close with the need for human flight approval. |

The intro plays once per browser tab session. To replay, clear the `orbit-intro` sessionStorage key or open a new browser session. Clicking a dot opens the Object Inspector in place of the threat rail while keeping the camera and swarm visible. It shows perigee/apogee, period, inclination, eccentricity and element epoch; choose **Focus object** to move the camera explicitly. `Space` pauses the global clock; `[` and `]` change between 1×, 60×, 600× and 3600×; `F` focuses selection; `Esc` returns to the overview; `?` opens shortcuts. Drag the scene to rotate and scroll to zoom. **Settings → Performance** lowers star count and render resolution while keeping the complete catalog. Development builds expose an FPS overlay with Shift+D.

On narrow screens, Mission Control uses panel tabs. Open `/alert/iss-cosmos` for the dedicated alert with countdown, key encounter numbers, recommended burn, option review and acknowledgment.

## Connect the team's backend

Copy `.env.example` to `.env.local` and configure:

```dotenv
VITE_USE_MOCKS=false
VITE_API_BASE_URL=https://your-fastapi-origin.example
```

Restart Vite after editing environment values. For production, set them **before** `npm run build`; Vite embeds these public values into the bundle. Do not put secrets or AWS credentials in `VITE_*` variables. Leave the base URL empty when `/api` is served from the same origin. Include an optional path prefix in the base URL only if the server expects that prefix before `/api`.

The browser only calls your backend. It never downloads CelesTrak data. The backend owns catalog caching, conjunction screening, Pc/covariance calculations, burn recommendations, Bedrock calls and production authentication. For a separate API origin, configure its CORS policy to allow the frontend origin and the required GET/POST requests and headers. The current client does not add authentication tokens or cross-origin cookie credentials; adapt `src/api/client.ts` if the deployed API requires them.

| Method | Path | Frontend use |
| --- | --- | --- |
| GET | `/api/catalog` | Full `CatalogObject[]` with raw OMM fields |
| GET | `/api/catalog/meta` | Count, object classes, sync epoch and source |
| GET | `/api/conjunctions?days=7&minPc=1e-6` | Risk-ordered watch list |
| GET | `/api/conjunctions/:id` | Covariance, range series, options and brief |
| POST | `/api/negotiations` | `{ conjunctionId }` → `{ negotiationId }` |
| GET | `/api/negotiations/:id/stream` | SSE `NegotiationEvent` objects |
| POST | `/api/cascade` | `{ noradId, event, years, includeLaunches }` → parameters and yearly totals |
| POST | `/api/ask` | `{ question }` → streamed answer tokens |

Types are defined in `src/api/types.ts`. Times are ISO 8601 UTC; miss distances are metres, positions kilometres, relative speeds km/s, delta-v m/s and propellant kg. Catalog IDs remain numeric up to nine digits. OMM records are initialized directly with `satellite.js`'s `json2satrec`; no TLE strings are produced.

SSE uses fetch streaming, including for the POST question endpoint. Emit UTF-8 `data: <JSON>\n\n` frames with `Content-Type: text/event-stream`; finish with `data: [DONE]\n\n` or close the stream. Negotiation events follow the discriminated union in `types.ts`. Question tokens may be JSON strings, `{ "type": "token", "text": "..." }`, `{ "token": "..." }` or plain data text. Disable proxy buffering and keep streaming requests open. AbortSignals cancel route-owned negotiation requests.

The contract has no operator dispatch endpoint. **Send plan to both operators** performs an explicitly labeled sample dispatch in mock mode; live mode reports that dispatch is not configured. Human overrides record a local planning decision only.

## Architecture

```text
src/app/          Persistent shell, navigation, palette, time controls
src/features/     Conjunction, negotiation and cascade screens
src/scene/        Earth, stars, object cloud, trails, encounter and GLSL shaders
src/api/          Typed fetch/SSE client, Query hooks, MSW handlers and fixtures
src/sim/          Shared Zustand clock, native OMM adapter, Comlink SGP4 worker
src/lib/          Units, probability/time formatting and seeded random helpers
src/styles/       Design tokens and global responsive layout
src/ui/           Shared SVG icon vocabulary
```

One canvas remains mounted across routes. React Query caches the catalog; a dedicated worker initializes its SGP4 records, propagates positions, and transfers Float32Array buffers to the scene. The renderer interpolates between buffers. TEME maps to Three coordinates as `(x, z, -y) / 6378.137`; Earth rotates with Greenwich sidereal time. A separate procedural shader expands the cascade from its returned seed and parameters. The shared simulation clock drives the orbital view and countdowns; Cascade Lab intentionally has its own year-scale playback.

## Static hosting

Publish the contents of `dist/` at the site root. No Node server is needed in production. Keep textures, fonts, worker bundles and `mockServiceWorker.js` accessible from their generated paths. MSW requires a secure context: localhost works for development; use HTTPS for hosted demos.

For S3 + CloudFront, use `index.html` as the default document and route application paths such as `/conjunctions/iss-cosmos` back to it. With a private S3 origin, an unknown object can return 403 as well as 404; configure the relevant SPA fallback to `/index.html` with response status 200. Keep real asset/API errors observable and route `/api/*` to the backend when sharing a distribution. See [CloudFront custom error responses](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/GeneratingCustomErrorResponses.html).

For Amplify Hosting, use the Vite build command and `dist` output directory, with a SPA rewrite to `/index.html`. See [Amplify redirects and rewrites](https://docs.aws.amazon.com/amplify/latest/userguide/redirects.html). Serve generated hashed assets with long caching; avoid long immutable caching for `index.html` and the mock service worker. Deployment to a subdirectory requires adjusting Vite base paths, router basename and public asset/service-worker URLs.

## Verification and limitations

The automated suite covers unit formatting, SSE chunk boundaries, clock controls/horizon, coordinate conversion, OMM initialization with nine-digit IDs, catalog consistency, representative seven-day propagation and cascade response constraints. It does not validate physical collision probabilities or flight safety.

Browser QA verified a 1440 × 900 view with Earth textures and the visible red/orange object cloud. A fresh startup produced no browser warnings or errors. Object search, the ISS inspector, conjunction replay, the recommended-burn preview, streamed negotiation through agreement, the human override dialog, cascade execution through year 25, and a streamed Sentinel answer were verified. At 390 px width, the alert route displayed without horizontal overflow and acknowledgement updated its session status. The [demo GIF](docs/demo.gif) is a screen tour assembled from captured screens rather than a real-time recording. GPU performance remains unmeasured. Do not treat the handoff's 60 fps, 30 fps low-tier, 2.5 s first-frame or 400 KB gzip goals as measured results. Record the browser/device and production-build numbers before claiming those budgets. The final dependency audit reported zero vulnerabilities. `DECISIONS.md` records the current simplifications; `ASSET_CREDITS.md` records bundled visual and font sources.
