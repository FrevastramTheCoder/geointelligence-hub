# Missing Analysis Roadmap

**Audit date:** 2026-10-10. Priorities address scientific reliability and executable gaps without replacing the current assistant or analysis engine.

## P0 — Trustworthy intent-to-execution path

- Keep the planner registry, backend `IMPLEMENTED_ANALYSES`, and capability status aligned. Add a check that every planner backend name has a registered runtime path.
- Add a searchable methodology catalog for unknown and not-yet-executable requests. Return method, required inputs, limitations, and an explicit implementation status; never route a knowledge-only result to analysis execution.
- Capture unsupported method requests locally as capability-gap records for future review. The initial implementation is browser-local; multi-user centralized triage requires a server endpoint and retention policy.
- Keep the current named analysis engine and assistant intact. Do not execute generated arbitrary code.

## P1 — Scientific guardrails on existing workflows

- Land-cover: label output as agreement with WorldCover-derived reference samples, not independent field accuracy. Preserve confusion matrix/class support; add producer's/user's accuracy and F1 only from a defined held-out matrix. Add geographically blocked validation before claiming spatial generalization.
- Suitability: expose criterion normalization, hard constraints, and defaults before execution; require user weights or explicit acceptance of the stated default scenario. Add sensitivity scenarios and preserve weights in result metadata.
- Flood: use precise terms for observed Sentinel-1 extent, terrain susceptibility, hazard and risk; do not show risk probability/depth without calibrated data and a validated model.
- Indices: use explicit sensor-band tables, reflectance scaling, QA masks, observation count, units, and context-specific threshold wording. Add tests for band mapping and formulas.
- Change/time series: require comparable season/windows and report sensor, temporal availability and matched observation counts. Flag cross-sensor comparisons.

## P2 — Core vector and raster GIS operations

- CRS inspection and explicit reprojection with datum-operation provenance; geometry validity checks and topology diagnostics.
- Implemented first: pairwise polygon intersection for uploaded WGS84 Polygon/MultiPolygon layers (2,500-pair ceiling), with input validation, overlap area/statistics, map layer and GeoJSON/CSV export. Remaining: clip, union, difference, dissolve and spatial joins, with CRS/unit and geometry-type rules.
- Raster metadata inspection, alignment, categorical/continuous resampling policy, mosaic and nodata handling. Do not reproject by relabeling.
- Add spatial-indexed local vector operations only where size limits and CRS are known; otherwise use a configured server-side engine.

## P3 — Spatial statistics and geostatistics

- Point-pattern diagnostics, nearest-neighbor and kernel density with stated bandwidth and edge effects.
- Global/local Moran and Getis-Ord Gi* with selectable spatial weights, null/permutation design, multiple-test correction, and significance legend.
- Spatial regression/GWR with diagnostics and leakage-aware spatial cross-validation.
- IDW and kriging only after input-density checks, empirical variograms, cross-validation, uncertainty surfaces and stationarity review.

## P4 — Hydrology, terrain and environmental models

- User-defined watershed delineation using a selected conditioned DEM, outlet snap, flow algorithm, threshold, and validation against known drainage.
- Rainfall-runoff, flood depth/probability and risk require calibrated inputs, reference events, exposure/vulnerability data and independent evaluation.
- Improve drought, erosion, soil moisture and carbon/biomass methods only with suitable datasets, units and validation; clearly label proxies.

## P5 — GeoAI, photogrammetry and mining

- Add semantic segmentation/object detection only after an inference runtime, named model artifact/version, license, input schema, confidence output and geographic validation are configured.
- Add drone SfM/DSM/DTM and point-cloud workflow only with a compatible external engine, GCP/checkpoint support and uncertainty report.
- Expand mineral prospectivity only with geological layers, occurrence data, bias-aware sampling, spatial holdout, confidence and field/lab qualification.

## P6 — Cartography and data engineering

- Reproducible report/map export including title, scale, CRS, units, legend, date range, source attribution, parameters and caveats.
- Add STAC/COG/PostGIS integrations only when deployment credentials, dependencies, API contracts, data lineage and resource controls are ready.
- Add job cancellation, progress, retry, cache invalidation and large-raster chunking without changing scientific semantics.

## Verification gates

For every method, report separate states: documented, understood by planner, registered, backend/local implementation, computation tested, results checked, and UI/export verified. Live Earth Engine tests require a valid user credential and a known AOI; no live GEE data computation is asserted by this source audit.
