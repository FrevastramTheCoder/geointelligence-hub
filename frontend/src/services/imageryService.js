/**
 * Earth Engine REST API Service
 * Analysis helpers using the GEE REST API (no Node.js ee package needed).
 */
import { getToken, apiCall, getMapTileUrl, evaluate } from './geeService';

const BASE = 'https://earthengine.googleapis.com/v1';
const PID = 'finalurbancontrol';

// ---- Raw API helpers ----
async function post(path, body) {
  const tok = getToken();
  const res = await fetch(`${BASE}/${path}`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${tok}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

// ---- Expression builders ----
function geo(geojson) {
  const c = geojson.coordinates;
  const t = geojson.type;
  let g;
  if (t === 'Polygon') g = { functionName: 'Geometry', args: { coords: c, geodesic: true } };
  else if (t === 'Point') g = { functionName: 'Geometry.Point', args: { coords: c } };
  else g = { functionName: 'Geometry.Polygon', args: { coords: c } };
  return wrap(g);
}

function wrap(obj) {
  if (obj.functionName) {
    const a = {};
    for (const [k, v] of Object.entries(obj.args || {})) {
      a[k] = typeof v === 'object' && !Array.isArray(v) ? wrap(v) : { constantValue: v };
    }
    return { functionInvocationValue: { functionName: obj.functionName, arguments: a } };
  }
  return obj;
}

function s2Collection(start, end, geometry) {
  return wrap({
    functionName: 'ImageCollection.filterDate',
    args: {
      collection: wrap({
        functionName: 'ImageCollection.filterBounds',
        args: {
          collection: wrap({ functionName: 'ImageCollection.load', args: { id: 'COPERNICUS/S2_SR_HARMONIZED' } }),
          geometry: geometry,
        },
      }),
      start, end,
    },
  });
}

function median(coll) { return wrap({ functionName: 'ImageCollection.median', args: { collection: coll } }); }

function clip(img, geom) { return wrap({ functionName: 'Image.clip', args: { image: img, geometry: geom } }); }

function normDiff(img, b1, b2) { return wrap({ functionName: 'Image.normalizedDifference', args: { image: img, band1: b1, band2: b2 } }); }

function rename(img, name) { return wrap({ functionName: 'Image.rename', args: { image: img, names: [name] } }); }

function addBands(img1, img2) { return wrap({ functionName: 'Image.addBands', args: { dstImg: img1, srcImg: img2 } }); }

function select(img, bands) { return wrap({ functionName: 'Image.select', args: { image: img, bandSelectors: bands } }); }

function reduce(img, reducerName, geom, scale = 10) {
  return wrap({
    functionName: 'Image.reduceRegion',
    args: {
      image: img,
      reducer: wrap({ functionName: `Reducer.${reducerName}`, args: {} }),
      geometry: geom, scale,
    },
  });
}

function blend(mask, img1, img2) { return wrap({ functionName: 'Image.blend', args: { top: img1, bottom: img2 } }); }

function gte(img, val) { return wrap({ functionName: 'Image.gte', args: { image: img, value: val } }); }
function lt(img, val) { return wrap({ functionName: 'Image.lt', args: { image: img, value: val } }); }
function andOp(a, b) { return wrap({ functionName: 'Image.and', args: { image: a, value: b } }); }
function mask(img, m) { return wrap({ functionName: 'Image.updateMask', args: { image: img, mask: m } }); }

// ---- Public Analysis Functions ----

export async function getSentinel2RGB(geometry, start, end) {
  const g = geo(geometry);
  const s2 = clip(median(s2Collection(start || '2024-01-01', end || '2025-12-31', g)), g);
  const tileUrl = await getMapTileUrl(s2, g);
  return { tileUrl };
}

export async function computeNDVI(geometry, start, end) {
  const g = geo(geometry);
  const s2 = clip(median(s2Collection(start || '2024-01-01', end || '2025-12-31', g)), g);
  const ndvi = rename(normDiff(s2, 'B8', 'B4'), 'NDVI');

  const statsBody = { expression: reduce(ndvi, 'mean', g, 10) };
  const statsRes = await post(`projects/${PID}/value:compute`, statsBody);
  const meanVal = statsRes?.result?.constantValue ?? statsRes?.result;

  const tileUrl = await getMapTileUrl(ndvi, g);

  return {
    type: 'NDVI', label: 'NDVI - Vegetation Index',
    stats: { mean: typeof meanVal === 'number' ? meanVal.toFixed(4) : String(meanVal) },
    tileUrl,
    interpretation: typeof meanVal === 'number'
      ? (meanVal > 0.6 ? 'Dense healthy vegetation.' : meanVal > 0.4 ? 'Moderate vegetation.' : meanVal > 0.2 ? 'Sparse vegetation.' : 'Bare/built-up surface.')
      : 'View map for interpretation.',
  };
}

export async function computeNDBI(geometry, start, end) {
  const g = geo(geometry);
  const s2 = clip(median(s2Collection(start || '2024-01-01', end || '2025-12-31', g)), g);
  const ndbi = rename(normDiff(s2, 'B11', 'B8'), 'NDBI');

  const statsRes = await post(`projects/${PID}/value:compute`, { expression: reduce(ndbi, 'mean', g, 10) });
  const meanVal = statsRes?.result?.constantValue ?? statsRes?.result;
  const tileUrl = await getMapTileUrl(ndbi, g);

  return {
    type: 'NDBI', label: 'NDBI - Built-up Index',
    stats: { mean: typeof meanVal === 'number' ? meanVal.toFixed(4) : String(meanVal) },
    tileUrl,
    interpretation: typeof meanVal === 'number' && meanVal > 0.1 ? 'Significant built-up area detected.' : 'Low built-up density.',
  };
}

export async function computeNDWI(geometry, start, end) {
  const g = geo(geometry);
  const s2 = clip(median(s2Collection(start || '2024-01-01', end || '2025-12-31', g)), g);
  const ndwi = rename(normDiff(s2, 'B3', 'B8'), 'NDWI');

  const statsRes = await post(`projects/${PID}/value:compute`, { expression: reduce(ndwi, 'mean', g, 10) });
  const meanVal = statsRes?.result?.constantValue ?? statsRes?.result;
  const tileUrl = await getMapTileUrl(ndwi, g);

  return {
    type: 'NDWI', label: 'NDWI - Water Index',
    stats: { mean: typeof meanVal === 'number' ? meanVal.toFixed(4) : String(meanVal) },
    tileUrl,
    interpretation: typeof meanVal === 'number' && meanVal > 0 ? 'Water bodies detected.' : 'Dry surface.',
  };
}

export async function computeElevation(geometry) {
  const g = geo(geometry);
  const srtm = clip(
    wrap({ functionName: 'Image.load', args: { id: 'USGS/SRTMGL1_003' } }),
    g
  );
  const elev = rename(srtm, 'Elevation');

  const statsRes = await post(`projects/${PID}/value:compute`, { expression: reduce(elev, 'mean', g, 30) });
  const meanVal = statsRes?.result?.constantValue ?? statsRes?.result;
  const tileUrl = await getMapTileUrl(elev, g);

  return {
    type: 'Elevation', label: 'Elevation (metres)',
    stats: { mean: `${typeof meanVal === 'number' ? meanVal.toFixed(1) : meanVal} m` },
    tileUrl,
    interpretation: `Mean elevation: ${typeof meanVal === 'number' ? meanVal.toFixed(0) : 'N/A'} metres.`,
  };
}

export async function computeSlope(geometry) {
  const g = geo(geometry);
  const srtm = clip(wrap({ functionName: 'Image.load', args: { id: 'USGS/SRTMGL1_003' } }), g);
  const slope = rename(wrap({ functionName: 'Terrain.slope', args: { input: srtm } }), 'Slope');

  const statsRes = await post(`projects/${PID}/value:compute`, { expression: reduce(slope, 'mean', g, 30) });
  const meanVal = statsRes?.result?.constantValue ?? statsRes?.result;
  const tileUrl = await getMapTileUrl(slope, g);

  return {
    type: 'Slope', label: 'Slope (degrees)',
    stats: { mean: `${typeof meanVal === 'number' ? meanVal.toFixed(1) : meanVal}°` },
    tileUrl,
    interpretation: typeof meanVal === 'number'
      ? (meanVal > 15 ? 'Steep terrain.' : meanVal > 5 ? 'Moderate slope.' : 'Flat terrain.')
      : 'View map.',
  };
}

export async function runVegetationAnalysis(geometry, start, end) {
  const g = geo(geometry);
  const s2 = clip(median(s2Collection(start || '2024-01-01', end || '2025-12-31', g)), g);
  const ndvi = rename(normDiff(s2, 'B8', 'B4'), 'NDVI');

  const thresholds = [
    { name: 'Dense (>0.6)', min: 0.6, max: 1.0 },
    { name: 'Moderate (0.4-0.6)', min: 0.4, max: 0.6 },
    { name: 'Sparse (0.2-0.4)', min: 0.2, max: 0.4 },
    { name: 'Bare (<0.2)', min: -1, max: 0.2 },
  ];

  const stats = {};
  for (const t of thresholds) {
    const m = andOp(gte(ndvi, t.min), lt(ndvi, t.max));
    const masked = mask(wrap({ functionName: 'Image.pixelArea', args: {} }), m);
    const areaRes = await post(`projects/${PID}/value:compute`, { expression: reduce(masked, 'sum', g, 10) });
    const areaM2 = areaRes?.result?.constantValue ?? 0;
    stats[t.name] = `${(Number(areaM2) / 10000).toFixed(1)} ha`;
  }

  const tileUrl = await getMapTileUrl(ndvi, g);
  return {
    type: 'Vegetation', label: 'Vegetation Analysis',
    stats, tileUrl,
    interpretation: `Classified vegetation density into 4 categories using NDVI thresholds.`,
  };
}

export async function runChangeDetection(geometry, year1, year2) {
  const g = geo(geometry);
  const s2a = clip(median(s2Collection(`${year1}-01-01`, `${year1}-12-31`, g)), g);
  const s2b = clip(median(s2Collection(`${year2}-01-01`, `${year2}-12-31`, g)), g);
  const ndvi1 = normDiff(s2a, 'B8', 'B4');
  const ndvi2 = normDiff(s2b, 'B8', 'B4');
  const diff = rename(wrap({ functionName: 'Image.subtract', args: { image: ndvi2, value: ndvi1 } }), 'change');

  const statsRes = await post(`projects/${PID}/value:compute`, { expression: reduce(diff, 'mean', g, 10) });
  const meanVal = statsRes?.result?.constantValue ?? statsRes?.result;
  const tileUrl = await getMapTileUrl(diff, g);

  return {
    type: 'ChangeDetection', label: `Change (${year1}-${year2})`,
    stats: { meanChange: typeof meanVal === 'number' ? meanVal.toFixed(4) : String(meanVal) },
    tileUrl,
    interpretation: typeof meanVal === 'number'
      ? (meanVal < -0.1 ? 'Vegetation loss.' : meanVal > 0.1 ? 'Vegetation gain.' : 'Minimal change.')
      : 'View map.',
  };
}
