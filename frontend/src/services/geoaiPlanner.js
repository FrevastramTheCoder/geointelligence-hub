/**
 * GEOAI PLANNER — central analysis registry + natural-language planner.
 *
 * Update, not rewrite: the GEE executor (useAnalysis/runAnalysis -> /api/analyze),
 * map layers, legends and auth stay untouched. This module only converts
 * natural language into a STRUCTURED request the existing engine executes.
 *
 * Every `backend` id here MUST exist in backend server.py _run_analysis_impl
 * (or be `local`). Discovery lists only these — never invent tools.
 *
 * Bilingual: pass ctx.lang ('en' | 'sw'); all user-facing replies translate.
 */
import { tr, blurbFor } from './assistantLang';
import { searchMethodologies, formatMethodologyReply } from './methodologyCatalog';

// ---------------------------------------------------------------------------
// Dataset registry — real GEE assets only (must match backend)
// ---------------------------------------------------------------------------
export const DATASET_REGISTRY = {
  sentinel2: { id: 'COPERNICUS/S2_SR_HARMONIZED', provider: 'ESA', resolution: '10m', coverage: '2015–now', bands: ['B2','B3','B4','B8','B11'], purpose: 'optical indices, classification' },
  landsat8: { id: 'LANDSAT/LC08/C02/T1_L2', provider: 'USGS/NASA', resolution: '30m', coverage: '2013–now', bands: ['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','ST_B10'], purpose: 'optical + thermal' },
  landsat9: { id: 'LANDSAT/LC09/C02/T1_L2', provider: 'USGS/NASA', resolution: '30m', coverage: '2021–now', bands: ['SR_B2','SR_B3','SR_B4','SR_B5','SR_B6','ST_B10'], purpose: 'optical + thermal' },
  srtm: { id: 'USGS/SRTMGL1_003', provider: 'NASA', resolution: '30m', coverage: 'static', bands: ['elevation'], purpose: 'terrain' },
  modis_lst: { id: 'MODIS/061/MOD11A1', provider: 'NASA', resolution: '1km', coverage: '2000–now', bands: ['LST_Day_1km'], purpose: 'land surface temperature' },
  chirps: { id: 'UCSB-CHG/CHIRPS/DAILY', provider: 'UCSB/CHG', resolution: '~5km', coverage: '1981–now', bands: ['precipitation'], purpose: 'rainfall' },
  sentinel1: { id: 'COPERNICUS/S1_GRD', provider: 'ESA', resolution: '10m', coverage: '2014–now', bands: ['VH','VV'], purpose: 'SAR flood mapping' },
  worldcover: { id: 'ESA/WorldCover/v200/2021', provider: 'ESA', resolution: '10m', coverage: '2020–2021', bands: ['Map'], purpose: 'land-cover reference' },
  dynamicworld: { id: 'GOOGLE/DYNAMICWORLD/V1', provider: 'Google', resolution: '10m', coverage: '2015–now', bands: ['label'], purpose: 'near real-time land cover' },
  openbuildings: { id: 'GOOGLE/Research/open-buildings/v3/polygons', provider: 'Google', resolution: 'vector', coverage: 'static', bands: [], purpose: 'building footprints' },
  s5p_no2: { id: 'COPERNICUS/S5P/OFFL/L3_NO2', provider: 'ESA', resolution: '~7km', coverage: '2018–now', bands: ['tropospheric_NO2_column_number_density'], purpose: 'NO2 concentration (mol/m²)' },
  s5p_so2: { id: 'COPERNICUS/S5P/OFFL/L3_SO2', provider: 'ESA', resolution: '~7km', coverage: '2018–now', bands: ['SO2_column_number_density'], purpose: 'SO2 concentration (mol/m²)' },
  s5p_co: { id: 'COPERNICUS/S5P/OFFL/L3_CO', provider: 'ESA', resolution: '~7km', coverage: '2018–now', bands: ['CO_column_number_density'], purpose: 'CO concentration (mol/m²)' },
  s5p_o3: { id: 'COPERNICUS/S5P/OFFL/L3_O3', provider: 'ESA', resolution: '~7km', coverage: '2018–now', bands: ['ozone_total_vertical_column'], purpose: 'O3 total column (mol/m²)' },
  modis_aod: { id: 'MODIS/061/MCD19A2_GRANULES', provider: 'NASA', resolution: '1km', coverage: '2000–now', bands: ['Optical_Depth_055'], purpose: 'aerosol optical depth' },
  modis_et: { id: 'MODIS/061/MOD16A2', provider: 'NASA', resolution: '500m', coverage: '2001–now', bands: ['ET'], purpose: 'evapotranspiration (mm/8day)' },
  merit_hydro: { id: 'MERIT/Hydro/v1_0_1', provider: 'MERIT', resolution: '90m', coverage: 'static', bands: ['upa','dir','elv'], purpose: 'flow accumulation + direction' },
  hansen: { id: 'UMD/hansen/global_forest_change_2023_v1_11', provider: 'UMD/GLAD', resolution: '30m', coverage: '2000–2023', bands: ['treecover2000','loss','lossyear','gain'], purpose: 'forest loss/gain' },
};

