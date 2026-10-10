# GeoIntelligence Hub GIS capability QA

## Verification run

The implemented spatial-statistics and drone-grid methods use small deterministic inputs with analytically known outputs. Run from the project root:

```powershell
python -B backend/test_spatial_statistics.py
python -B backend/test_drone_mining.py
python -B backend/test_analysis_registration.py
python -B backend/test_mocked_integrations.py
python -B backend/test_live_integrations.py
backend\venv\Scripts\python.exe -B -m unittest discover -s backend -p "test_*.py" -v
```

Static audit found 54/54 unique existing Earth Engine backend analysis IDs represented in the rule-based planner, with no unmatched IDs. The new spatial-statistics and drone methods are on separate registered local routes. The Earth Engine test is deliberately skipped because no safe real test project/AOI is configured. The frontend production build completed successfully; existing chunk-size and duplicate dynamic-import warnings remain.

The full backend regression discovery run completed **38 tests: 37 passed, 1 live Earth Engine integration skipped**. It includes existing classifier, spectral-index, trend, sensor-mapping and AHP/suitability unit tests plus the new spatial-statistics and drone tests. The backend venv uses Python 3.10.11; `google.api_core` emitted its support-window `FutureWarning`, so plan a Python 3.11+ runtime upgrade.

## Spatial statistics

| Method | Status | Output and validation | Limits |
|---|---|---|---|
| Global Moran's I | Implemented | Moran I, expected I, permutation p-value and permutation count; explicit binary or inverse-distance weights; explicit threshold or k-nearest | Local metric plane only; maximum 1,000 points; permutation p-values are conditional on exchangeability and weights |
| Local Moran's I | Implemented | Local I, raw permutation p, BH q, cluster/outlier class only after q≤0.05 | Maximum 500 points; BH under spatial dependence is approximate |
| Getis-Ord Gi* | Implemented | Self-inclusive z, normal p and BH q; labels only after q≤0.05 | Normal approximation, not a permutation test; weight specification required |
| KDE | Implemented | Gaussian intensity grid, bandwidth and density output | Requires AOI and bandwidth; no edge correction; intensity is not probability |
| Nearest neighbour | Implemented | Clark–Evans R, z and normal p | No edge correction; CSR/homogeneous Poisson assumption; AOI required |
| Point-pattern statistics | Implemented | Ripley K and L(r)-r at declared radii | Descriptive only; no edge correction or Monte Carlo envelope, therefore no significance claim |
| IDW | Implemented | Point-sample interpolated grid with declared power | Requires numeric field/AOI; deterministic, no inferential uncertainty |
| Ordinary kriging | Implemented | Spherical variogram predictions and kriging variance | 8–100 observations; explicit sill/range/nugget required; stationarity/isotropy assumptions; no variogram fitting or residual cross-validation |
| Spatial sampling | Implemented | Seeded uniform random points inside Polygon/MultiPolygon | No stratification; WGS84 AOI limited to regional extent |
| Spatial regression | Implemented as GWR | Local coefficients/fitted values/residuals, R² and residual Moran permutation diagnostic | 8+ points, 1–8 predictors, explicit bandwidth; no local coefficient p-values; no spatial lag/error model |
| Zonal statistics | Existing Earth Engine workflow | Existing `/api/zonal` route and assistant workflow | Requires Earth Engine and a supported raster analysis; no real-account integration run in this QA |

All point methods validate GeoJSON Point geometries, finite values, field presence and WGS84 coordinates. Distance workflows use a local regional metric approximation and reject extents wider than five degrees. Cell grids are limited to 2,500 cells (KDE/IDW), 100 cells (kriging), and documented sample/permutation workload caps.

## Drone and mining

