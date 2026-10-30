# Engineering decisions and implementation boundaries

This frontend prioritizes the complete hackathon narrative with a stable API boundary. The original handoff remains the target specification; items below explain the implementation choices and remaining acceptance work.

## Data is synthetic; orbit propagation is real

The default MSW catalog contains exactly 33,482 deterministic records. It approximates the requested payload/debris/rocket-body mix and LEO, polar, MEO and GEO shells. Named objects support the story, but their orbital elements are demonstration fixtures, not current tracking data. All mock epochs and TCAs are anchored to application load rather than a historical date.

The worker initializes native OMM records with satellite.js 6. Catalog IDs remain numeric, including six- to nine-digit IDs. No TLE conversion is used. The worker has a nominal 200 ms interval after each propagation completes, so actual update frequency depends on compute time. Zero-copy transfer applies to the returned position buffer; new buffers are allocated in the worker, and scene attributes are replaced per update. The render shader interpolates between position samples.

Miss distances, covariance, Pc, burns and secondary collisions are authored fixtures. They are not calculated from the two displayed catalog orbits. The encounter view anchors to the primary's TCA position and draws magnified illustrative paths; it is labeled accordingly. Replay range follows the supplied miss distance and relative speed. Option previews communicate a proposed change, rather than integrating thrust and orbital dynamics. The backend must provide validated screening and maneuver results for any operational use.

## Rendering choices

Earth uses local WebP day/night/cloud textures, a dedicated water mask (`earth-water.png`), custom terminator and atmosphere shaders, an approximate solar vector and sidereal rotation. A dedicated terrain bump map is not yet used. Clouds are a separate sphere. The atmosphere radius is 1.021 Earth radii.

The swarm is one Points draw call with class attributes, screen-sized cores and debris flicker. It uses NormalBlending to preserve saturated red and orange without clipping the cores. The user's follow-up overrides the handoff palette: satellites are red (`#ff5d66`), debris remains orange, and object visibility stays persistent during selection. Clicking an object opens the dedicated Object Inspector in place of the threat rail without moving the camera or dimming the swarm. The explicit **Focus object** action moves the camera. The inspector shows perigee/apogee, period, inclination, eccentricity and element epoch. Scene labels use fixed pixel sizing rather than distance scaling. A periodically rebuilt screen-space grid supports picking. This avoids per-object React nodes, but the picking grid allocates cells and is a performance profiling target. Orbit trails are sampled SGP4 paths for selected objects. An illustrative satellite model appears in selected detail contexts.

The scene uses ACES tone mapping, renderer antialiasing and a CSS vignette. Full postprocessing bloom, SMAA, film grain, Milky Way and lens flare from the handoff are not implemented. Point shaders supply the restrained luminous treatment without another render pipeline.

Quality is initially selected from hardware concurrency and can be changed in Settings. It is not a measured GPU-tier classification. Performance mode lowers stars and pixel ratio and removes clouds; all catalog objects remain available. Camera transitions follow an arc outside Earth. The current intro opens at a distant view and then transitions to the overview; it does not sequence separate GEO/MEO/LEO shell reveals.

## Cascade is an analytic visual approximation

The API returns parent OMM, fragment count, velocity-spread parameters, seed, yearly totals and secondary-event parameters. No 25-year position history is downloaded. A seeded shader smears points along the parent orbital plane and fans their nodes and inclinations out over time. This resembles differential periods and J₂ drift visually; it is not an implementation of a validated breakup or long-term conjunction model. The current shader uses the spread standard deviation; the mean spread parameter is retained in the API contract for a fuller physical model.

The 25-year sample collision case creates 12,784 fragments and includes secondary events at years 8.4 and 17.2. Their population effects are fixture values; their locations render as event rings and seed independent smaller fragment clouds. Planned launches are an illustrative baseline scenario. The UI labels the model approximate.

## AI and operator boundaries

The standalone negotiation is an SSE script with delays and weighted scores. Ask Sentinel streams a canned answer selected from the question. Neither calls Amazon Bedrock directly; the backend owns that integration. Sample signatures describe the agents' planning agreement, not authenticated operator signatures.

The API contract includes no dispatch or burn-command operation. Mock dispatch explicitly stages a sample plan and contacts nobody. In live mode, the UI reports that dispatch is unavailable rather than pretending it succeeded. Human override is a local planning record and has no spacecraft effect.

## Product and code tradeoffs

React 18, Vite, strict TypeScript, React Three Fiber 8, Drei, Zustand, TanStack Query, Comlink, satellite.js, MSW and self-hosted Fontsource packages follow the proposed stack. React Router is upgraded to 7.18.5 and Vitest to 5.0.5; use Node.js 22.12+ or 24+. The final dependency audit reported zero vulnerabilities. The redesigned UI uses Archivo 400/500/600 for its heading hierarchy and graphite surfaces with squared rails, authored CSS and shared tokens. Styles are global feature-scoped selectors rather than CSS Modules. Dialog behavior uses Radix; other native controls retain browser semantics. UI motion uses CSS and requestAnimationFrame rather than a separate animation timeline dependency.

One canvas persists between views. Routes are lazy loaded; the Three.js vendor group is split separately. Manual chunks do not establish compliance with the 400 KB gzip initial-JavaScript budget: the scene/vendor and mock-runtime costs must be measured together from a production load. The current build should be treated as a functional demo before that optimization target is signed off.

Responsive Mission Control uses layer/threat tabs. `/alert/:id` provides a dedicated phone alert with countdown, key encounter numbers, recommended burn, option review and acknowledgment. Settings and override state are local to the session. The global clock intentionally stops at the seven-day screening horizon, and Cascade Lab uses an independent year clock.

## Acceptance still requiring measurement

Automated tests verify formatting, clock behavior, coordinate mapping, OMM initialization and representative propagation, SSE framing and mock contracts. Browser QA verified the Earth textures and visible red/orange swarm after a reserved GLSL identifier causing shader failure was corrected. A fresh startup produced no browser warnings or errors. The verified demo interactions are listed below. GPU performance is unmeasured. Benchmark the 33k view on an identified mid-range integrated GPU and a low-tier device; measure first meaningful frame and gzip transfer sizes; review keyboard, mobile and reduced-motion behavior in-browser. The FPS overlay is a development aid, not evidence of a completed benchmark.

Final browser verification: the refreshed desktop app started without console errors or warnings. Object lookup and the ISS inspector, encounter replay, recommended maneuver preview, streamed negotiation through agreement, the human override dialog, cascade execution and year-25 secondary-event totals, and a streamed Sentinel answer were verified. At 390 px width, the alert route displayed correctly without horizontal overflow and acknowledgement updated its session status. [`docs/demo.gif`](docs/demo.gif) is a short walkthrough assembled from captured demo screens; it is a screen tour rather than a real-time recording. Hardware FPS and load-time targets remain unmeasured.