// ---------------------------------------------------------------------------
// Analysis registry — the ONLY place that maps words -> tools.
// `backend`: id sent to /api/analyze. `local`: computed in-browser.
// ---------------------------------------------------------------------------
export const ANALYSIS_REGISTRY = {
  ndvi: { category: 'vegetation', backend: 'ndvi', needsYear: true, needsSource: true,
    aliases: ['ndvi','vegetation','vegetation index','plant health','greenness','vegetation health','vegetation condition','vegetation cover','green cover','green areas','crop health','plant vigor','biomass','forest monitoring','vegetation loss','vegetation stress','vegetation density','show vegetation','analyze vegetation','show vegetaion','show vegation','vegation','vegetaion','vegetatio','vegtation','vegitation','vegatation','onyesha mimea','afya ya mimea','mimea','ukijani','uoto','woto'],
    blurb: 'NDVI vegetation health (Sentinel-2/Landsat)' },
  evi: { category: 'vegetation', backend: 'evi', needsYear: true, needsSource: true,
    aliases: ['evi','enhanced vegetation index'],
    blurb: 'EVI vegetation index (less soil/atmosphere bias)' },
  evi2: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'EVI2',
    aliases: ['evi2','evi 2','two-band enhanced vegetation index'], blurb: 'EVI2 two-band vegetation index' },
  ndmi: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'NDMI',
    aliases: ['ndmi','normalized difference moisture index','normalized difference moisture'], blurb: 'NDMI vegetation moisture index' },
  nbr: { category: 'change', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'NBR',
    aliases: ['nbr','normalized burn ratio','burn ratio'], blurb: 'NBR normalized burn ratio' },
  dnbr: { category: 'change', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'DNBR',
    aliases: ['dnbr','d-nbr','burn severity','burn severity mapping','differenced normalized burn ratio'], blurb: 'dNBR pre-fire minus post-fire burn severity screening' },
  ndsi: { category: 'snow', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'NDSI',
    aliases: ['ndsi','normalized difference snow index','snow cover index'], blurb: 'NDSI snow cover index' },
  savi: { category: 'vegetation', backend: 'savi', needsYear: true, needsSource: true,
    aliases: ['savi','soil adjusted vegetation index'],
    blurb: 'SAVI vegetation index (soil-adjusted)' },
  ndwi: { category: 'water', backend: 'ndwi', needsYear: true, needsSource: true,
    aliases: ['ndwi','water index','water body','water bodies','show water','map water','extract water','water extent','water coverage','surface water','water detection','lake','river','wetland','moisture','onyesha maji','maji','mto','ziwa'],
    blurb: 'NDWI water bodies / moisture' },
  ndbi: { category: 'urban', backend: 'ndbi', needsYear: true, needsSource: true,
    aliases: ['ndbi','built-up','built up','urban area','urban areas','urban footprint','built-up extraction','concrete','impervious','city','town','find built-up','built up areas'],
    blurb: 'NDBI built-up / urban areas' },
  urban_growth: { category: 'urban', backend: 'urban_growth', needsYear: true, needsSource: true,
    aliases: ['urban growth','urban expansion','urban densification','built-up change','urban change','city expansion'],
    blurb: 'Urban growth via NDBI difference between two years' },
  water_change: { category: 'change', backend: 'water_change', needsYear: true, needsSource: true,
    aliases: ['water extent change','water area change','water gain and loss','surface water change','change in water bodies','maji yameongezeka'],
    blurb: 'Water extent gain/loss from matched NDWI composites' },
  elevation: { category: 'terrain', backend: 'elevation',
    aliases: ['elevation','altitude','height','dem','terrain height','topography','above sea level','mountain','hill','show elevation','mwinuko'],
    blurb: 'Elevation from SRTM DEM' },
  slope: { category: 'terrain', backend: 'slope',
    aliases: ['slope','steepness','gradient','steep areas','find steep','mteremko'],
    blurb: 'Slope from SRTM DEM' },
  curvature: { category: 'terrain', backend: 'curvature',
    aliases: ['terrain curvature','curvature map','profile curvature','plan curvature'],
    blurb: 'Discrete 3×3 elevation Laplacian curvature from SRTM' },
  tri: { category: 'terrain', backend: 'tri',
    aliases: ['terrain ruggedness index','ruggedness index','tri map'],
    blurb: '8-neighbour RMS Terrain Ruggedness Index from SRTM' },
  tpi: { category: 'terrain', backend: 'tpi',
    aliases: ['topographic position index','tpi map','ridge valley position'],
    blurb: 'Elevation minus 3-pixel neighbourhood mean' },
  twi: { category: 'terrain', backend: 'twi',
    aliases: ['topographic wetness index','twi map'],
    blurb: 'Topographic wetness index from MERIT upstream area and SRTM slope' },
  terrain: { category: 'terrain', backend: 'terrain',
    aliases: ['terrain analysis','terrain map','topographic analysis'],
    blurb: 'Terrain derivatives (slope by default; request elevation, aspect, hillshade, curvature, TRI, TPI or TWI)' },
  landcover: { category: 'landcover', backend: 'landcover', needsYear: true, needsSource: true,
    aliases: ['land cover','landcover','lulc','classify land','classify this area','classify the polygon','land cover classification','landcover classification','land classification','show land cover classes','land use','ainisha ardhi','matumizi ya ardhi','aina ya ardhi'],
    blurb: 'Supervised land-cover classification (default Random Forest, 5 classes)' },
  vegetation: { category: 'vegetation', backend: 'vegetation', needsYear: true, needsSource: true,
    aliases: ['vegetation classification','classify vegetation','forest classification','vegetation classes','vegetation categories'],
    blurb: 'NDVI-threshold vegetation classification with custom classes' },
  dynamicworld: { category: 'landcover', backend: 'dynamicworld', needsYear: true,
    aliases: ['dynamic world','near real-time','current land cover','real-time land cover'],
    blurb: 'Dynamic World 9-class (10m)' },
  worldcover_v200: { category: 'landcover', backend: 'worldcover_v200',
    aliases: ['world cover','worldcover','esa land cover','global land cover'],
    blurb: 'ESA WorldCover 11-class (10m)' },
  modis_lc: { category: 'landcover', backend: 'modis_lc', needsYear: true,
    aliases: ['modis land cover','modis mcd12q1','mcd12q1'],
    blurb: 'MODIS MCD12Q1 17-class (500m)' },
  modis_cmg: { category: 'landcover', backend: 'modis_cmg', needsYear: true,
    aliases: ['modis cmg','mcd12c1','modis climate grid'],
    blurb: 'MODIS MCD12C1 CMG land cover' },
  copernicus_lc: { category: 'landcover', backend: 'copernicus_lc', needsYear: true,
    aliases: ['copernicus','proba-v','glcs','copernicus land cover'],
    blurb: 'Copernicus Global Land Cover (100m)' },
  glc_fcs30: { category: 'landcover', backend: 'glc_fcs30', needsYear: true,
    aliases: ['glc','fcs30','glc_fcs30','30m global land cover'],
    blurb: 'GLC_FCS30D 30m land cover' },
  nlcd: { category: 'landcover', backend: 'nlcd', needsYear: true,
    aliases: ['nlcd','national land cover database','us land cover'],
    blurb: 'NLCD 2021 (USA only, 30m)' },
  corine: { category: 'landcover', backend: 'corine', needsYear: true,
    aliases: ['corine','clc','european land cover','eu land cover'],
    blurb: 'CORINE 2018 (Europe only, 100m)' },
  change: { category: 'change', backend: 'change', needsYear: true, needsSource: true,
    aliases: ['change detection','compare','before after','difference','vegetation change','water change','built-up change','show changes','changes between','ndvi change','ndvi difference'],
    blurb: 'NDVI change between two years' },
  buildings: { category: 'urban', backend: 'buildings',
    aliases: ['building','buildings','building density','building footprint','houses','rooftop','structures','how many buildings','building count'],
    blurb: 'Building count + density (Open Buildings)' },
  flood_risk: { category: 'flood', backend: 'flood',
    aliases: ['flood risk','flood susceptibility','flood-prone','flood prone','flood hazard','flood zone','show flood risk'],
    blurb: 'Flood SUSCEPTIBILITY from terrain (SRTM proxy — not a hydraulic model)' },
  flood_mapping: { category: 'flood', backend: 'flood_mapping', needsYear: true,
    aliases: ['flood mapping','flooded areas','map flood','detect flooded','flood extent','map flooded areas','show floods','surface water flood','sentinel-1 flood','sentinel 1 flood'],
    blurb: 'Flood EXTENT from Sentinel-1 SAR water detection' },
  lst: { category: 'climate', backend: 'lst', needsYear: true,
    aliases: ['lst','land surface temperature','surface temperature','show temperature','heat hotspot','temperature','joto'],
    blurb: 'Land Surface Temperature (MODIS, °C)' },
  rainfall: { category: 'climate', backend: 'rainfall', needsYear: true,
    aliases: ['rainfall','precipitation','rain','chirps','annual rainfall','monthly rainfall','seasonal rainfall','mvua','precip'],
    blurb: 'Rainfall totals from CHIRPS' },
  erosion: { category: 'soil', backend: 'erosion', needsYear: true,
    aliases: ['soil erosion','erosion','rusle','soil loss','land degradation','soil degradation','tons/ha'],
    blurb: 'RUSLE-lite soil-loss proxy (t/ha/yr)' },
  drought: { category: 'climate', backend: 'drought', needsYear: true,
    aliases: ['drought','drought monitoring','drought severity','drought risk','vegetation drought','dry spell','ukame','vci','vhi','tci','spi','aridity'],
    blurb: 'Drought via NDVI anomaly (+ rainfall context)' },
  timeseries: { category: 'timeseries', backend: 'timeseries', needsYear: true,
    aliases: ['time series','timeseries','trend from','over time','yearly trend','mfululizo wa muda'],
    blurb: 'Yearly time series + trend (NDVI, rainfall, LST, ET, NO2)' },
  // ---- Spectral index engine: one backend (spectral_index), many indices ----
  mndwi: { category: 'water', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'MNDWI',
    aliases: ['mndwi','modified water index'],
    blurb: 'MNDWI water index (better in built-up areas)' },
  awei: { category: 'water', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'AWEI',
    aliases: ['awei','automated water extraction'],
    blurb: 'AWEI water extraction index' },
  msavi: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'MSAVI',
    aliases: ['msavi','modified soil adjusted'],
    blurb: 'MSAVI vegetation index' },
  ndre: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'NDRE',
    aliases: ['ndre','red edge','red-edge'],
    blurb: 'NDRE red-edge index (Sentinel-2)' },
  gndvi: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'GNDVI',
    aliases: ['gndvi','green ndvi'],
    blurb: 'GNDVI green vegetation index' },
  dvi: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'DVI',
    aliases: ['dvi','difference vegetation index'],
    blurb: 'DVI difference vegetation index' },
  rvi: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'RVI',
    aliases: ['rvi','ratio vegetation index'],
    blurb: 'RVI ratio vegetation index (NIR/Red)' },
  arvi: { category: 'vegetation', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'ARVI',
    aliases: ['arvi','atmospherically resistant'],
    blurb: 'ARVI atmospherically-resistant index' },
  bsi: { category: 'soil', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'BSI',
    aliases: ['bsi','bare soil index'],
    blurb: 'BSI bare-soil index' },
  ui: { category: 'urban', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'UI',
    aliases: [' ui ','urban index',' ui.'],
    blurb: 'UI urban index' },
  ibi: { category: 'urban', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'IBI',
    aliases: ['ibi','index-based built-up'],
    blurb: 'IBI built-up index' },
  ebbi: { category: 'urban', backend: 'spectral_index', needsYear: true, needsSource: true, index: 'EBBI',
    aliases: ['ebbi','enhanced built-up'],
    blurb: 'EBBI built-up index (Landsat thermal)' },
  // ---- Satellite imagery ----
  truecolor: { category: 'imagery', backend: 'imagery', needsYear: true, needsSource: true, mode: 'truecolor',
    aliases: ['true color','true colour','truecolor','natural color','natural colour','rgb','show sentinel-2','show landsat','satellite image','satellite imagery','picha ya satelaiti'],
    blurb: 'True-colour cloud-free composite' },
  falsecolor: { category: 'imagery', backend: 'imagery', needsYear: true, needsSource: true, mode: 'falsecolor',
    aliases: ['false color','false colour','falsecolor','false-color','nir composite','infrared composite'],
    blurb: 'False-colour (NIR) composite' },
  composite: { category: 'imagery', backend: 'imagery', needsYear: true, needsSource: true, mode: 'composite',
    aliases: ['cloud-free','cloud free','composite','median composite','mosaic','compare satellite'],
    blurb: 'Cloud-free median composite' },
  // ---- Terrain ----
  aspect: { category: 'terrain', backend: 'aspect',
    aliases: ['aspect','slope direction','faces which direction','mwelekeo'],
    blurb: 'Aspect (slope direction) from SRTM' },
  hillshade: { category: 'terrain', backend: 'hillshade',
    aliases: ['hillshade','hill shade','shaded relief','relief'],
    blurb: 'Hillshade relief from SRTM' },
  slope_classes: { category: 'terrain', backend: 'slope_classes',
    aliases: ['classify slope','slope classes','slope classification','slope categories','slope area','calculate slope'],
    blurb: 'Slope classification with custom classes/thresholds' },
  // ---- Temperature / urban thermal ----
  lst_change: { category: 'climate', backend: 'lst_change', needsYear: true,
    aliases: ['temperature change','lst change','lst anomaly','temperature anomaly','thermal change'],
    blurb: 'LST change between two years (MODIS)' },
  uhi: { category: 'climate', backend: 'uhi', needsYear: true,
    aliases: ['uhi','urban heat island','urban heat','heat island','heat hotspots','hottest areas','joto la mjini','maeneo ya joto'],
    blurb: 'Urban Heat Island intensity (urban vs rural LST)' },
  uftvi: { category: 'climate', backend: 'uftvi', needsYear: true,
    aliases: ['uftvi','utfvi','urban thermal field','thermal variance','vegetation thermal'],
    blurb: 'Urban Thermal Field Variance Index (UTFVI)' },
  // ---- Urban pattern ----
  sprawl: { category: 'urban', backend: 'sprawl', needsYear: true, needsSource: true,
    aliases: ['sprawl','urban sprawl','expansion pattern','development pattern','growth direction','leapfrog','dispersion'],
    blurb: 'Urban sprawl: expansion, rate, infill vs leapfrog' },
  // ---- Forest / LULC dynamics ----
  lulc_change: { category: 'change', backend: 'lulc_change', needsYear: true, needsSource: true,
    aliases: ['lulc change','class-wise','class wise','transition matrix','land cover change from','landcover change','conversion'],
    blurb: 'Class-wise LULC change + transition matrix' },
  deforestation: { category: 'change', backend: 'deforestation', needsYear: true,
    aliases: ['deforestation','forest loss','forest cover loss','forest change','ukataji miti','misitu kupotea'],
    blurb: 'Forest loss from Hansen Global Forest Change' },
  // ---- Water detail ----
  waterlogging: { category: 'water', backend: 'waterlogging', needsYear: true, needsSource: true,
    aliases: ['waterlogging','waterlogged','water logging','stagnant water','logging areas'],
    blurb: 'Waterlogging: MNDWI + flat + low-NDVI mask' },
  // ---- Climate extras ----
  et: { category: 'climate', backend: 'et', needsYear: true,
    aliases: [' evapotranspiration',' et ','evapotranspiration trend','monthly et','annual et'],
    blurb: 'Evapotranspiration from MODIS MOD16' },
  // ---- Air quality (Sentinel-5P / MODIS — real datasets only) ----
  airquality: { category: 'airquality', backend: 'airquality', needsYear: true,
    aliases: ['air quality','air pollution','pollutant','pollution trend','hewa chafu','uchafuzi wa hewa'],
    blurb: 'Air pollutants from Sentinel-5P (NO2, SO2, CO, O3) / MODIS AOD' },
  no2: { category: 'airquality', backend: 'airquality', needsYear: true, pollutant: 'no2',
    aliases: ['no2','no₂','nitrogen dioxide','nitrogen oxide'],
    blurb: 'NO2 tropospheric column (Sentinel-5P)' },
  so2: { category: 'airquality', backend: 'airquality', needsYear: true, pollutant: 'so2',
    aliases: ['so2','so₂','sulfur dioxide','sulphur dioxide'],
    blurb: 'SO2 column (Sentinel-5P)' },
  co: { category: 'airquality', backend: 'airquality', needsYear: true, pollutant: 'co',
    aliases: [' carbon monoxide',' co ','monoxide'],
    blurb: 'CO column (Sentinel-5P)' },
  aod: { category: 'airquality', backend: 'airquality', needsYear: true, pollutant: 'aod',
    aliases: ['aod','aerosol','aerosol optical depth'],
    blurb: 'Aerosol optical depth (MODIS)' },
  pm25: { category: 'airquality', backend: 'airquality', needsYear: true, pollutant: 'pm25',
    aliases: ['pm2.5','pm25','particulate','fine dust'],
    blurb: 'PM2.5 — no valid GEE dataset configured (guided message)' },
  // ---- Soil / hazards / hydrology / minerals / suitability ----
  salinity: { category: 'soil', backend: 'salinity', needsYear: true, needsSource: true,
    aliases: ['salinity','soil salinity','salinity index','salinity monitoring','chumvi'],
    blurb: 'Soil salinity indicator + classes' },
  moisture: { category: 'soil', backend: 'moisture', needsYear: true, needsSource: true,
    aliases: ['soil moisture','moisture','ndmi','unyevu wa udongo'],
    blurb: 'Soil moisture via NDMI' },
  landslide: { category: 'hazard', backend: 'landslide', needsYear: true,
    aliases: ['landslide','landslides','maporomoko','landslide susceptibility','landslide risk','landslide-prone'],
    blurb: 'Landslide susceptibility (weighted factors, transparent)' },
  hydrology: { category: 'hydrology', backend: 'hydrology',
    aliases: ['flow accumulation','flow direction','stream order','strahler order','watershed','drainage','stream network','catchment statistics','catchment','basin','drainage density','bonde la maji'],
    blurb: 'MERIT Hydro drainage, flow direction, upstream area and catchment indicators' },
  mineral: { category: 'geology', backend: 'mineral', needsYear: true, needsSource: true,
    aliases: ['mineral','minerals','mineral exploration','mineral mapping','rock index','band ratio','band ratios','clay','alteration','madini'],
    blurb: 'Spectral mineral/alteration indicator (band ratios)' },
  suitability: { category: 'suitability', backend: 'suitability', needsYear: true,
    aliases: ['suitability','suitable areas','site selection','site suitability','residential','agricultural suitability','crop suitability','solar suitability','industrial suitability','kufaa'],
    blurb: 'WLC or AHP suitability with explicit criteria and weights; AHP format: “AHP criteria slope,rainfall,landcover; matrix 1,2,3;0.5,1,2;0.33,0.5,1”' },
  // ---- Statistical trend tests ----
  trend: { category: 'timeseries', backend: 'trend', needsYear: true,
    aliases: ['linear regression','regression','mann kendall','mann-kendall','mannkendall','trend analysis','trend test','show trend','run trend','takwimu'],
    blurb: 'Linear regression (slope/intercept/R²) + Mann-Kendall (Z/p)' },
  // ---- Boundary / zonal / export (executor routes, not /api/analyze) ----
  zonal: { category: 'zonal', zonal: true,
    aliases: ['for every','for each','each ward','every ward','per feature','by feature','zonal','zonal statistics','ward by ward','kila','kila kata','kila kipengele','wards','villages'],
    blurb: 'Zonal statistics per boundary feature' },
  admin_lookup: { category: 'boundary', admin: true,
    aliases: ['district','districts','ward','wards','village','villages','municipality','municipal','region','regions','division','wilaya','kata','kijiji','mkoa','tarafa','admin boundary','administrative boundary','boundaries'],
    blurb: 'Administrative boundary lookup (GAUL via GEE)' },
  export_this: { category: 'export', exportKind: 'current',
    aliases: ['export this','export result','export the result','download result','export current','hamisha','pakua matokeo'],
    blurb: 'Export the current result' },
  export_geotiff: { category: 'export', exportKind: 'geotiff',
    aliases: ['geotiff','tif','tiff','cog','as geotiff','raster export','export raster'],
    blurb: 'Export raster as QGIS-ready GeoTIFF' },
  export_shapefile: { category: 'export', exportKind: 'shp',
    aliases: ['shapefile','shp','as shapefile','export vector'],
    blurb: 'Export classes as Shapefile (QGIS)' },
  export_geojson: { category: 'export', exportKind: 'geojson',
    aliases: ['export as geojson','download geojson','to geojson'],
    blurb: 'Export as GeoJSON' },
  export_kml: { category: 'export', exportKind: 'kml',
    aliases: ['kml','kmz','google earth export','export kml'],
    blurb: 'Export as KML/KMZ' },
  export_csv: { category: 'export', exportKind: 'csv',
    aliases: ['csv','spreadsheet','give me the csv','statistics csv','export table','export stats','table export'],
    blurb: 'Export statistics as CSV' },
  export_png: { category: 'export', exportKind: 'png',
    aliases: ['png','preview image','map image','export image'],
    blurb: 'Export rendered PNG preview' },
  export_boundary: { category: 'export', exportKind: 'boundary',
    aliases: ['export boundary','export the boundary','export aoi','download boundary','export this boundary','hamisha mpaka'],
    blurb: 'Export the current boundary (GeoJSON/Shapefile/KML)' },
  qgis: { category: 'export', exportKind: 'qgis',
    aliases: ['qgis','prepare for qgis','use in qgis','open in qgis','continue in qgis','qgis ready'],
    blurb: 'QGIS-ready export bundle' },
  // Local (no GEE): computed in-browser with turf
  // Local vector overlay (GeoJSON Polygon/MultiPolygon inputs, WGS84).
  intersection: { category: 'vector', local: 'intersection',
    aliases: ['intersection','intersect','intersect polygons','polygon intersection','overlap between','overlay intersection','makutano ya poligoni','intersection analysis'],
    blurb: 'Polygon intersection of two uploaded layers (local Turf)' },
  area: { category: 'measure', local: 'area',
    aliases: ['area','how big','calculate area','measure area','surface area','hectare','size of'],
    blurb: 'Polygon area (local)' },
  distance: { category: 'measure', local: 'distance',
    aliases: ['distance','how far','measure distance','length','proximity between'],
    blurb: 'Centroid distance (local)' },
  buffer: { category: 'measure', local: 'buffer',
    aliases: ['buffer','buffer zone','radius','surrounding area','catchment around'],
    blurb: 'Buffer around AOI (local)' },
  global_moran: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['global moran','moran i','global spatial autocorrelation','spatial autocorrelation'], blurb: 'Global Moran spatial autocorrelation test' },
  local_moran: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['local moran','local indicators of spatial association','lisa','cluster and outlier analysis'], blurb: 'Local Moran cluster and outlier analysis' },
  getis_ord_gi_star: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['getis ord','getis-ord','gi star','gi*','hot spot analysis','hotspot analysis'], blurb: 'Getis-Ord Gi* hot and cold spot analysis' },
  kde: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['kernel density','kernel density estimation','kde','point density surface'], blurb: 'Gaussian kernel density estimate' },
  nearest_neighbor: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['nearest neighbour','nearest neighbor','clark evans','nearest-neighbour analysis'], blurb: 'Clark-Evans nearest-neighbour test against CSR' },
  point_pattern: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['point pattern','ripley k','ripley l','point-pattern statistics'], blurb: 'Ripley K/L descriptive point-pattern statistics' },
  idw: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['idw','inverse distance weighting','inverse distance weighted interpolation'], blurb: 'Inverse-distance weighted point interpolation' },
  kriging: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['kriging','ordinary kriging','geostatistical interpolation'], blurb: 'Ordinary kriging with an explicit spherical variogram' },
  spatial_sampling: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['spatial sampling','random spatial sample','random sample points','generate sample points'], blurb: 'Uniform random spatial sampling in the study area' },
  spatial_regression: { category: 'spatial statistics', local: 'spatial_statistics',
    aliases: ['spatial regression','geographically weighted regression','gwr'], blurb: 'Geographically weighted regression with local coefficients' },
  surface_metrics: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['dsm analysis','dtm analysis','surface metrics','drone surface analysis'], blurb: 'Metrics for supplied DSM or DTM elevation grids' },
  dsm_dtm: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['dsm dtm difference','dsm minus dtm','canopy height model','surface model difference'], blurb: 'Aligned DSM–DTM elevation difference' },
  dem_difference: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['dem difference','dem of difference','elevation difference','terrain change monitoring'], blurb: 'DEM of difference from aligned elevation grids' },
  cut_fill: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['cut and fill','cut fill calculation','earthwork volume'], blurb: 'Cut/fill volumes from aligned elevation grids' },
  stockpile_volume: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['stockpile volume','stockpile measurement','mine stockpile'], blurb: 'Stockpile volume against an explicit base and footprint mask' },
  excavation_volume: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['excavation volume','pit excavation volume','excavation measurement'], blurb: 'Excavation volume against an explicit reference surface and footprint mask' },
  point_cloud_inspection: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['inspect point cloud','point cloud inspection','xyz point cloud','drone point cloud'], blurb: 'Descriptive inspection of uploaded projected XYZ points' },
  orthomosaic_analysis: { category: 'drone and mining', local: 'drone_analysis',
    aliases: ['orthomosaic analysis','orthomosaic ndvi','drone ndvi','analyze orthomosaic'], blurb: 'NDVI from uploaded calibrated orthomosaic red/NIR bands' },
};

