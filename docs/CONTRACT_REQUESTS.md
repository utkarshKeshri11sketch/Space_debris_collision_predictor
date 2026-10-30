# Contract requests

Need a field, an endpoint, or something from another agent? Add an entry below. The Lead answers and,
if accepted, updates `backend/app/models.py`. Never edit `models.py` or the frontend yourself.

## Template

```
### <short title>
- From: <agent> (<branch>)
- To: Lead | Data | Screening | Physics | AI
- Date:
- Request: what you need and why
- Proposed shape: field names, types, units
- Status: open | accepted | rejected | done
- Answer:
```

## Open

### Real data catalog assertions
- From: Data (be-data)
- To: Lead
- Date: 2026-10-30
- Request: Update tests/test_api.py::test_catalog_and_meta to compare len(items) to /api/catalog/meta.objectCount and sum(byType), instead of mock_data.OBJECT_COUNT. The real bundled archive contains 28,124 objects; future refresh counts vary.
- Proposed shape: No API change. Assert items is nonempty, 25544 exists when appropriate, exact enum keys and count consistency.
- Status: open
- Answer:

### Compress the full catalog before the Lambda proxy response
- From: Data (be-data)
- To: Lead
- Date: 2026-10-30
- Request: Add catalog response compression in the Lead-owned ASGI/deployment layer. Measured full catalog: 14,589,722 JSON bytes; gzip level 6: 2,054,348 bytes. The complete JSON catalog exceeds Lambda's 6 MB buffered synchronous response limit. Configure gzip and the gateway binary response behavior, or serve the same array through a cached/static endpoint preserving the frontend contract. Do not silently truncate the catalog.
- Proposed shape: Same GET /api/catalog JSON array after HTTP decompression. GZipMiddleware is documented by Mangum, which base64-encodes responses with Content-Encoding=gzip; ensure the complete Lambda envelope remains below its limit. Validate at the deployed gateway too.
- References: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html ; https://mangum.fastapiexpert.com/http/
- Status: open
- Answer:

### Data configuration, scheduled refresh, and physics interface
- From: Data (be-data)
- To: Lead | Screening | Physics
- Date: 2026-10-30
- Request: Merge the settings documented in backend/app/data/.env.example into the Lead-owned backend/.env.example. Deploy app.data.refresh.refresh_handler separately with EventBridge rate(6 hours), S3 GetObject/PutObject on catalog and refresh-state keys, and recent boto3 conditional PutObject support. Use reserved concurrency 1 in addition to the S3 lease.
- Proposed shape: load_catalog()->list[CatalogObject] and catalog_meta()->CatalogMeta remain unchanged. For native OMM Satrec and optional owner/country/mean altitude, use load_orbit_catalog()->dict[int, OrbitRecord] from app.data.catalog. No extra JSON fields are introduced.
- Status: open
- Answer:

### Catalog coverage, historical archive, and verified maneuverability
- From: Data (be-data)
- To: Lead | Screening | Physics | AI
- Date: 2026-10-30
- Request: Confirm a documented bulk public OMM source if the demo must claim the entire current public catalog, including inactive payloads and unclassified objects. CelesTrak's documented active, NAME=DEB and NAME=R/B queries cover the requested active/debris/body categories but cannot guarantee every public object. No GROUP=all endpoint is assumed. The bundled 28,124-object archive is July 2025 data from satellite.js's real Space-Track OMM test archive; original epochs and historical source labeling are retained. Perform a successful current refresh before real-time screening and validate real name/NORAD associations instead of reusing the mocks' associations.
- Proposed shape: Preserve the existing API. active comes from SATCAT status or active-feed membership; missing evidence defaults false. maneuverable defaults false unless an active payload appears in operator-verified CATALOG_MANEUVERABLE_IDS. Supply capability data for real negotiations; current GP/SATCAT alone cannot verify propulsion capability. The archive lacks activity evidence and therefore reports active=false (unverified) and maneuverable=false.
- Status: open
- Answer:

## Closed

_None yet._
