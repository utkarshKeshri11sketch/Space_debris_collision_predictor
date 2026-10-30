# Contract and integration requests

## Screening -> Lead / Data / Physics

1. `main` currently contains no backend skeleton or `app/models.py`. Screening
   returns dictionaries matching the frontend exactly; Lead can validate them
   through shared Pydantic models when those land. Please add runtime NumPy
   and `sgp4` dependencies to the global backend dependency/deployment files.
2. Data: supply cached frontend `CatalogObject` records with full OMM fields.
   Screening never fetches remotely or bypasses the two-hour refresh limit.
   Missing/invalid records are reported in `ScreeningRun.issues`.
3. Lead: `GET /api/conjunctions` specifies only `days` and `minPc`. The product
   also requires screening a selected satellite. Please define the protected
   primary IDs and aggregate cached runs, or approve an optional `noradId`
   query parameter. No frontend/contract changes were made by Screening.
4. Lead: public GP has neither covariance nor dimensions. Explicitly supply
   `risk_model(primary, secondary, tca) -> EncounterUncertainty`: each object's
   RTN position covariance **at TCA** in m^2, combined hard-body radius in m,
   provenance, and illustrative flag. Do not present guessed values as
   measured. Detail briefs always retain the provided provenance.
5. Physics: `Encounter` retains both TCA states and the original catalog
   records. Helpers are `record_from_catalog`, `state_at`, `rtn_basis`, and
   `collision_probability`. `run.get_detail(id, options=..., brief=...)`
   accepts your manoeuvre options and AI's assessment; optional `afterSeries`
   should be attached by the integration layer when a real burn curve exists.
6. Lead: keep each run in cache so IDs from list/detail remain consistent.
   Precompute full-catalog screening on refresh/a worker, rather than every
   API request. Log/surface `issues` and `complete=False`; unsupported slow
   encounters or failed objects must not appear as a clean screening result.
7. Contract owner: the frontend's ellipse draws literal R/N axes. A general
   encounter plane is perpendicular to relative velocity and is not exactly
   R/N. `covariance.angleDeg` is relative to projected primary radial in that
   plane; `rtnM` is real primary RTN. Please decide whether to label the
   existing view schematic or eventually add plane-coordinate fields.
8. Lead/Data: provide a timestamp-matched SOCRATES snapshot for external
   comparison. No claim of SOCRATES validation or 30k-object Lambda timing
   has been made. Search settings and assumptions are in
   `tests/screening/README.md` and module comments.

The AI branch also has requests in its copy of this document. Preserve both
agents' entries when integrating these branches.
