import { saveAs } from 'file-saver';
import * as XLSX from 'xlsx';

export function exportGeoJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/geo+json' });
  saveAs(blob, `${filename}.geojson`);
}

export function exportCSV(data, filename) {
  const rows = [];
  if (Array.isArray(data)) {
    const headers = Object.keys(data[0] || {});
    rows.push(headers.join(','));
    data.forEach(row => rows.push(headers.map(h => JSON.stringify(row[h] ?? '')).join(',')));
  } else {
    Object.entries(data).forEach(([k, v]) => rows.push(`${k},${v}`));
  }
  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
  saveAs(blob, `${filename}.csv`);
}

export function exportExcel(data, filename) {
  const ws = XLSX.utils.json_to_sheet(Array.isArray(data) ? data : [data]);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Results');
  XLSX.writeFile(wb, `${filename}.xlsx`);
}

export function exportPNG(canvasId, filename) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.toBlob((blob) => { saveAs(blob, `${filename}.png`); });
}

export function generateId() {
  return `id_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
