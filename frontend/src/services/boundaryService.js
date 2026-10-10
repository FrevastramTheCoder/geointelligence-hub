/**
 * BOUNDARY SERVICE — universal AOI input + central AOI state.
 * Extends (never replaces) the drawn-polygon flow: every boundary becomes a
 * normal map layer, and getCurrentAOI() picks the winner by priority:
 * selected feature > designated AOI layer > last uploaded boundary > last drawn.
 */
import JSZip from 'jszip';
import proj4 from 'proj4';

// ---------------------------------------------------------------------------
// CRS: detect EPSG from .prj WKT, transform anything common to WGS84.
// ---------------------------------------------------------------------------
function epsgFromWkt(wkt) {
  if (!wkt) return null;
  const m = String(wkt).match(/AUTHORITY\s*\[\s*["']EPSG["']\s*,\s*["']?(\d+)["']?\s*\]/i);
  if (m) return parseInt(m[1], 10);
  // UTM fallback when AUTHORITY is missing but projection+zone are present
  const utm = String(wkt).match(/UTM\s+zone\s+(\d+)\s*([NS])/i);
  if (utm) return (String(utm[2]).toUpperCase() === 'S' ? 32700 : 32600) + parseInt(utm[1], 10);
  return null;
}

function projDef(epsg) {
  if (epsg === 4326) return 'EPSG:4326';
  if (epsg === 3857) return 'EPSG:3857';
  if (epsg >= 32601 && epsg <= 32660) return `+proj=utm +zone=${epsg - 32600} +datum=WGS84 +units=m +no_defs`;
  if (epsg >= 32701 && epsg <= 32760) return `+proj=utm +zone=${epsg - 32700} +south +datum=WGS84 +units=m +no_defs`;
  return null; // unknown — caller warns and assumes WGS84
}

function reprojectCoords(coords, fromEpsg) {
  const def = projDef(fromEpsg);
  if (!def || fromEpsg === 4326) return coords;
  const conv = proj4(def, 'EPSG:4326');
  const walk = (c) => (typeof c[0] === 'number' ? conv.forward(c) : c.map(walk));
  return walk(coords);
}

function reprojectFeature(f, fromEpsg) {
  if (!fromEpsg || fromEpsg === 4326) return f;
  const g = { ...f.geometry, coordinates: reprojectCoords(f.geometry.coordinates, fromEpsg) };
  return { ...f, geometry: g };
}

// ---------------------------------------------------------------------------
// Minimal Shapefile reader (Point / Polygon / MultiPolygon + DBF attributes).
// ---------------------------------------------------------------------------
function parseShp(buffer) {
  const dv = new DataView(buffer);
  const n = dv.byteLength;
  const getI = (o) => dv.getInt32(o, false);
  const recs = [];
  let off = 100;
  while (off + 8 <= n) {
    const contentLen = getI(off + 4) * 2;
    if (off + 8 + contentLen > n) break;
    const type = dv.getInt32(off + 8, true);
    const base = off + 12;
    if (type === 1 && contentLen >= 16) {
      recs.push({ type: 'Point', coords: [dv.getFloat64(base, true), dv.getFloat64(base + 8, true)] });
    } else if ((type === 5 || type === 15) && contentLen >= 40) {
      const nParts = dv.getInt32(base + 32, true);
      const nPts = dv.getInt32(base + 36, true);
      const parts = [];
      for (let i = 0; i < nParts; i++) parts.push(dv.getInt32(base + 40 + i * 4, true));
      const pts = [];
      let po = base + 40 + nParts * 4;
      for (let i = 0; i < nPts && po + 16 <= n; i++, po += 16) {
        pts.push([dv.getFloat64(po, true), dv.getFloat64(po + 8, true)]);
      }
      const rings = parts.map((s, i) => pts.slice(s, parts[i + 1] ?? pts.length));
      recs.push({ type: 'PolygonRings', rings });
    }
    off += 8 + contentLen;
  }
  return recs;
}

function parseDbf(buffer) {
  try {
    const dv = new DataView(buffer);
    const nRec = dv.getUint32(4, true);
    const headerLen = dv.getUint16(8, true);
    const recLen = dv.getUint16(10, true);
    const fields = [];
    for (let o = 32; o < headerLen - 1; o += 32) {
      let name = '';
      for (let i = 0; i < 11; i++) {
        const c = dv.getUint8(o + i);
        if (c === 0) break;
        name += String.fromCharCode(c);
      }
      const type = String.fromCharCode(dv.getUint8(o + 11));
      const len = dv.getUint8(o + 16);
      const dec = dv.getUint8(o + 17);
      if (name) fields.push({ name, type, len, dec });
    }
    const rows = [];
    const td = new TextDecoder('utf-8');
    for (let r = 0; r < nRec; r++) {
      const base = headerLen + r * recLen;
      if (base + recLen > dv.byteLength) break;
      const row = {};
      let o = base + 1;
      for (const f of fields) {
        const raw = td.decode(new Uint8Array(buffer, o, f.len)).trim();
        o += f.len;
        if (f.type === 'N' || f.type === 'F') {
          const v = parseFloat(raw);
          row[f.name] = Number.isNaN(v) ? raw : v;
        } else if (f.type === 'D' && /^\d{8}$/.test(raw)) {
          row[f.name] = `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
        } else if (f.type === 'L') {
          row[f.name] = /^[YT]/i.test(raw);
        } else {
          row[f.name] = raw;
        }
      }
      rows.push(row);
    }
    return rows;
  } catch {
    return [];
  }
}

function parseKML(text, fileName) {
  const parser = new DOMParser();
  const kml = parser.parseFromString(text, 'text/xml');
  const features = [];
  kml.querySelectorAll('Placemark').forEach((pm, i) => {
    const props = { name: pm.querySelector('name')?.textContent?.trim() || `KML Feature ${i + 1}` };
    pm.querySelectorAll('SimpleData, Data').forEach((d) => {
      const k = d.getAttribute('name');
      if (k) props[k] = d.textContent?.trim();
    });
    const poly = pm.querySelector('Polygon > outerBoundaryIs > LinearRing > coordinates')?.textContent?.trim()
      || pm.querySelector('Polygon coordinates')?.textContent?.trim();
    if (poly) {
      const ring = poly.split(/\s+/).filter(Boolean).map((c) => c.split(',').slice(0, 2).map(Number)).filter((p) => p.every(Number.isFinite));
      if (ring.length >= 4) {
        features.push({ type: 'Feature', properties: props, geometry: { type: 'Polygon', coordinates: [ring] } });
        return;
      }
    }
    const line = pm.querySelector('LineString > coordinates')?.textContent?.trim();
    if (line) {
      const pts = line.split(/\s+/).filter(Boolean).map((c) => c.split(',').slice(0, 2).map(Number)).filter((p) => p.every(Number.isFinite));
      if (pts.length >= 2) {
        features.push({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: pts } });
        return;
      }
    }
    const pt = pm.querySelector('Point > coordinates')?.textContent?.trim();
    if (pt) {
      const [lng, lat] = pt.split(',').map(Number);
      if (Number.isFinite(lng) && Number.isFinite(lat)) {
        features.push({ type: 'Feature', properties: props, geometry: { type: 'Point', coordinates: [lng, lat] } });
      }
    }
  });
  return { features, fileName };
}

// ---------------------------------------------------------------------------
// Public: parse any supported boundary file -> normalized {features, meta}.
// ---------------------------------------------------------------------------
export async function parseBoundaryFile(file) {
  const name = file.name || 'upload';
  const ext = name.split('.').pop().toLowerCase();
  let features = [];
  let crs = 4326;
  let crsNote = 'WGS84 (EPSG:4326)';

  if (['geojson', 'json'].includes(ext)) {
    const data = JSON.parse(await file.text());
    if (data.type === 'FeatureCollection') features = data.features || [];
    else if (data.type === 'Feature') features = [data];
    else if (data.type && data.coordinates) features = [{ type: 'Feature', properties: {}, geometry: data }];
    else throw new Error('Not a GeoJSON geometry/feature. Export it from QGIS as GeoJSON first.');
  } else if (ext === 'kml') {
    features = parseKML(await file.text(), name).features;
  } else if (ext === 'kmz') {
    const zip = await JSZip.loadAsync(file);
    const entry = Object.keys(zip.files).find((k) => k.toLowerCase().endsWith('.kml'));
    if (!entry) throw new Error('KMZ has no .kml inside.');
    features = parseKML(await zip.files[entry].async('text'), name).features;
  } else if (ext === 'zip') {
    const zip = await JSZip.loadAsync(file);
    const names = Object.keys(zip.files).filter((k) => !zip.files[k].dir);
    const shpName = names.find((k) => k.toLowerCase().endsWith('.shp'));
    if (!shpName) throw new Error('ZIP has no .shp. For Shapefiles, zip .shp + .shx + .dbf (+ .prj) together.');
    const base = shpName.replace(/\.shp$/i, '');
    const byLower = {};
    names.forEach((k) => { byLower[k.toLowerCase()] = k; });
    const shpBuf = await zip.files[shpName].async('arraybuffer');
    const shxName = byLower[`${base.toLowerCase()}.shx`];
    const dbfName = byLower[`${base.toLowerCase()}.dbf`];
    const prjName = byLower[`${base.toLowerCase()}.prj`];
    if (!shxName || !dbfName) throw new Error('Incomplete Shapefile: .shx and .dbf are required beside .shp.');
    let epsg = 4326;
    if (prjName) {
      const wkt = await zip.files[prjName].async('text');
      epsg = epsgFromWkt(wkt) || 4326;
    }
    crs = epsg;
    crsNote = epsg === 4326
      ? (prjName ? 'WGS84 (EPSG:4326, from .prj)' : 'No .prj found — assumed WGS84 (EPSG:4326). Verify on the map!')
      : `EPSG:${epsg} (from .prj) → reprojected to WGS84`;
    const recs = parseShp(shpBuf);
    const rows = parseDbf(await zip.files[dbfName].async('arraybuffer'));
    features = recs.map((r, i) => ({
      type: 'Feature',
      properties: { ...(rows[i] || {}), _fid: i + 1 },
      geometry: r.type === 'Point'
        ? { type: 'Point', coordinates: r.coords }
        : { type: 'Polygon', coordinates: r.rings.length > 1 ? r.rings : [r.rings[0] || []] },
    })).filter((f) => f.geometry.coordinates.length && f.geometry.coordinates[0]?.length >= (f.geometry.type === 'Point' ? 2 : 4));
    if (epsg !== 4326 && projDef(epsg)) features = features.map((f) => reprojectFeature(f, epsg));
    if (epsg !== 4326 && !projDef(epsg)) {
      throw new Error(`CRS EPSG:${epsg} is not transformable here. Re-export the layer as WGS84 in QGIS and retry.`);
    }
  } else if (ext === 'gpkg') {
    throw new Error('GeoPackage cannot be read in the browser yet. In QGIS: right-click layer → Export → Save as GeoJSON or zipped Shapefile, then upload that.');
  } else {
    throw new Error(`Unsupported format .${ext}. Use GeoJSON, KML/KMZ, or zipped Shapefile.`);
  }

  if (!features.length) throw new Error('No usable features found in this file.');
  return { features, meta: { fileName: name, format: ext, crs, crsNote, count: features.length } };
}

// ---------------------------------------------------------------------------
// Validation (turf, lazy) -> {valid, warnings[], info{areaHa, bounds}}.
// ---------------------------------------------------------------------------
export async function validateBoundary(features) {
  const turf = await import('@turf/turf');
  const warnings = [];
  let areaHa = 0;
  try {
    const fc = { type: 'FeatureCollection', features };
    const bbox = turf.bbox(fc);
    if (!bbox.every(Number.isFinite)) throw new Error('bad-coords');
    if (bbox[0] < -180 || bbox[2] > 180 || bbox[1] < -90 || bbox[3] > 90) {
      warnings.push('Coordinates are outside lon/lat ranges — the file may use a projected CRS. Re-export as WGS84.');
    }
    for (const f of features) {
      const g = f.geometry;
      if (!g || !g.coordinates || !g.coordinates.length) warnings.push(`Feature "${f.properties?.name || '?'}": empty geometry.`);
      if (g?.type === 'Polygon') {
        const ring = g.coordinates[0] || [];
        if (ring.length >= 4) {
          const [a, b] = [ring[0], ring[ring.length - 1]];
          if (a[0] !== b[0] || a[1] !== b[1]) warnings.push(`Feature "${f.properties?.name || '?'}": ring auto-closed.`);
        }
        try {
          if (turf.kinks(f).features.length) warnings.push(`Feature "${f.properties?.name || '?'}": self-intersection detected.`);
        } catch { /* kinks needs valid input; skip */ }
      }
      try {
        areaHa += turf.area(f) / 10000;
      } catch { /* ignore per-feature */ }
    }
    if (areaHa > 1000000) warnings.push('Very large AOI (>1M ha): analyses will be slow — consider a smaller area.');
    return { valid: true, warnings, info: { areaHa: Math.round(areaHa * 10) / 10, count: features.length } };
  } catch {
    return { valid: false, warnings: ['Invalid geometry or coordinates.'], info: { areaHa: 0, count: features.length } };
  }
}

// ---------------------------------------------------------------------------
// CENTRAL AOI — priority: selected feature > designated layer > last upload >
// last drawn. Every analysis/AI request goes through here.
// ---------------------------------------------------------------------------
export function getCurrentAOI(state) {
  const layers = (state.layers || []).filter((l) => l.type === 'geojson' && l.visible !== false && l.data);
  if (!layers.length) return null;
  const byId = (id) => layers.find((l) => l.id === id);
  const toFeature = (d) => (d?.type === 'Feature' ? d : { type: 'Feature', properties: {}, geometry: d?.geometry || d });

  // 1. Explicitly selected feature
  const sel = state.selectedFeature;
  if (sel) {
    const layer = byId(sel.layerId);
    const feat = layer?.data?.type === 'FeatureCollection'
      ? layer.data.features?.[sel.index]
      : (sel.index === 0 ? layer?.data : null);
    if (feat && feat.geometry) {
      return { kind: 'feature', layer, feature: feat, geometry: feat.geometry, label: `${layer.name} — ${feat.properties?.name || `feature ${sel.index + 1}`}` };
    }
  }
  // 2. Designated AOI layer
  if (state.aoiLayerId) {
    const layer = byId(state.aoiLayerId);
    if (layer?.data) {
      return { kind: 'layer', layer, feature: toFeature(layer.data), geometry: layer.data, label: layer.name };
    }
  }
  // 3. Last uploaded boundary
  const uploaded = [...layers].reverse().find((l) => l.boundary);
  if (uploaded) {
    return { kind: 'layer', layer: uploaded, feature: toFeature(uploaded.data), geometry: uploaded.data, label: uploaded.name };
  }
  // 4. Last drawn polygon
  const last = layers[layers.length - 1];
  return { kind: 'layer', layer: last, feature: toFeature(last.data), geometry: last.data, label: last.name };
}

export function layerMatchesAttribute(layer, field, value) {
  const feats = layer?.data?.type === 'FeatureCollection' ? layer.data.features : [layer?.data];
  const want = String(value).toLowerCase();
  return (feats || []).map((f, i) => ({ f, i })).filter(({ f }) => {
    const props = f?.properties || {};
    return Object.values(props).some((v) => String(v).toLowerCase().includes(want))
      || (field && String(props[field] ?? props[field.toUpperCase()] ?? '').toLowerCase().includes(want));
  });
}
