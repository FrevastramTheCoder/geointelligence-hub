/**
 * EXPORT SERVICE — talks to /api/export*, builds QGIS download links.
 * Server files download with ?token= (browser links can't set headers);
 * Google-hosted URLs (GeoTIFF/PNG) download directly.
 */
import { API, TOKEN_KEY } from '../config/api';

export function getSessionToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

function headers() {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${getSessionToken()}` };
}

async function post(url, body) {
  const res = await fetch(url, { method: 'POST', headers: headers(), body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Export failed (${res.status})`);
  return data;
}

async function get(url) {
  const res = await fetch(url, { headers: headers() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export function requestExport(payload) {
  return post(API.EXPORT, payload);
}

export function requestZonal(payload) {
  return post(API.ZONAL, payload);
}

export function requestAdminBoundary(payload) {
  return post(API.ADMIN_BOUNDARY, payload);
}

export function requestBoundaryExport(payload) {
  return post(`${API.EXPORT}-boundary`, payload);
}

export function listExports() {
  return get(API.EXPORTS);
}

export function exportStatus(taskId) {
  return get(`${API.EXPORT_STATUS}?task=${encodeURIComponent(taskId)}`);
}

/** Href the browser can open directly (file record or Google URL). */
export function downloadHref(record) {
  if (!record) return null;
  if (record.downloadUrl) return record.downloadUrl;
  const path = record.download || (record.exportId ? `${API.EXPORT_DOWNLOAD}?id=${record.exportId}` : null);
  if (!path) return null;
  if (/^https?:/.test(path)) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}token=${encodeURIComponent(getSessionToken())}`;
}

export function isRasterResult(result) {
  if (!result) return false;
  if (result.tileUrl || result.layer?.tile_url) return true;
  return false;
}

export function isCategoricalResult(result) {
  const legend = result?.legend;
  return Array.isArray(legend) && legend.length > 0;
}

/** Formats that honestly apply to this result (never offer vector for continuous). */
export function compatibleFormats(result) {
  if (!result) return [];
  if (result.geometry?.type === 'FeatureCollection') {
    return [
      { id: 'geojson', label: 'GeoJSON result features' },
      { id: 'csv', label: 'CSV statistics' },
    ];
  }
  const out = [
    { id: 'geotiff', label: 'GeoTIFF (QGIS raster)' },
    { id: 'png', label: 'PNG preview' },
    { id: 'csv', label: 'CSV statistics' },
  ];
  if (isCategoricalResult(result)) {
    out.push(
      { id: 'geojson', label: 'GeoJSON classes' },
      { id: 'shp', label: 'Shapefile ZIP' },
      { id: 'kml', label: 'KML' },
      { id: 'kmz', label: 'KMZ' },
    );
  }
  return out;
}