| Method | Status | Inputs / reported output | Limits |
|---|---|---|---|
| DSM/DTM surface metrics | Implemented for supplied grids | Elevation range/mean, finite-difference slope, native CRS, affine resolution and units | Requires user-prepared projected metric JSON grid; not a GeoTIFF reader |
| DEM difference / terrain change | Implemented | Aligned before/after grids, per-cell difference, cut/fill sums | Exact grid alignment required; no co-registration workflow |
| Cut and fill | Implemented | Positive and negative volume from elevation difference × affine pixel area | Grid vertical/horizontal units must be metres; no uncertainty unless supplied |
| Stockpile volume | Implemented | Per-cell prismatic column integration against aligned reference or explicit horizontal/tilted plane; explicit footprint mask required | Does not infer a base; vertical accuracy is an optional conservative bound and does not include registration/footprint error |
| Excavation volume | Implemented | Cut/fill against explicit reference/plane and footprint mask | Same assumptions as stockpile workflow |
| Point-cloud inspection | Partial, implemented descriptive XYZ inspection | Count, XYZ extent, Z range/mean; map sample (up to 5,000) | No LAS/LAZ reader, classification, meshing or denoising; accepts uploaded JSON XYZ only |
| Orthomosaic NDVI | Implemented for supplied bands | NDVI per pixel from aligned calibrated red/NIR reflectance grids | Does not generate orthomosaics; raw digital numbers are rejected |
| Photogrammetry / orthomosaic generation | Not implemented | Requires OpenDroneMap/WebODM, Metashape or equivalent engine | No ODM/Metashape, PDAL, rasterio, laspy, Open3D or GDAL tools were available in backend venv |
| Building/road extraction | Not implemented | Requires suitable trained detector/segmentation model and validation imagery | No supported model weights or independent validation set available |
| Geological lineaments | Not implemented | Requires geological/remote-sensing methodology and suitable imagery/DEM validation | Generic edge detection is not labeled as geological evidence |
| Mineral prospectivity | Not implemented as a dedicated model | Must use documented, user-supplied evidence layers/weights and independent validation | No confirmed deposits or validated evidence layers are available; prospectivity must not be reported as a discovery |

Elevation JSON schema: `crs`, `horizontalUnits: "m"`, `verticalUnits: "m"`, `verticalDatum`, `transform: [x0,pixelX,rowX,y0,pixelY,rowY]`, and rectangular `values`. DEM comparisons/volume also require matching `verticalDatum` metadata. For volume methods include a same-sized boolean `mask` and either an aligned `reference` grid or `basePlane: {type:"horizontal", elevationM:..., verticalDatum:...}` / `{type:"plane", a:..., b:..., c:..., verticalDatum:...}`. Metric coordinate transforms are supported for UTM without extra libraries; other projected EPSG CRSs need `pyproj`. Web Mercator is rejected for volume because of area distortion.

Orthomosaic JSON has aligned `bands.red` and `bands.nir` grid objects with `units: "reflectance"`. Point-cloud JSON has `crs`, `units: "m"`, and `pointCloud` as a FeatureCollection of Point coordinates `[x,y,z]`.

## Assistant, maps and exports

Spatial-statistics and verified drone methods have rule-based planner entries and login-protected local backend routes; they do not require an Earth Engine token. Existing EE analyses continue through their prior `/api/analyze` and export routes. Computed vector-cell outputs are added to the interactive map, with property popups, numeric color ramps or evidence-based categories, statistics, per-feature tables, charts where defined, GeoJSON and CSV downloads.

These locally computed grid outputs are vector-cell GeoJSON, not GeoTIFF. GeoPackage and PDF exports are not implemented for these results. Existing Earth Engine GeoTIFF/vector exports remain separate and need a working EE session. No project/database schema changes or destructive project operations were made.

## Test categories and current evidence

- **Unit:** `test_spatial_statistics.py` checks a known chain Moran value, p/q bounds, CSR workflows, interpolation grids, sampling repeatability, GWR on an exact linear relation, and input/weights rejection.
- **Unit:** `test_drone_mining.py` checks known UTM coordinates, exact 12 m³ cut/12 m³ fill cases, grid alignment rejection, a known 45° planar slope, XYZ point-cloud checks and calibrated-reflectance NDVI.
- **Mocked/static integration:** `test_analysis_registration.py` verifies planner registrations, API route constants, backend routes and preserved upload parser integration; it does not exercise a running HTTP server.
- **Mocked integration:** `test_mocked_integrations.py` stubs only coordinate conversion and verifies the actual volume calculation-to-GeoJSON output path.
- **Real integration:** `test_live_integrations.py` is skipped because this checkout has no configured Earth Engine test project/AOI. No live Earth Engine, large real-world raster, model inference, or photogrammetry run is claimed.