// Backwards-compatible list of backend ids (for validation / suggestions)
export const IMPLEMENTED_BACKENDS = Object.values(ANALYSIS_REGISTRY)
  .map((r) => r.backend).filter(Boolean);

// Capability listing for "what can you analyze?" — only implemented tools
export function listCapabilities() {
  const cats = {};
  for (const [id, r] of Object.entries(ANALYSIS_REGISTRY)) {
    if (!cats[r.category]) cats[r.category] = [];
    cats[r.category].push(id);
  }
  return cats;
}

// ---------------------------------------------------------------------------
// Extractors
// ---------------------------------------------------------------------------
const NUMBER_WORDS = { three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8,
  third: 3, fourth: 4, fifth: 5, sixth: 6, seventh: 7, eighth: 8,
  tatu: 3, nne: 4, tano: 5, sita: 6, saba: 7, nane: 8,
  '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8 };

const CLASS_NOUNS = 'classes?|category|categories|types?|groups?|clusters?|aina|makundi|madarasa|vikaango|darasa';
export function extractClassCount(text) {
  const lower = text.toLowerCase();
  let m = lower.match(new RegExp(`\\b([3-8])\\s*(?:${CLASS_NOUNS})\\b`));
  if (m) return parseInt(m[1], 10);
  m = lower.match(new RegExp(`\\b(three|four|five|six|seven|eight|tatu|nne|tano|sita|saba|nane)\\s*(?:${CLASS_NOUNS})\\b`));
  if (m) return NUMBER_WORDS[m[1]];
  // Noun-first order (Swahili + casual EN): "classes 5", "madarasa matano".
  m = lower.match(new RegExp(`\\b(?:${CLASS_NOUNS})\\s+(three|four|five|six|seven|eight|tatu|nne|tano|sita|saba|nane|[3-8])\\b`));
  if (m) return NUMBER_WORDS[m[1]] ?? parseInt(m[1], 10);
  m = lower.match(/\binto\s+(three|four|five|six|seven|eight|tatu|nne|tano|sita|saba|nane|[3-8])\b/);
  if (m) return NUMBER_WORDS[m[1]] ?? parseInt(m[1], 10);
  return null;
}

// "classify slope as 0-5, 5-15, 15-30, 30-45, above 45 degrees"
export function extractThresholds(text) {
  const lower = text.toLowerCase().replace(/–|—/g, '-');
  const nums = [...lower.matchAll(/(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)/g)]
    .map((m) => [parseFloat(m[1]), parseFloat(m[2])]);
  const above = lower.match(/above\s+(\d+(?:\.\d+)?)/);
  if (!nums.length) return null;
  const breaks = [nums[0][0]];
  nums.forEach(([a, b]) => { breaks.push(a, b); });
  if (above) breaks.push(parseFloat(above[1]));
  const uniq = [...new Set(breaks)].sort((a, b2) => a - b2).slice(0, 9);
  return uniq.length >= 3 ? uniq : null;
}

const MONTHS = { january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
  july: 7, august: 8, september: 9, october: 10, november: 11, december: 12,
  jan: 1, feb: 2, mar: 3, apr: 4, jun: 6, jul: 7, aug: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12,
  januari: 1, februari: 2, machi: 3, aprili: 4, mei: 5, juni: 6,
  julai: 7, agosti: 8, septemba: 9, oktoba: 10, novemba: 11, desemba: 12 };
// Default season mapping (documented in replies; East-Africa bimodal)
const SEASONS = { djf: [12, 1, 2], mam: [3, 4, 5], jja: [6, 7, 8], son: [9, 10, 11],
  'wet season': [11, 12, 1, 2, 3, 4], 'dry season': [5, 6, 7, 8, 9, 10],
  'wet': [11, 12, 1, 2, 3, 4], 'dry': [5, 6, 7, 8, 9, 10],
  summer: [6, 7, 8], winter: [12, 1, 2], spring: [3, 4, 5], autumn: [9, 10, 11], fall: [9, 10, 11] };

export function extractPeriod(text) {
  const lower = text.toLowerCase();
  for (const [name, months] of Object.entries(SEASONS)) {
    // Word boundaries: 'fall' must not fire inside 'rainfall'.
    if (new RegExp(`\\b${escRx(name)}\\b`).test(lower)) return { period: 'seasonal', season: name.replace(' ', ''), months };
  }
  const words = lower.split(/[^a-z]+/);
  for (const w of words) {
    if (MONTHS[w]) return { period: 'monthly', month: MONTHS[w], monthName: w };
  }
  if (/monthly|\bmonth\b|kila mwezi/.test(lower)) return { period: 'monthly', month: null };
  if (/seasonal|season\b|msimu/.test(lower)) return { period: 'seasonal', season: null, months: null };
  if (/annual|yearly|mwaka/.test(lower)) return { period: 'annual' };
  return { period: 'annual' };
}

// "slope 40, landcover 30, ndvi 30" -> normalized weights
export function extractWeights(text) {
  const lower = text.toLowerCase();
  const factors = { slope: ['slope', 'mteremko'], landcover: ['landcover', 'land cover', 'lulc'],
    ndvi: ['ndvi', 'vegetation', 'mimea'], elevation: ['elevation', 'dem', 'mwinuko'],
    rainfall: ['rainfall', 'rain', 'mvua'], flood: ['flood', 'mafuriko'] };
  const found = {};
  for (const [key, words] of Object.entries(factors)) {
    for (const w of words) {
      const m = lower.match(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*(\\d{1,3})'));
      if (m) { found[key] = Math.min(100, Math.max(1, parseInt(m[1], 10))); break; }
    }
  }
  if (!Object.keys(found).length) return null;
  const total = Object.values(found).reduce((a, b) => a + b, 0);
  const norm = {};
  for (const [k, v] of Object.entries(found)) norm[k] = Math.round((v / total) * 100) / 100;
  return norm;
}

export function extractDroughtIndicator(text) {
  const lower = text.toLowerCase();
  if (/\bvhi\b|vegetation health index/.test(lower)) return 'vhi';
  if (/\bvci\b|vegetation condition/.test(lower)) return 'vci';
  if (/\btci\b|temperature condition/.test(lower)) return 'tci';
  if (/\bspi\b|standardized precipitation/.test(lower)) return 'spi';
  if (/aridity|arid/.test(lower)) return 'aridity';
  return null;
}

export function extractPollutant(text) {
  const lower = text.toLowerCase();
  if (/pm2\.?5|pm25|particulate/.test(lower)) return 'pm25';
  if (/no2|no₂|nitrogen/.test(lower)) return 'no2';
  if (/so2|so₂|sulfur|sulphur/.test(lower)) return 'so2';
  if (/o3|ozone/.test(lower) && !/o32/.test(lower)) return 'o3';
  if (/\bco\b|carbon monoxide/.test(lower)) return 'co';
  if (/aod|aerosol/.test(lower)) return 'aod';
  return null;
}

// "B7/B2", "B5/B7" (sensor-relative band codes)
export function extractBandRatio(text) {
  const m = text.toUpperCase().match(/\b(B\d{1,2}[A-Z]?)\s*\/\s*(B\d{1,2}[A-Z]?)\b/);
  return m ? { num: m[1], den: m[2] } : null;
}

export function extractMineralPreset(text) {
  const lower = text.toLowerCase();
  if (/clay/.test(lower)) return 'clay';
  if (/ferrous|iron oxide|iron/.test(lower)) return 'ferrous';
  if (/alteration|oh-group|hydroxyl/.test(lower)) return 'alteration';
  if (/rock index|silica/.test(lower)) return 'silica';
  return null;
}

export function extractStatsOp(text) {
  const lower = text.toLowerCase();
  if (/maximum|\bmax\b|peak|hottest|highest/.test(lower)) return 'max';
  if (/minimum|\bmin\b|lowest|coldest/.test(lower)) return 'min';
  if (/std|standard deviation|variability/.test(lower)) return 'std';
  if (/average|\bmean\b|typical/.test(lower)) return 'mean';
  return null;
}

export function extractTrendTest(text) {
  const lower = text.toLowerCase();
  if (/mann[\s-]?kendall|mk test/.test(lower)) return 'mannkendall';
  if (/linear regression|regression|least squares/.test(lower)) return 'regression';
  return 'both';
}

export function isCodeRequest(text) {
  return /gee code|earth engine code|generate code|show .*code|code for|script for|javascript|python script|nionyeshe code|andika code|niandikie msimbo|please|tafadhali/gi.test(text.toLowerCase());
}

// "use the ward boundary" / "ward boundary" / known layer names
export function extractTargetLayer(text, layerNames = []) {
  const lower = text.toLowerCase();
  for (const n of layerNames) {
    if (n && n.length >= 3 && lower.includes(String(n).toLowerCase())) return n;
  }
  const m = lower.match(/use\s+(?:the\s+)?([a-z0-9 _-]{3,60}?)\s*(boundary|layer|shapefile|geojson)\b/);
  if (m) return m[1].trim();
  return null;
}

// "the ward named Vwawa" / "wards in Mbozi" / "analyze only Mbozi district"
export function extractAttributeFilter(text) {
  const lower = text.toLowerCase();
  let m = lower.match(/(?:named|called|called\s+as)\s+([a-z0-9 _-]{2,60})/);
  if (m) return { field: null, value: m[1].trim() };
  m = lower.match(/(?:wards?|features?|areas?)\s+in\s+([a-z0-9 _-]{2,60})/);
  if (m) return { field: null, value: m[1].trim() };
  m = lower.match(/only\s+([a-z0-9 _-]{2,60}?)\s+(district|ward|village|region|area)\b/);
  if (m) return { field: null, value: m[1].trim() };
  return null;
}

// "Mbozi district" / "district of Mbozi" / "Vwawa ward"
export function extractAdminName(text) {
  const lower = text.toLowerCase();
  const levels = [
    { words: ['region', 'mkoa'], level: 1 },
    { words: ['district', 'wilaya', 'municipality', 'municipal'], level: 2 },
    { words: ['ward', 'kata', 'village', 'kijiji', 'division', 'tarafa'], level: 2 },
  ];
  for (const { words, level } of levels) {
    for (const w of words) {
      let m = lower.match(new RegExp(`([a-z][a-z0-9 _-]{1,50}?)\\s+${w}\\b`));
      if (m && !/the|this|that|current/.test(m[1].trim())) return { name: m[1].trim(), level };
      m = lower.match(new RegExp(`${w}\\s+of\\s+([a-z][a-z0-9 _-]{1,50})`));
      if (m) return { name: m[1].trim(), level };
    }
  }
  return null;
}

export function extractExportSpec(text) {
  const lower = text.toLowerCase();
  let format = null;
  if (/shapefile|\bshp\b/.test(lower)) format = 'shp';
  else if (/geojson/.test(lower)) format = 'geojson';
  else if (/kmz/.test(lower)) format = 'kmz';
  else if (/\bkml\b/.test(lower)) format = 'kml';
  else if (/csv|spreadsheet|table/.test(lower)) format = 'csv';
  else if (/png|preview|image/.test(lower)) format = 'png';
  else if (/geotiff|\btif\b|\btiff\b|\bcog\b|raster/.test(lower)) format = 'geotiff';
  let scale = null;
  const sm = lower.match(/(\d{2,5})\s*m\b/);
  if (sm) scale = Math.min(10000, Math.max(1, parseInt(sm[1], 10)));
  let crs = null;
  const cm = lower.match(/epsg\s*:\s*(\d{4,5})/) || lower.match(/\b(utm\s*36s?|wgs84)\b/);
  if (cm) crs = /utm/i.test(cm[1] || cm[0]) ? 'EPSG:32736' : /wgs/i.test(cm[0]) ? 'EPSG:4326' : `EPSG:${cm[1]}`;
  return { format, scale, crs };
}

// "classify into X, Y and Z" / "classify vegetation into forest, shrubs, ..."
export function extractClassNames(text) {
  const lower = text.toLowerCase();
  const m = lower.match(/classif\w*[^.]*?\binto\s+([^.?]+)/);
  if (!m) return null;
  const raw = m[1]
    .replace(/\b(area|areas|here|this area|the polygon|the map|classes?|categories?|types?|groups?|clusters?)\b/g, ' ')
    .trim();
  if (!raw || raw.length < 2) return null;
  const parts = raw.split(/,|\band\b|;|\//)
    .map((s) => s.trim().replace(/^(the|a|an)\s+/, ''))
    .filter((s) => s.length >= 2 && s.length <= 40 && !/^\d+$/.test(s));
  if (parts.length < 2 || parts.length > 8) return null;
  const title = (s) => s.split(/\s+/).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  return parts.map(title);
}

const ALGORITHM_ALIASES = [
  { id: 'random_forest', aliases: ['random forest', 'random-forest', /\brf\b/, 'forest classifier'] },
  { id: 'svm', aliases: ['svm', 'support vector machine', 'support vector'] },
  { id: 'cart', aliases: ['cart', 'decision tree', 'tree classifier', 'classification tree'] },
  { id: 'gtb', aliases: ['gtb', 'gradient tree boosting', 'gradient boosting', 'boosted trees'] },
  { id: 'minimum_distance', aliases: ['minimum distance', 'minimum-distance', 'min distance'] },
  { id: 'kmeans', aliases: ['k-means', 'kmeans', 'k means', 'unsupervised', 'clustering', 'automatic clusters'] },
];

export function extractAlgorithm(text) {
  const lower = text.toLowerCase();
  for (const a of ALGORITHM_ALIASES) {
    for (const al of a.aliases) {
      if (typeof al === 'string' ? lower.includes(al) : al.test(lower)) return a.id;
    }
  }
  return null;
}

export function extractClassificationFeatures(text) {
  const lower = text.toLowerCase();
  const map = { blue: 'blue', green: 'green', red: 'red', rededge1: 'rededge1', rededge2: 'rededge2',
    rededge3: 'rededge3', nir: 'nir', nir_narrow: 'nir_narrow', swir1: 'swir1', swir2: 'swir2',
    ndvi: 'ndvi', ndwi: 'ndwi', mndwi: 'mndwi', savi: 'savi', evi: 'evi', evi2: 'evi2',
    msavi: 'msavi', gndvi: 'gndvi', ndmi: 'ndmi', nbr: 'nbr', ndsi: 'ndsi', ndbi: 'ndbi', bsi: 'bsi', ndre: 'ndre' };
  const mentioned = Object.keys(map).filter((name) => new RegExp(`\\b${name}\\b`, 'i').test(lower));
  return mentioned.length ? mentioned.map((name) => map[name]) : null;
}

export function extractModelConfig(text, algorithm) {
  const lower = text.toLowerCase();
  const config = {};
  const treeCount = lower.match(/\b(\d{2,4})\s*(?:trees?|estimators?)\b/);
  if (treeCount) config.trees = Number(treeCount[1]);
  const leaf = lower.match(/\b(?:min(?:imum)?\s*leaf(?:\s*population)?|leaf\s*size)\s*(?:of|=|:)?\s*(\d+)\b/);
  if (leaf) config.minLeafPopulation = Number(leaf[1]);
  const kernel = lower.match(/\b(linear|rbf|polynomial|poly|sigmoid)\s*(?:kernel)?\b/);
  if (kernel) config.svmKernel = kernel[1] === 'polynomial' ? 'POLY' : kernel[1].toUpperCase();
  const cost = lower.match(/\b(?:svm\s*)?cost\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\b/);
  if (cost) config.svmCost = Number(cost[1]);
  const gamma = lower.match(/\bgamma\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\b/);
  if (gamma) config.svmGamma = Number(gamma[1]);
  return Object.keys(config).length ? config : null;
}

export function extractYears(text) {
  const lower = text.toLowerCase();
  const allYears = [...lower.matchAll(/\b(19[8-9]\d|20[0-3]\d)\b/g)].map((x) => parseInt(x[1], 10));
  const uniqueYears = [...new Set(allYears)].sort((a, b) => a - b);
  if (uniqueYears.length >= 3) return { year: uniqueYears.at(-1), year2: uniqueYears[0], years: uniqueYears };
  // "from 2015 to 2025" / "between 2000 and 2025" / "compare 2015 and 2025"
  let m = lower.match(/from\s+(19[8-9]\d|20[0-3]\d)\s+to\s+(19[8-9]\d|20[0-3]\d)/)
    || lower.match(/between\s+(19[8-9]\d|20[0-3]\d)\s+and\s+(19[8-9]\d|20[0-3]\d)/)
    || lower.match(/compare\s+(19[8-9]\d|20[0-3]\d)\s+(?:and|vs|with|to)\s+(19[8-9]\d|20[0-3]\d)/);
  if (m) return { year: parseInt(m[2], 10), year2: parseInt(m[1], 10), years: uniqueYears };
  const all = allYears;
  if (all.length >= 2) return { year: all[all.length - 1], year2: all[0] };
  if (all.length === 1) return { year: all[0], year2: null };
  return { year: null, year2: null };
}

export function extractSource(text) {
  const lower = text.toLowerCase();
  if (lower.includes('landsat 9') || lower.includes('landsat-9') || lower.includes('l9')) return 'landsat9';
  if (lower.includes('landsat 8') || lower.includes('landsat-8') || lower.includes('l8')) return 'landsat8';
  if (lower.includes('landsat 7') || lower.includes('landsat-7')) return 'landsat7';
  if (lower.includes('landsat')) return 'landsat8';
  if (lower.includes('sentinel-1') || lower.includes('sentinel 1') || lower.includes('s1') || lower.includes('sar')) return 'sentinel1';
  if (lower.includes('sentinel-2') || lower.includes('sentinel 2') || lower.includes('sentinel')) return 'sentinel2';
  if (lower.includes('modis')) return 'modis';
  return null;
}

export function extractBufferRadius(text) {
  const lower = text.toLowerCase();
  let m = lower.match(/(\d+(?:\.\d+)?)\s*(km|kilometers?|kilometres?)\b/);
  if (m) return Math.round(parseFloat(m[1]) * 1000);
  m = lower.match(/(\d+(?:\.\d+)?)\s*(m|meters?|metres?)\b/);
  if (m) return Math.round(parseFloat(m[1]));
  return 500;
}

export function extractTimeseriesVariable(text) {
  const lower = text.toLowerCase();
  if (lower.includes('rainfall') || lower.includes('precipitation') || lower.includes('rain ')) return 'rainfall';
  if (lower.includes('lst') || lower.includes('temperature') || lower.includes('heat')) return 'lst';
  if (lower.includes('ndvi') || lower.includes('vegetation') || lower.includes('ndwi') || lower.includes('water') || lower.includes('built')) return 'ndvi';
  return 'ndvi';
}

const AOI_PHRASES = ['this area', 'this polygon', 'selected area', 'drawn area', 'current area',
  'here', 'the map area', 'the polygon', 'my area', 'my polygon', 'the area',
  'eneo hili', 'hapa', 'eneo langu', 'eneo lililochorwa']; 

export function mentionsAOI(text) {
  return AOI_PHRASES.some((p) => text.toLowerCase().includes(p));
}

// ---------------------------------------------------------------------------
// Scoring against the registry (single place — no scattered if-includes)
// ---------------------------------------------------------------------------
const escRx = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Edit distance <=2 for typo tolerance ("vegation" -> "vegetation").
function editDist(a, b) {
  if (Math.abs(a.length - b.length) > 2) return 99;
  const dp = Array(b.length + 1).fill(0).map((_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const t = dp[j];
      dp[j] = Math.min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = t;
    }
  }
  return dp[b.length];
}

function scoreRegistry(text) {
  const lower = text.toLowerCase();
  const words = lower.split(/[^a-z0-9]+/).filter((w) => w.length >= 4);
  const scores = {};
  for (const [id, r] of Object.entries(ANALYSIS_REGISTRY)) {
    let s = 0;
    for (const raw of r.aliases) {
      const a = raw.trim();
      if (!a) continue;
      // Word boundaries everywhere: 'ndwi' ≠ 'mndwi', 'et' ≠ 'vegetation',
      // 'show water' ≠ 'show watershed'/'show waterlogging'.
      const pat = a.includes(' ')
        ? `\\b${a.split(/\s+/).map(escRx).join('\\s+')}\\b`
        : `\\b${escRx(a)}\\b`;
      if (new RegExp(pat).test(lower)) {
        s += a.length >= 8 ? 20 : a.length >= 4 ? 12 : 6;
        continue;
      }
      // Typo fallback: single-word aliases only, distance 1-2.
      if (!a.includes(' ') && a.length >= 5 && words.length) {
        for (const w of words) {
          if (w.length >= 5 && editDist(w, a) <= 2 && Math.abs(w.length - a.length) <= 2) {
            s += 8;
            break;
          }
        }
      }
    }
    if (s > 0) scores[id] = s;
  }
  return scores;
}

function topMatches(scores, n = 2) {
  return Object.entries(scores).sort((a, b) => b[1] - a[1]).slice(0, n);
}

// ---------------------------------------------------------------------------
// Planner
// ---------------------------------------------------------------------------
export const DEFAULT_LULC_CLASSES = ['Bareland', 'Built-up', 'Vegetation', 'Cropland', 'Rangeland'];
export const DEFAULT_VEGETATION_CLASSES = ['Bare', 'Rangeland', 'Shrubs', 'Cropland', 'Forest'];

const ALGORITHM_LABEL = { random_forest: 'Random Forest', cart: 'CART', svm: 'SVM', gtb: 'Gradient Tree Boosting', kmeans: 'K-Means' };

/**
 * planRequest(text, ctx) -> structured plan (executor-ready, no NL inside engine)
 * ctx: { hasAOI, prev (previous plan or null) }
 */
export function planRequest(text, ctx = {}) {
  const raw = (text || '').trim();
  const lower = raw.toLowerCase().trim();
  const { hasAOI = false, prev = null, lang = 'en', layerNames = [] } = ctx;
  const L = lang === 'sw' ? 'sw' : 'en';
  if (!lower) return { intent: 'empty', confidence: 1, aoi: hasAOI ? 'current' : null, parameters: {}, reply: tr(L, 'empty') };
  if (/ca\s*[-]?\s*markov|future\s+land\s*cover\s+scenario|predict\s+future\s+land\s*cover/.test(lower)) {
    return { intent: 'clarify', confidence: 0.95, aoi: hasAOI ? 'current' : null, parameters: {},
      reply: L === 'sw'
        ? 'CA-Markov haijazalishwa: mradi huu hauna ramani 3+ za kihistoria zilizo na madarasa yanayolingana na hindcast huru iliyothibitishwa. Tumia LULC comparison ya miaka hadi 8 kupata mabadiliko yaliyoonekana.'
        : 'No CA-Markov scenario was produced: this project lacks 3+ historical maps with harmonized classes and a validated independent hindcast. Use the observed LULC comparison for up to 8 dates instead.' };
  }

  // Educational methodology questions use the verified catalog and never trigger analysis execution.
  const asksForMethodology = /^(what is|what are|explain|define|how does|how do|formula for|limitations of|assumptions of|ni nini|eleza|fafanua|inafanyaje|kanuni ya|mipaka ya|dhana za)\b/.test(lower)
    || /\b(what is|explain|define|how does|ni nini|eleza|fafanua|inafanyaje)\b/.test(lower);
  if (asksForMethodology) {
    const method = searchMethodologies(raw, 1)[0];
    if (method) return { intent: 'knowledge', confidence: 0.9, aoi: null, parameters: {}, methodId: method.id,
      methodologyStatus: method.status, reply: formatMethodologyReply(method, L) };
  }

  // Code generation for a specific analysis (no EE run — returns GEE JS/Python)
  if (isCodeRequest(raw)) {
    const stripped = raw.replace(/gee code|earth engine code|generate code|show .*code|code for|script for|javascript|python script|msimbo .*gee|nionyeshe code|andika code|niandikie msimbo|please|tafadhali/gi, ' ').trim();
    if (!stripped || stripped.length < 4) {
      if (prev && prev.backend) {
        return { intent: 'code', confidence: 0.9, aoi: null, backend: prev.backend,
          parameters: { ...prev.parameters, wantsCode: true },
          reply: tr(L, 'code_for_last', { x: prev.backend }) };
      }
      return { intent: 'clarify', confidence: 0.7, aoi: null, parameters: {},
        reply: tr(L, 'clarify_code_which') };
    }
    const sub = planSingle(stripped, { hasAOI, prev: null, lang: L, layerNames });
    if (sub.backend || sub.local) {
      return { intent: 'code', confidence: 0.85, aoi: null, backend: sub.backend, local: sub.local,
        parameters: { ...sub.parameters, wantsCode: true },
        reply: tr(L, 'code_for', { x: sub.intent }) };
    }
    if (prev && prev.backend) {
      return { intent: 'code', confidence: 0.7, aoi: null, backend: prev.backend,
        parameters: { ...prev.parameters, wantsCode: true },
        reply: tr(L, 'code_for_last', { x: prev.backend }) };
    }
    return { intent: 'clarify', confidence: 0.6, aoi: null, parameters: {},
      reply: tr(L, 'clarify_code_unknown') };
  }

  // Discovery — only implemented tools
  if (lower.match(/what can you (analyze|do)|capabilit|list .*analys|available.*(tool|analys)|help.*analys|unaweza nini/)) {
    const caps = listCapabilities();
    const lines = Object.entries(caps).map(([c, ids]) => `• ${c}: ${ids.join(', ')}`).join('\n');
    return { intent: 'discovery', confidence: 1, aoi: null, parameters: {},
      reply: `${tr(L, 'discovery_intro')}\n${lines}\n\n${tr(L, 'discovery_hint')}` };
  }

  // Explicit polygon overlay verbs outrank incidental admin-boundary aliases
  // (e.g. "intersect ward boundaries with protected areas").
  if (/\b(intersect|intersection)\b/.test(lower) || /\b(?:polygon|vector|layer)\s+overlay\b/.test(lower)) {
    const mentionedLayers = layerNames.filter((name) => name && lower.includes(String(name).toLowerCase()));
    const parameters = {};
    if (mentionedLayers.length >= 2) {
      parameters.sourceLayer = mentionedLayers[0];
      parameters.targetLayer = mentionedLayers[1];
    }
    return { intent: 'intersection', confidence: 0.96, aoi: null, local: 'intersection', parameters,
      reply: L === 'sw'
        ? 'Nita-intersect poligoni za layers mbili zilizopakiwa kwa Turf; nitahesabu eneo la overlap na kuweka matokeo kwenye ramani.'
        : 'I will intersect the two uploaded polygon layers with Turf, calculate overlap area and add the result to the map.' };
  }

  // Compound: "urban expansion from 2015 to 2025 and vegetation loss" -> steps
  const isAHPMatrix = /(?:ahp|analytic hierarchy).*?criteria\s+[^;]+;\s*matrix\s+[0-9.,;|/ ]+/.test(lower);
  const compoundParts = lower.split(/\s+and\s+|\s*;\s*|\s+then\s+|\s+na\s+/).filter((p) => p.length > 8);
  const isClassifierFeatureList = /classif\w*|ainisha/.test(lower)
    && /\b(using|with|features?|bands?|kutumia)\b/.test(lower)
    && extractClassificationFeatures(lower)?.length >= 2;
  if (compoundParts.length >= 2 && !isClassifierFeatureList && !isAHPMatrix) {
    const steps = [];
    for (const part of compoundParts.slice(0, 4)) {
      const sub = planSingle(part, { hasAOI, prev: null, lang: L, layerNames });
      if (sub.intent !== 'unknown' && sub.intent !== 'chat' && sub.backend) steps.push(sub);
    }
    if (steps.length >= 2) {
      return { intent: 'multi_step', confidence: 0.8, aoi: hasAOI ? 'current' : null,
        parameters: {}, steps,
        reply: tr(L, 'multi', { n: steps.length, list: steps.map((s) => s.intent).join(' → ') }) };
    }
  }

  return planSingle(raw, { hasAOI, prev, lang: L, layerNames });
}

function planSingle(raw, { hasAOI, prev, lang = 'en', layerNames = [] }) {
  const L = lang === 'sw' ? 'sw' : 'en';
  const lower = raw.toLowerCase().trim();
  // Strip leading filler verbs (SW actions with no alias role) so "fanya NDVI"
  // scores like "NDVI". Verbs that form aliases (show, onyesha, …) stay.
  const core = lower.replace(/^(tafadhali\s+|please\s+)?(fanya|fanyia|toa|angalia|pima|hesabu|tathmini|kadiri|nionyeshe|nipe|niletee)\s+/, '');
  const scores = scoreRegistry(core.length >= 2 ? core : lower);
  const years = extractYears(lower);
  const classCount = extractClassCount(lower);
  const classNames = extractClassNames(raw);
  const algorithm = extractAlgorithm(lower);
  const source = extractSource(lower);

  let [best, bestScore] = topMatches(scores, 1)[0] || [null, 0];
  if (/\bsuitability\b/.test(lower) && /\bahp\b|analytic hierarchy/.test(lower)) best = 'suitability';
  if (years.year && years.year2 && /flood|inundat/.test(lower)
      && /before.?after|compar|change between/.test(lower)) best = 'flood_mapping';

  // ---- First-class semantics (not keyword soup) ----
  const saysClassify = /classif\w*|ainisha|gawa|tenga/.test(lower);
  const saysChange = /chang\w*|compar\w*|between|transition|deforest|loss|gain/.test(lower);
  const names = classNames;

  // "classify into X, Y, Z" with 3+ names -> classification, even if a
  // class word (e.g. built-up) outscores the generic aliases.
  // Classification TARGET = wording outside the "into X, Y, Z" item list
  // ("classify vegetation into forest…" -> vegetation; "classify into …vegetation…" -> LULC).
  const targetText = lower.replace(/into\s+[^.?]+/, ' ');
  const targetVeg = targetText.includes('vegetation') || targetText.includes('mimea');
  const targetLand = /\bland\b|land\s*cover|landcover|\blulc\b|ardhi/.test(targetText);
  if (saysClassify && names && names.length >= 3) {
    best = targetVeg && !targetLand ? 'vegetation' : 'landcover';
    bestScore = Math.max(bestScore, 25);
  } else if (saysClassify && !best) {
    // "classify into five classes" — classify with no target defaults to LULC.
    best = targetVeg ? 'vegetation' : 'landcover';
    bestScore = Math.max(bestScore, 15);
  }
  // "classify using <algorithm>" with no other target -> LULC (not e.g. distance).
  if (saysClassify && algorithm && best &&
      !['landcover', 'vegetation', 'change', 'urban_growth', 'lulc_change'].includes(best)) {
    best = targetVeg ? 'vegetation' : 'landcover';
    bestScore = Math.max(bestScore, 20);
  }
  // Year range + change language -> change detection family.
  if (years.year && years.year2 && saysChange) {
    if (/flood|inundat/.test(lower)) {
      best = 'flood_mapping';
    } else if (/lulc|land\s*cover|landcover|class-?wise|transition|conversion/.test(lower)) {
      best = 'lulc_change';
    } else if (/water|wetland|lake|river|maji|ziwa|mto/.test(lower)) {
      best = 'water_change';
    } else if (/forest|deforestation|misitu/.test(lower)) {
      best = 'deforestation';
    } else if (/burn|fire|dnbr|d\s*nbr/.test(lower)) {
      best = 'dnbr';
    } else {
      best = /urban|built|city|ndbi|sprawl/.test(lower) && !/vegetation|forest|ndvi/.test(lower)
        ? 'urban_growth' : 'change';
    }
    bestScore = Math.max(bestScore, 25);
  }
  if (/flood|inundat/.test(lower) && /sentinel\s*[- ]?1|sar/.test(lower)
      && /before.?after|compar|change between/.test(lower)) best = 'flood_mapping';
  // Year range on a chartable variable without change language -> time series.
  const spectralSeries = best && ANALYSIS_REGISTRY[best]?.index && ANALYSIS_REGISTRY[best].index !== 'DNBR';
  if (years.year && years.year2 && !saysChange && best &&
      (['ndvi', 'evi', 'savi', 'lst', 'rainfall'].includes(best) || spectralSeries) &&
      !/classif/.test(lower)) {
    const variable = spectralSeries ? ANALYSIS_REGISTRY[best].index.toLowerCase()
      : best === 'rainfall' ? 'rainfall' : best === 'lst' ? 'lst' : best;
    return { intent: 'timeseries', confidence: 0.85, aoi: hasAOI ? 'current' : null, backend: 'timeseries',
      parameters: { year: Math.min(years.year, years.year2), year2: Math.max(years.year, years.year2), variable },
      reply: `Yearly ${variable} time series ${Math.min(years.year, years.year2)}–${Math.max(years.year, years.year2)} with trend, chart and latest-year map. Running on the current AOI.` };
  }

  const entry = best ? ANALYSIS_REGISTRY[best] : null;

  // ---- Conversational follow-ups on previous plan ----
  // Pronouns (it / this / that / hiyo / hii): "compare it with 2015",
  // "classify it", "classify it into 5 classes", "what has changed?"
  const saysPronoun = /\bit\b|\bthis\b|\bthat\b|\bhiyo\b|\bhii\b/.test(lower);
  if (prev && prev.backend && saysPronoun) {
    const prevCat = prev.category
      || { landcover: 'landcover', vegetation: 'vegetation', change: 'change', lulc_change: 'change' }[prev.backend]
      || 'spectral';
    if (/compar|linganisha|kulinganisha/.test(lower)) {
      const fam = prev.backend === 'landcover' || prev.backend === 'lulc_change' ? 'lulc_change'
        : ['ndbi', 'urban_growth', 'sprawl'].includes(prev.backend) ? 'urban_growth' : 'change';
      const y = years.year || 2025;
      const y2 = years.year2 || prev.parameters?.year || 2020;
      return { intent: fam, confidence: 0.85, aoi: hasAOI ? 'current' : null, backend: fam,
        parameters: { ...(prev.parameters || {}), year: Math.max(y, y2), year2: Math.min(y, y2) },
        reply: tr(L, 'follow_compare', { what: prev.intent || prev.backend, a: Math.min(y, y2), b: Math.max(y, y2) }) };
    }
    if (/classif|ainisha|gawa/.test(lower)) {
      const fam = prev.backend === 'vegetation' ? 'vegetation' : 'landcover';
      const n = classCount || prev.parameters?.numClasses || 5;
      const names = (classNames && classNames.length === n) ? classNames : prev.parameters?.classNames;
      return { intent: fam, confidence: 0.85, aoi: hasAOI ? 'current' : null, backend: fam,
        parameters: { ...(prev.parameters || {}), numClasses: n, ...(names ? { classNames: names } : {}),
          algorithm: extractAlgorithm(lower) || prev.parameters?.algorithm || 'random_forest' },
        reply: tr(L, 'follow_classify_it', { n }) };
    }
    if (/export|hamisha|pakua|download/.test(lower)) {
      return { intent: 'export_this', confidence: 0.9, aoi: hasAOI ? 'current' : null,
        exportKind: 'current', parameters: {},
        reply: blurbFor('export_this', L, ANALYSIS_REGISTRY.export_this.blurb) + '. ' + tr(L, 'running_aoi') };
    }
  }
  if (/what\s+(has\s+)?changed|nini\s+kimebadilika|nini\s+kilichobadilika/.test(lower)) {
    if (prev?.backend) {
      const fam = prev.backend === 'landcover' ? 'lulc_change'
        : ['ndbi', 'urban_growth', 'sprawl'].includes(prev.backend) ? 'urban_growth' : 'change';
      const y2 = prev.parameters?.year || 2020;
      return { intent: fam, confidence: 0.8, aoi: hasAOI ? 'current' : null, backend: fam,
        parameters: { ...(prev.parameters || {}), year: 2025, year2: y2 },
        reply: tr(L, 'follow_changed', { what: prev.intent || prev.backend, a: y2, b: 2025 }) };
    }
    return { intent: 'clarify', confidence: 0.6, aoi: null, parameters: {},
      reply: tr(L, 'clarify_changed') };
  }
  if (prev && prev.backend) {
    // "use 7 classes" / "give me 7 classes" -> modify previous classification
    if (classCount && !best) {
      if (['landcover', 'vegetation'].includes(prev.backend)) {
        const names = classNames && classNames.length === classCount ? classNames : undefined;
        return { intent: prev.intent, confidence: 0.85, aoi: hasAOI ? 'current' : null,
          backend: prev.backend, local: prev.local,
          parameters: { ...prev.parameters, numClasses: classCount, ...(names ? { classNames: names } : {}) },
          reply: tr(L, 'follow_classes', { intent: prev.intent, n: classCount,
            names: names ? ` (${names.join(', ')})` : '', algo: ALGORITHM_LABEL[prev.parameters?.algorithm || 'random_forest'] }) };
      }
      return { intent: 'clarify', confidence: 0.7, aoi: null, parameters: {},
        reply: tr(L, 'clarify_classes', { n: classCount }) };
    }
    // "use random forest / svm / ..." -> modify method
    if (algorithm && !best) {
      if (['landcover'].includes(prev.backend)) {
        return { intent: prev.intent, confidence: 0.85, aoi: hasAOI ? 'current' : null,
          backend: prev.backend, local: prev.local,
          parameters: { ...prev.parameters, algorithm },
          reply: tr(L, 'follow_algo', { intent: prev.intent, algo: ALGORITHM_LABEL[algorithm] }) };
      }
    }
    // "show only built-up" after LULC -> targeted extraction
    if (!best && /only\s+built|just\s+built|built.?up\s+only|extract\s+built/.test(lower) && prev.backend === 'landcover') {
      return { intent: 'ndbi', confidence: 0.75, aoi: hasAOI ? 'current' : null, backend: 'ndbi',
        parameters: { year: years.year || prev.parameters?.year || 2024, source: source || prev.parameters?.source || 'sentinel2' },
        reply: tr(L, 'follow_builtin') };
    }
    // vague follow-up ("more", "and?") -> repeat previous
    if (!best && /^(more|details?|what else|and|also|again|zaidi|tena)\??$/.test(lower)) {
      return { intent: prev.intent, confidence: 0.7, aoi: hasAOI ? 'current' : null,
        backend: prev.backend, local: prev.local, parameters: { ...prev.parameters },
        reply: tr(L, 'follow_repeat', { intent: prev.intent }) };
    }
  } else if (classCount && !best) {
    // "give me 7 classes" with no context
    return { intent: 'clarify', confidence: 0.7, aoi: null, parameters: {},
      reply: tr(L, 'clarify_classes', { n: classCount }) };
  }

  if (!best || bestScore < 6) {
    const top2 = topMatches(scores, 2);
    if (top2.length >= 2 && top2[0][1] >= 6) {
      return { intent: 'clarify', confidence: 0.6, aoi: null, parameters: {},
        options: [top2[0][0], top2[1][0]],
        reply: tr(L, 'clarify_pick', { a: top2[0][0], b: top2[1][0] }) };
    }
    const methods = searchMethodologies(raw, 1);
    if (methods.length) {
      const method = methods[0];
      return { intent: 'knowledge', confidence: 0.65, aoi: null, parameters: {}, methodId: method.id,
        methodologyStatus: method.status, reply: formatMethodologyReply(method, L) };
    }
    return { intent: 'unknown', confidence: 0.4, aoi: null, parameters: {}, reply: tr(L, 'unknown') };
  }

  // ---- Boundary / export / zonal families (executor routes, not /api/analyze) ----
  const reg0 = ANALYSIS_REGISTRY[best];
  if (reg0 && reg0.exportKind) {
    const spec = extractExportSpec(raw);
    return { intent: best, confidence: 0.85, aoi: hasAOI ? 'current' : null,
      exportKind: reg0.exportKind,
      parameters: { format: spec.format || (reg0.exportKind === 'current' ? null : reg0.exportKind),
        scale: spec.scale, crs: spec.crs },
      reply: blurbFor(best, L, reg0.blurb) + '. ' + tr(L, 'running_aoi') };
  }
  // Pure AOI designation: "use the ward boundary (for the analysis)".
  const useAoi = lower.match(/^\s*(please\s+|tafadhali\s+)?use\s+(the\s+)?(.+?)\s*(boundary|layer|shapefile|geojson)\b(\s+for\s+(the\s+)?analysis)?\s*$/);
  if (useAoi) {
    const target = (useAoi[3] || '').trim() || null;
    return { intent: 'aoi_target', confidence: 0.85, aoi: null, parameters: { targetLayer: target },
      reply: tr(L, 'aoi_target_ask', { target: target || 'boundary' }) };
  }
  if (reg0 && reg0.admin) {
    // Attribute-filter analysis ("analyze wards in Mbozi") beats GAUL lookup.
    const preFilt = extractAttributeFilter(raw);
    if (preFilt && /analyz|analyse|classif|calculat|show|zonal|each|every|only|chambua|ainisha|onyesha/i.test(lower)) {
      const subBest = topMatches(scores, 6).map(([id]) => id)
        .find((id) => id !== 'admin_lookup' && id !== 'zonal'
          && ['ndvi','evi','savi','ndwi','ndbi','lst','rainfall','landcover','vegetation'].includes(ANALYSIS_REGISTRY[id]?.backend));
      const subBackend = subBest ? ANALYSIS_REGISTRY[subBest].backend : 'ndvi';
      return { intent: 'zonal', confidence: 0.8, aoi: hasAOI ? 'current' : null,
        backend: subBackend, subIntent: subBest || 'ndvi',
        parameters: { year: years.year || 2024, year2: years.year2 || 2020, source: source || 'sentinel2',
          zonal: true, filter: preFilt, targetLayer: extractTargetLayer(raw, layerNames) },
        reply: tr(L, 'zonal_plan', { analysis: subBackend }) };
    }
    const adm = extractAdminName(raw);
    if (!adm) {
      return { intent: 'clarify', confidence: 0.65, aoi: null, parameters: {},
        reply: tr(L, 'clarify_admin') };
    }
    return { intent: best, confidence: 0.85, aoi: null, admin: adm, parameters: { ...adm },
      reply: tr(L, 'admin_lookup', { name: adm.name, level: adm.level }) };
  }
  // Zonal: explicit zonal words, or zonal words + a raster analysis in one breath.
  const zonalScore = scores.zonal || 0;
  const rasterBackends = ['ndvi','evi','savi','ndwi','ndbi','lst','rainfall','elevation','slope','landcover','vegetation','flood','change'];
  if ((best === 'zonal' || (zonalScore >= 12 && best && ANALYSIS_REGISTRY[best]?.backend
      && rasterBackends.includes(ANALYSIS_REGISTRY[best].backend)))) {
    let sub = best === 'zonal' ? null : best;
    if (!sub) {
      const runner = topMatches(scores, 6).map(([id]) => id)
        .find((id) => rasterBackends.includes(ANALYSIS_REGISTRY[id]?.backend));
      sub = runner || null;
    }
    if (!sub && prev?.backend && rasterBackends.includes(prev.backend)) {
      sub = { intent: prev.intent, backend: prev.backend, parameters: prev.parameters };
    }
    if (!sub) sub = 'ndvi';
    const subEntry = typeof sub === 'string' ? ANALYSIS_REGISTRY[sub] : null;
    const subBackend = typeof sub === 'string' ? subEntry.backend : sub.backend;
    const subParams = typeof sub === 'string'
      ? { year: years.year || 2024, year2: years.year2 || 2020, source: source || 'sentinel2' }
      : { ...sub.parameters };
    const filt = extractAttributeFilter(raw);
    const target = extractTargetLayer(raw, layerNames);
    return { intent: 'zonal', confidence: 0.85, aoi: hasAOI ? 'current' : null,
      backend: subBackend, subIntent: typeof sub === 'string' ? sub : sub.intent,
      parameters: { ...subParams, zonal: true, labelField: null, filter: filt, targetLayer: target },
      reply: tr(L, 'zonal_plan', { analysis: subBackend }) };
  }

  // ---- Build structured parameters ----
  const params = {};
  const reg = ANALYSIS_REGISTRY[best];
  if (reg.local === 'spatial_statistics') {
    params.method = best;
    const threshold = lower.match(/(?:threshold|within|distance)\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)\s*(m|km|metres?|meters?|kilometres?|kilometers?)\b/);
    if (threshold) params.distanceThreshold = Number(threshold[1]) * (/^k/i.test(threshold[2]) ? 1000 : 1);
    const kval = lower.match(/(?:k\s*=\s*|k[- ]?nearest(?: neighbours?| neighbors?)?\s*)(\d{1,3})/);
    if (kval) params.k = Number(kval[1]);
    const bandwidth = lower.match(/bandwidth\s*(?:=|:|of)?\s*(\d+(?:\.\d+)?)\s*(m|km|metres?|meters?|kilometres?|kilometers?)?/);
    if (bandwidth) params.bandwidth = Number(bandwidth[1]) * (/^k/i.test(bandwidth[2] || '') ? 1000 : 1);
    const cell = lower.match(/(?:cell(?: size)?|resolution)\s*(?:=|:|of)?\s*(\d+(?:\.\d+)?)\s*(m|km)?/);
    if (cell) params.cellSize = Number(cell[1]) * (cell[2] === 'km' ? 1000 : 1);
    const count = lower.match(/(?:sample|points?)\s*(?:size|count)?\s*(?:=|:|of)?\s*(\d{1,5})/);
    if (best === 'spatial_sampling' && count) params.sampleSize = Number(count[1]);
    const power = lower.match(/(?:power|exponent)\s*(?:=|:)?\s*(\d+(?:\.\d+)?)/);
    if (power) params.power = Number(power[1]);
    const sill = lower.match(/sill\s*(?:=|:)?\s*(\d+(?:\.\d+)?)/);
    const range = lower.match(/range\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*(m|km)?/);
    const nugget = lower.match(/nugget\s*(?:=|:)?\s*(\d+(?:\.\d+)?)/);
    if (sill) params.sill = Number(sill[1]);
    if (range) params.range = Number(range[1]) * (range[2] === 'km' ? 1000 : 1);
    if (nugget) params.nugget = Number(nugget[1]);
    const permutations = lower.match(/(\d{2,4})\s*permutations?/);
    if (permutations) params.permutations = Number(permutations[1]);
    const value = raw.match(/(?:field|variable|attribute)\s+(?:named\s+)?["']?([\w.-]+)/i);
    if (value) params.valueField = value[1];
    const predictors = raw.match(/predictors?\s+([\w,.-]+(?:\s+[\w,.-]+)*?)(?=\s+(?:bandwidth|permutations|threshold|k-nearest|distance)\b|$)/i);
    if (predictors && best === 'spatial_regression') params.predictors = predictors[1].split(/[ ,]+/).filter(Boolean);
  }
  if (reg.local === 'drone_analysis') {
    params.method = best === 'orthomosaic_analysis' ? 'orthomosaic_ndvi' : best;
    const base = lower.match(/base\s*plane\s*(?:at|=|:)?\s*(-?\d+(?:\.\d+)?)\s*m?/);
    if (base) params.basePlane = { type: 'horizontal', elevationM: Number(base[1]) };
    const uncertainty = lower.match(/(?:vertical\s+accuracy|accuracy)\s*(?:=|:|of)?\s*(\d+(?:\.\d+)?)\s*m/);
    if (uncertainty) params.verticalAccuracyM = Number(uncertainty[1]);
  }
  // Explicit default year (configured default 2024, surfaced in reply).
  const noYearGiven = !years.year && !years.year2;

  if (reg.needsYear) {
    params.year = years.year || 2024;
    if (['change', 'urban_growth', 'sprawl', 'lulc_change', 'deforestation', 'water_change', 'lst_change', 'trend', 'dnbr', 'flood_mapping'].includes(best)) {
      params.year2 = years.year2 || 2020;
    }
    if (best === 'timeseries') { params.year = years.year2 || years.year || 2015; params.year2 = years.year ? years.year : 2024; }
  }
  if (best === 'lulc_change' && years.years?.length >= 3) params.comparisonYears = years.years;
  if (reg.needsSource) params.source = source || 'sentinel2';
  if (best === 'buffer') params.radius = extractBufferRadius(lower);
  if (best === 'intersection') {
    const mentionedLayers = layerNames.filter((name) => name && lower.includes(String(name).toLowerCase()));
    if (mentionedLayers.length >= 2) {
      params.sourceLayer = mentionedLayers[0];
      params.targetLayer = mentionedLayers[1];
    }
  }

  // Per-tool semantic parameters (registry-driven: index/mode/pollutant defaults)
  if (reg.index) {
    params.index = reg.index;
    Object.assign(params, extractPeriod(lower));
  }
  if (reg.mode) params.mode = reg.mode;
  if (reg.pollutant && !extractPollutant(lower)) params.pollutant = reg.pollutant;
  const opPollutant = extractPollutant(lower);
  if (opPollutant && best === 'airquality') params.pollutant = opPollutant;
  if (best === 'trend') {
    params.test = extractTrendTest(lower);
    const namedIndex = Object.values(ANALYSIS_REGISTRY).find((item) => item.index && item.index !== 'DNBR'
      && (lower.includes(item.index.toLowerCase()) || item.aliases?.some((alias) => alias.length > 4 && lower.includes(alias))));
    params.variable = /rain|precip|mvua/.test(lower) ? 'rainfall'
      : /lst|temperature|joto|heat/.test(lower) ? 'lst'
      : /et\b|evapotranspiration/.test(lower) ? 'et'
      : /no2|nitrogen/.test(lower) ? 'no2' : namedIndex ? namedIndex.index.toLowerCase() : 'ndvi';
  }
  if (best === 'timeseries' && !params.variable) {
    // Water/built-up/LULC have no single-variable series here — ask honestly.
    const hasSpectralSeries = Object.values(ANALYSIS_REGISTRY).some((item) => item.index && item.index !== 'DNBR'
      && (lower.includes(item.index.toLowerCase()) || item.aliases?.some((alias) => alias.length > 4 && lower.includes(alias))));
    if (/water|maji|built|urban|mjini|lulc|land\s*cover|landcover/.test(lower)
        && !hasSpectralSeries && !/ndvi|evi|savi|rain|precip|mvua|lst|temperature|joto|\bet\b|evapotranspiration|no2|nitrogen/.test(lower)) {
      return { intent: 'clarify', confidence: 0.7, aoi: null, parameters: {},
        options: L === 'sw' ? ['NDVI', 'mvua', 'LST'] : ['NDVI', 'rainfall', 'LST'],
        reply: tr(L, 'clarify_series_var') };
    }
    params.variable = extractTimeseriesVariable(lower);
  }
  const statsOp = extractStatsOp(lower);
  if (statsOp && ['ndvi', 'evi', 'savi', 'ndwi', 'ndbi', 'lst', 'rainfall'].includes(best)) params.statsOp = statsOp;
  if (best === 'rainfall' || best === 'et') Object.assign(params, extractPeriod(lower));
  if (best === 'drought') {
    const ind = extractDroughtIndicator(lower);
    if (ind) params.indicator = ind;
  }
  if (best === 'mineral') {
    const ratio = extractBandRatio(raw);
    if (ratio) params.ratio = ratio;
    const preset = extractMineralPreset(lower);
    if (preset) params.preset = preset;
  }
  if (best === 'suitability') {
    const use = /residential|makazi/.test(lower) ? 'residential'
      : /agricultur|crop|mazao|kilimo/.test(lower) ? 'agricultural'
      : /urban|mjini/.test(lower) ? 'urban'
      : /solar|jua/.test(lower) ? 'solar'
      : /industrial|viwanda/.test(lower) ? 'industrial' : 'residential';
    params.use = use;
    const weights = extractWeights(lower);
    params.weights = weights;
    if (/\bahp\b|analytic hierarchy/.test(lower)) params.suitabilityMethod = 'ahp';
    const ahpSpec = lower.match(/(?:ahp|analytic hierarchy).*?criteria\s+([a-z_, ]+?)\s*;\s*matrix\s+([0-9.,;|/ ]+)/);
    if (ahpSpec) {
      const criteria = ahpSpec[1].split(/[, ]+/).filter(Boolean);
      const matrix = ahpSpec[2].split(/[;|/]+/).map((row) => row.split(/[ ,]+/).filter(Boolean).map(Number));
      params.suitabilityMethod = 'ahp';
      params.criteria = criteria;
      params.pairwiseMatrix = matrix;
    }
    const maxSlope = lower.match(/(?:max(?:imum)?\s+slope|slope\s*(?:limit|below|under|<=))\s*(\d+(?:\.\d+)?)/);
    params.constraints = { ...(/exclude water|mask water|water excluded/.test(lower) ? { excludeWater: true } : {}),
      ...(maxSlope ? { maxSlope: Number(maxSlope[1]) } : {}) };
    const sensitivity = lower.match(/sensitivity(?:\s+analysis)?\s*(?:±|\+\/-)?\s*(\d+(?:\.\d+)?)\s*%/);
    if (/sensitivity analysis|weight sensitivity/.test(lower)) {
      params.sensitivity = { perturbation: sensitivity ? Number(sensitivity[1]) / 100 : 0.1 };
    }
    const scenarioText = raw.match(/scenarios?\s+(.+)$/i);
    if (scenarioText && /\|/.test(scenarioText[1])) {
      params.scenarios = scenarioText[1].split('|').map((part, i) => {
        const match = part.trim().match(/^(?:([\w-]+)\s*[:=]\s*)?(.+)$/);
        return { name: match?.[1] || `Scenario ${i + 1}`, weights: extractWeights(match?.[2] || '') };
      }).filter((item) => item.weights);
    }
  }
  if (best === 'hydrology') {
    params.variable = /stream\s*order|strahler/.test(lower) ? 'stream_order'
      : /flow\s*direction|direction/.test(lower) ? 'flow_direction'
      : /flow\s*accumulation|upstream\s*area/.test(lower) ? 'flow_accumulation'
      : /watershed|delineat|basin/.test(lower) ? 'watershed'
      : /catchment\s*(?:stats|statistics)|catchment/.test(lower) ? 'catchment_statistics' : 'drainage';
    const threshold = lower.match(/(?:threshold|upa|upstream area)\s*(?:>=|>|of)?\s*(\d+(?:\.\d+)?)\s*(?:km2|km²|sq\.?\s*km)?/);
    if (threshold) params.thresholds = [Number(threshold[1])];
  }
  if (best === 'flood_mapping') {
    params.mode = /before.?after|compare|change between|compare years/.test(lower) ? 'compare' : 'single';
  }
  if (best === 'slope_classes') {
    const breaks = extractThresholds(raw);
    if (breaks) {
      params.thresholds = breaks;
      params.numClasses = breaks.length - 1;
    } else {
      params.numClasses = classCount || 5;
    }
  }

  // Classes are first-class for landcover + vegetation
  if (best === 'landcover' || best === 'vegetation') {
    const defaults = best === 'landcover' ? DEFAULT_LULC_CLASSES : DEFAULT_VEGETATION_CLASSES;
    let n = classCount || (classNames ? classNames.length : null) || 5;
    n = Math.min(8, Math.max(3, n));
    let names = null;
    if (classNames && classNames.length >= 3 && classNames.length <= 8) {
      names = classNames;
      n = classNames.length;
    } else if (classCount) {
      names = defaults.slice(0, Math.min(classCount, defaults.length));
      while (names.length < n) names.push(`Class ${names.length + 1}`);
    } else {
      names = defaults;
      n = 5;
    }
    params.numClasses = n;
    params.classNames = names;
    params.algorithm = algorithm || 'random_forest';
    params.featureSelection = extractClassificationFeatures(lower);
    params.modelConfig = extractModelConfig(lower, params.algorithm);
    if (/balance\s+classes|class\s+balanc|equal\s+samples|sawazisha\s+madarasa/.test(lower)) params.balanceClasses = true;
    if (/improve|tune|tuning|best.*(tree|accuracy)|boresha/.test(lower)) params.tune = true;
  } else if (algorithm && best === 'change') {
    params.algorithm = algorithm;
  }

  // Flood: mapping vs risk already separated by registry entries
  const needsAOI = !reg.local || reg.local === 'buffer';
  if (needsAOI && !hasAOI) {
    return { intent: best, confidence: 0.9, aoi: null, backend: reg.backend, local: reg.local,
      parameters: params, reply: tr(L, 'aoi_needed', { tool: best }) };
  }

  // Boundary targeting: "use the ward boundary", "analyze wards in Mbozi".
  const tgt = extractTargetLayer(raw, layerNames);
  if (tgt) params.targetLayer = tgt;
  const af = extractAttributeFilter(raw);
  if (af && (best === 'zonal' || /ward|feature|filter|only|in\s+[a-z]/i.test(lower))) params.filter = af;

  const methodNote = params.algorithm ? tr(L, 'method', { x: ALGORITHM_LABEL[params.algorithm] }) + ' ' : '';
  const classNote = params.classNames ? tr(L, 'classes', { n: params.numClasses, list: params.classNames.join(', ') }) + ' ' : '';
  const periodNote = params.year2 && reg.needsYear ? tr(L, 'period_range', { a: params.year2, b: params.year }) + ' '
    : reg.needsYear && params.year && noYearGiven ? tr(L, 'year_default', { y: params.year }) + ' '
    : reg.needsYear && params.year ? tr(L, 'period_year', { y: params.year }) + ' ' : '';
  return { intent: best, confidence: bestScore >= 20 ? 0.95 : bestScore >= 12 ? 0.85 : 0.7,
    aoi: hasAOI ? 'current' : null, backend: reg.backend, local: reg.local, parameters: params,
    reply: `${blurbFor(best, L, reg.blurb)}. ${methodNote}${classNote}${periodNote}${tr(L, 'running_aoi')}` };
}
