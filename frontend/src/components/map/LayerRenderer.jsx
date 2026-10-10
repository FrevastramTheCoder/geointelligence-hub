import { GeoJSON, TileLayer } from 'react-leaflet';
import L from 'leaflet';
import { useApp } from '../../context/AppContext';

export function LayerRenderer({ layers }) {
  const { state } = useApp();
  if (!layers?.length) return null;

  return layers.filter(l => l.visible !== false).map((layer) => {
    if (layer.type === 'geojson' && layer.data) {
      const features = layer.data.type === 'FeatureCollection' ? layer.data.features || [] : [layer.data];
      const values = features.map((f) => f.properties?.[layer.styleBy]).filter((v) => typeof v === 'number' && Number.isFinite(v));
      const min = values.length ? Math.min(...values) : 0;
      const max = values.length ? Math.max(...values) : 1;
      const ramp = ['#313695', '#4575b4', '#74add1', '#abd9e9', '#ffffbf', '#fdae61', '#f46d43', '#d73027'];
      const categorical = { 'High-High': '#d73027', 'Low-Low': '#4575b4', 'High-Low': '#fdae61', 'Low-High': '#abd9e9', 'Not significant': '#bdbdbd', 'Hot spot': '#d73027', 'Cold spot': '#4575b4' };
      const colorFor = (feature) => {
        const value = feature.properties?.[layer.styleBy];
        if (typeof value === 'string') return categorical[value] || layer.color || '#3388ff';
        if (typeof value === 'number' && Number.isFinite(value)) {
          const t = max === min ? 0.5 : Math.max(0, Math.min(1, (value - min) / (max - min)));
          return ramp[Math.round(t * (ramp.length - 1))];
        }
        return layer.color || '#3388ff';
      };
      return (
        <GeoJSON
          key={layer.id}
          data={layer.data}
          pointToLayer={(feature, latlng) => {
            const color = colorFor(feature);
            return L.circleMarker(latlng, { radius: 6, color, fillColor: color, fillOpacity: 0.8, weight: 1 });
          }}
          style={(feature) => ({
            color: colorFor(feature || {}),
            fillColor: colorFor(feature || {}),
            fillOpacity: 0.3,
            weight: 2,
          })}
          onEachFeature={(feature, target) => {
            const escape = (value) => String(value).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
            const rows = Object.entries(feature.properties || {}).map(([key, value]) => `<b>${escape(key)}</b>: ${escape(value)}`);
            if (rows.length) target.bindPopup(rows.join('<br/>'));
          }}
        />
      );
    }
    if (layer.type === 'image' && layer.url) {
      return (
        <TileLayer
          key={layer.id}
          url={layer.url}
          opacity={0.7}
          attribution="Google Earth Engine"
        />
      );
    }
    return null;
  });
}
