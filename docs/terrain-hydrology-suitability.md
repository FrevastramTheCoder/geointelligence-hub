# Terrain, hydrology, flood, and suitability workflows

## Terrain products

Terrain analyses use `USGS/SRTMGL1_003` elevation in metres (nominal 1 arc-second, about 30 m near the equator; coverage is not global). Slope/aspect/hillshade use Earth Engine terrain products. Added products are:

- `curvature`: 3×3 discrete Laplacian, reported in elevation metres per pixel squared; this is not a geodetic profile/plan curvature decomposition.
- `tri`: 8-neighbour root-mean-square elevation difference (Riley-style TRI), in metres.
- `tpi`: DEM minus the circular 3-pixel-radius neighbourhood mean, in metres. Scale changes the landform interpretation.
- `twi`: `ln(specific contributing area / tan(slope))`, with MERIT Hydro `upa` (km²), a nominal 90 m contour width, and SRTM slope. It is a topographic index, not soil-moisture measurement.

All use the AOI and return an Earth Engine map tile, statistics, legend, and an image export. SRTM voids and high-latitude resolution differences remain properties of the input dataset.

## Hydrology

The hydrology workflow reads `MERIT/Hydro/v1_0_1` (~90 m). Its conditioned `dir` band supports mapped flow-direction codes and `upa` supports accumulated upstream area and thresholded drainage extraction. For drainage, pass one positive `thresholds` value in km²; the default extraction threshold is 10 km². `variable` accepts `flow_direction`, `flow_accumulation`, `drainage`, or `catchment_statistics`.

MERIT `upa` is not a Strahler stream-order field. The current runtime has no raster D8 routing library or graph solver, so exact Strahler order and pour-point watershed delineation are reported as unsupported instead of being inferred from upstream-area classes. Catchment statistics summarize upstream area within the AOI; they do not represent a new watershed boundary. A snapped pour point plus a validated flow-routing engine is required to add exact outlet delineation.

## Flood workflows

- `flood_mapping` uses Sentinel-1 IW VH annual median backscatter and a documented `< -18 dB` open-water screen. A single year maps water. For two periods, send `mode: "compare"`, `year2` (before) and `year` (after); the output includes persistent dry, new water, receded water, persistent water, and new-water area. Annual medians can capture seasonal/permanent water change; they do not prove a flood event.
- `flood` is a susceptibility screening index from SRTM elevation and slope, CHIRPS annual rainfall (mm), and MERIT upstream area. Four monotonic 0–1 transforms are equally weighted for an exploratory map; class breaks are 0.25 intervals. This is not a calibrated probability, observed flood extent, exposure-based risk estimate, or hydraulic flood-depth model.

Sentinel-1 annual composites are only returned when overlapping IW/VH scenes exist. SAR can miss water under vegetation and buildings; threshold and dates need local event validation.

## WLC and AHP suitability

Suitability requires user-supplied weights or a pairwise AHP matrix. There are no default weights. The current configured uses are agricultural, residential, and urban environmental screening; solar requires an irradiance layer, while infrastructure and conservation need road/access or ecological criteria not configured in this runtime.

Request WLC with explicit criterion weights, for example:

```json
{"analysis":"suitability","use":"agricultural","weights":{"slope":40,"rainfall":30,"landcover":30},"constraints":{"excludeWater":true,"maxSlope":25}}
```

Request AHP with ordered criteria and a reciprocal Saaty matrix:

```json
{"analysis":"suitability","suitabilityMethod":"ahp","criteria":["slope","rainfall","landcover"],"pairwiseMatrix":[[1,2,3],[0.5,1,2],[0.333333,0.5,1]]}
```

Weights are normalized to sum to one. AHP uses the geometric-mean priority vector and rejects a consistency ratio above 0.10. Criteria use documented fixed screening transforms: inverse slope on 0–30°, NDVI −1..1 mapped to 0..1, rainfall 0–2000 mm/year, inverse elevation 0–3000 m, flood-prone low/flat pixels as a binary cost factor, and ESA WorldCover ordinal compatibility values included in result statistics. These scales are assumptions for a relative ranking, not universal agronomic, engineering, or ecological standards.

Constraints are opt-in (`excludeWater`, `maxSlope` degrees); masked cells are omitted from class-area summaries. The classified raster is displayed and exported. Optional `scenarios` accepts up to six `{name, weights}` alternatives; optional `sensitivity` accepts `true` or `{perturbation: 0.1}` and reports the mean-score change after perturbing each selected weight. CHIRPS has a coarser native grid than SRTM; alignment does not add spatial detail.

## Verification status

Pure-Python WLC/AHP validation, normalization, and pairwise consistency tests are in `backend/test_spatial_analysis.py`. The Earth Engine expressions and request integration are syntax-checked and frontend intents are exercised through the Vite module loader. An authenticated Earth Engine run is required to verify dataset availability and retrieve real AOI outputs; this workspace currently has no configured Earth Engine project connection. No data-derived map values are claimed by the local tests.
