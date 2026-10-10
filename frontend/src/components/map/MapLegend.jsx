import { useEffect } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { useApp } from '../../context/AppContext';

// EXACT GEE visualization palettes (must match server.py)
const LEGENDS = {
  ndvi: {
    title: 'NDVI',
    items: [
      { color: '#ff0000', label: 'Low (< 0)' },
      { color: '#ffff00', label: '0.2' },
      { color: '#00ff00', label: '0.8 (Dense)' },
    ],
  },
  ndbi: {
    title: 'NDBI - Built-up',
    items: [
      { color: '#00FF00', label: 'Low (Vegetation)' },
      { color: '#FFFF00', label: 'Moderate' },
      { color: '#FF0000', label: 'High (Built-up)' },
    ],
  },
  ndwi: {
    title: 'NDWI - Water',
    items: [
      { color: '#8B4513', label: 'Dry land' },
      { color: '#FFD700', label: 'Moisture' },
      { color: '#00BFFF', label: 'Water' },
      { color: '#0000CD', label: 'Deep water' },
    ],
  },
  elevation: {
    title: 'Elevation (m)',
    items: [
      { color: '#006400', label: 'Low' },
      { color: '#32CD32', label: 'Mid-low' },
      { color: '#FFD700', label: 'Mid' },
      { color: '#8B4513', label: 'High' },
      { color: '#FFFFFF', label: 'Peak' },
    ],
  },
  slope: {
    title: 'Slope',
    items: [
      { color: '#008000', label: 'Flat (0-10°)' },
      { color: '#ffff00', label: 'Moderate (10-20°)' },
      { color: '#ffa500', label: 'Steep (20-35°)' },
      { color: '#ff0000', label: 'Very Steep (>35°)' },
    ],
  },
  change: {
    title: 'Change Detection',
    items: [
      { color: '#FF0000', label: 'Major loss' },
      { color: '#FFA500', label: 'Minor loss' },
      { color: '#FFFF00', label: 'No change' },
      { color: '#90EE90', label: 'Minor gain' },
      { color: '#006400', label: 'Major gain' },
    ],
  },
  vegetation: {
    title: 'Vegetation (NDVI)',
    items: [
      { color: '#d73027', label: 'Bare/Ground' },
      { color: '#FFD700', label: 'Rangeland' },
      { color: '#FF8C00', label: 'Shrubs' },
      { color: '#228B22', label: 'Cropland' },
      { color: '#004d00', label: 'Forest' },
    ],
  },
  // Land Cover datasets - colors MUST match server.py LC_DATASETS palettes
  landcover: {
    title: 'Land Cover (RF)',
    items: [
      { color: '#FF0000', label: 'Built-up' },
      { color: '#00FF00', label: 'Vegetation' },
      { color: '#FFD700', label: 'Bare Soil' },
      { color: '#0000FF', label: 'Water' },
    ],
  },
  dynamicworld: {
    title: 'Dynamic World',
    items: [
      { color: '#419BDF', label: 'Water' },
      { color: '#397D49', label: 'Trees' },
      { color: '#88B053', label: 'Grass' },
      { color: '#7A87C6', label: 'Flooded Veg' },
      { color: '#E49635', label: 'Crops' },
      { color: '#DFC35A', label: 'Shrub/Scrub' },
      { color: '#C4281B', label: 'Built-up' },
      { color: '#A59B8F', label: 'Bare' },
      { color: '#B39FE1', label: 'Snow/Ice' },
    ],
  },
  worldcover_v200: {
    title: 'ESA WorldCover',
    items: [
      { color: '#006400', label: 'Trees' },
      { color: '#ffbb22', label: 'Shrubland' },
      { color: '#ffff4c', label: 'Grassland' },
      { color: '#f096ff', label: 'Cropland' },
      { color: '#fa0000', label: 'Built-up' },
      { color: '#b4b4b4', label: 'Bare' },
      { color: '#f0f0f0', label: 'Snow/Ice' },
      { color: '#0064c8', label: 'Water' },
      { color: '#0096a0', label: 'Wetland' },
      { color: '#00cf75', label: 'Mangroves' },
      { color: '#fae6a0', label: 'Moss' },
    ],
  },
  modis_lc: {
    title: 'MODIS Land Cover',
    items: [
      { color: '#05450a', label: 'Forest' },
      { color: '#78d203', label: 'Shrub/Savanna' },
      { color: '#dade48', label: 'Grassland' },
      { color: '#f9ffa4', label: 'Cropland' },
      { color: '#c24f44', label: 'Urban' },
      { color: '#1c0dff', label: 'Water' },
    ],
  },
  modis_cmg: {
    title: 'MODIS CMG',
    items: [
      { color: '#05450a', label: 'Forest' },
      { color: '#78d203', label: 'Shrub/Savanna' },
      { color: '#dade48', label: 'Grassland' },
      { color: '#f9ffa4', label: 'Cropland' },
      { color: '#c24f44', label: 'Urban' },
      { color: '#1c0dff', label: 'Water' },
    ],
  },
  copernicus_lc: {
    title: 'Copernicus GLCS',
    items: [
      { color: '#282828', label: 'Unknown' },
      { color: '#ffbb22', label: 'Shrubs' },
      { color: '#ffff4c', label: 'Herbaceous' },
      { color: '#f096ff', label: 'Cropland' },
      { color: '#fa0000', label: 'Urban' },
      { color: '#b4b4b4', label: 'Bare' },
      { color: '#0032c8', label: 'Water' },
      { color: '#009900', label: 'Forest' },
    ],
  },
  nlcd: {
    title: 'NLCD (USA)',
    items: [
      { color: '#466b9f', label: 'Water' },
      { color: '#d99282', label: 'Developed' },
      { color: '#68ab5f', label: 'Forest' },
      { color: '#dfdfc2', label: 'Pasture/Crops' },
      { color: '#b8d9eb', label: 'Wetland' },
    ],
  },
  corine: {
    title: 'CORINE (EU)',
    items: [
      { color: '#e6004d', label: 'Urban fabric' },
      { color: '#ff0000', label: 'Industrial' },
      { color: '#80ff00', label: 'Forest' },
      { color: '#ffff00', label: 'Agriculture' },
      { color: '#ccffcc', label: 'Wetland' },
      { color: '#000080', label: 'Water' },
    ],
  },
  glc_fcs30: {
    title: 'GLC_FCS30D',
    items: [
      { color: '#006400', label: 'Forest' },
      { color: '#ffff00', label: 'Cropland' },
      { color: '#ff0000', label: 'Urban' },
      { color: '#0000ff', label: 'Water' },
      { color: '#dcdcdc', label: 'Bare' },
    ],
  },
  flood: {
    title: 'Flood Risk',
    items: [
      { color: '#FF0000', label: 'High Risk' },
      { color: '#FFA500', label: 'Medium Risk' },
      { color: '#FFFF00', label: 'Low Risk' },
      { color: '#006400', label: 'Safe (No Risk)' },
    ],
  },
  flood_mapping: {
    title: 'Flood Mapping (SAR)',
    items: [
      { color: '#e0e0e0', label: 'Non-water' },
      { color: '#0000CD', label: 'Flooded/Water' },
    ],
  },
  evi: {
    title: 'EVI',
    items: [
      { color: '#d73027', label: 'Low' },
      { color: '#fee08b', label: 'Moderate' },
      { color: '#1a9850', label: 'Dense' },
    ],
  },
  savi: {
    title: 'SAVI',
    items: [
      { color: '#d73027', label: 'Low' },
      { color: '#fee08b', label: 'Moderate' },
      { color: '#1a9850', label: 'Dense' },
    ],
  },
  lst: {
    title: 'LST (°C)',
    items: [
      { color: '#0000ff', label: 'Cool' },
      { color: '#ffff00', label: 'Warm' },
      { color: '#ff0000', label: 'Hot (>35°C)' },
    ],
  },
  rainfall: {
    title: 'Rainfall (mm/yr)',
    items: [
      { color: '#ffffff', label: 'Low' },
      { color: '#00ffff', label: 'Moderate' },
      { color: '#0000ff', label: 'High' },
    ],
  },
  erosion: {
    title: 'Soil Loss (t/ha/yr)',
    items: [
      { color: '#1a9850', label: 'Slight (<5)' },
      { color: '#FFD700', label: 'Moderate (5-15)' },
      { color: '#FF0000', label: 'Severe (>15)' },
    ],
  },
  drought: {
    title: 'Drought (NDVI anomaly)',
    items: [
      { color: '#1a9850', label: 'Normal' },
      { color: '#FFFF00', label: 'Moderate' },
      { color: '#FF0000', label: 'Severe' },
    ],
  },
  urban_growth: {
    title: 'Urban Growth (NDBI Δ)',
    items: [
      { color: '#0000ff', label: 'Loss' },
      { color: '#ffffff', label: 'No change' },
      { color: '#ff0000', label: 'Growth' },
    ],
  },
  timeseries: {
    title: 'Time Series',
    items: [{ color: '#1565c0', label: 'Yearly values (see chart)' }],
  },
  spectral_index: {
    title: 'Spectral Index',
    items: [
      { color: '#ff0000', label: 'Low' },
      { color: '#ffff00', label: 'Moderate' },
      { color: '#00ff00', label: 'High' },
    ],
  },
  imagery: {
    title: 'Satellite Imagery',
    items: [{ color: '#888888', label: 'Composite (see map)' }],
  },
  aspect: {
    title: 'Aspect',
    items: [
      { color: '#0000ff', label: 'North' },
      { color: '#00ff00', label: 'East' },
      { color: '#ff0000', label: 'South' },
      { color: '#ffff00', label: 'West' },
    ],
  },
  hillshade: {
    title: 'Hillshade',
    items: [
      { color: '#000000', label: 'Shadow' },
      { color: '#ffffff', label: 'Lit' },
    ],
  },
  slope_classes: {
    title: 'Slope Classes',
    items: [{ color: '#1a9850', label: 'Flat → steep (see stats)' }],
  },
  lst_change: {
    title: 'LST Change (°C)',
    items: [
      { color: '#0000ff', label: 'Cooling' },
      { color: '#ffffff', label: 'No change' },
      { color: '#ff0000', label: 'Warming' },
    ],
  },
  uhi: {
    title: 'UHI (°C vs rural)',
    items: [
      { color: '#0000ff', label: 'Cool' },
      { color: '#ffff00', label: 'Warm' },
      { color: '#ff0000', label: 'Hot island' },
    ],
  },
  uftvi: {
    title: 'UTFVI',
    items: [
      { color: '#0000ff', label: 'None' },
      { color: '#ffff00', label: 'Middle' },
      { color: '#ff0000', label: 'Strongest' },
    ],
  },
  sprawl: {
    title: 'Urban Sprawl',
    items: [
      { color: '#ff0000', label: 'Pre-existing' },
      { color: '#ff9800', label: 'Infill/Edge' },
      { color: '#ffff00', label: 'Leapfrog' },
    ],
  },
  lulc_change: {
    title: 'LULC Change',
    items: [
      { color: '#1a9850', label: 'Stable' },
      { color: '#ff0000', label: 'Changed' },
    ],
  },
  deforestation: {
    title: 'Forest Loss',
    items: [
      { color: '#1a9850', label: 'No loss' },
      { color: '#ff0000', label: 'Loss' },
    ],
  },
  et: {
    title: 'ET (mm)',
    items: [
      { color: '#ffffff', label: 'Low' },
      { color: '#1a9850', label: 'High' },
    ],
  },
  airquality: {
    title: 'Air Quality',
    items: [
      { color: '#00ff00', label: 'Low' },
      { color: '#ff0000', label: 'High' },
    ],
  },
  hydrology: {
    title: 'Drainage',
    items: [
      { color: '#00BFFF', label: 'Streams' },
      { color: '#000080', label: 'Major rivers' },
    ],
  },
  landslide: {
    title: 'Landslide Susceptibility',
    items: [
      { color: '#1a9850', label: 'Low' },
      { color: '#FFFF00', label: 'Moderate' },
      { color: '#FF9800', label: 'High' },
      { color: '#FF0000', label: 'Very high' },
    ],
  },
  salinity: {
    title: 'Salinity Indicator',
    items: [
      { color: '#1a9850', label: 'Non-saline' },
      { color: '#FF0000', label: 'High' },
    ],
  },
  moisture: {
    title: 'NDMI',
    items: [
      { color: '#8B4513', label: 'Dry' },
      { color: '#0000CD', label: 'Moist' },
    ],
  },
  mineral: {
    title: 'Mineral Indicator',
    items: [
      { color: '#000000', label: 'Background' },
      { color: '#FF0000', label: 'Anomalous' },
    ],
  },
  suitability: {
    title: 'Suitability',
    items: [
      { color: '#FF0000', label: 'Poor' },
      { color: '#FFFF00', label: 'Fair' },
      { color: '#91cf60', label: 'Good' },
      { color: '#1a9850', label: 'Excellent' },
    ],
  },
  trend: {
    title: 'Trend',
    items: [{ color: '#1565c0', label: 'Yearly values (see chart)' }],
  },
  waterlogging: {
    title: 'Waterlogging',
    items: [
      { color: '#e0e0e0', label: 'Not waterlogged' },
      { color: '#FF9800', label: 'Waterlogged' },
    ],
  },
};

export function MapLegend({ analysisType, serverLegend, serverTitle }) {
  const map = useMap();
  const app = useApp();
  // Server-driven legend first (dynamic classes), hardcoded fallback second.
  let serverDriven = null;
  try {
    const result = app?.state?.results;
    const rl = serverLegend ?? result?.legend;
    const rt = serverTitle ?? result?.label;
    if (Array.isArray(rl) && rl.length) {
      serverDriven = { title: rt || 'Legend', items: rl.map((l) => ({ color: l.color || '#888888', label: String(l.label ?? l.value ?? '') })) };
    } else if (rl && rl.type === 'continuous') {
      serverDriven = { title: rt || 'Legend',
        items: [{ color: '#888888', label: `Continuous ${rl.min} → ${rl.max}${rl.unit ? ' ' + rl.unit : ''}` }] };
    }
    if (!serverDriven && ['SpatialStatistics', 'DroneMining'].includes(result?.type) && result?.styleBy) {
      const features = result.geometry?.features || [];
      const values = features.map((feature) => feature.properties?.[result.styleBy]);
      const ramp = ['#313695', '#4575b4', '#74add1', '#abd9e9', '#ffffbf', '#fdae61', '#f46d43', '#d73027'];
      const categories = [...new Set(values.filter((value) => typeof value === 'string'))];
      if (categories.length) {
        const colors = { 'High-High': '#d73027', 'Low-Low': '#4575b4', 'High-Low': '#fdae61', 'Low-High': '#abd9e9', 'Not significant': '#bdbdbd', 'Hot spot': '#d73027', 'Cold spot': '#4575b4' };
        serverDriven = { title: rt || result.styleBy, items: categories.map((label) => ({ label, color: colors[label] || '#3388ff' })) };
      } else {
        const numeric = values.filter((value) => typeof value === 'number' && Number.isFinite(value));
        if (numeric.length) {
          const min = Math.min(...numeric); const max = Math.max(...numeric);
          serverDriven = { title: rt || result.styleBy, items: [
            { color: ramp[0], label: `${min.toPrecision(4)}${result.metadata?.units ? ` ${result.metadata.units}` : ''}` },
            { color: ramp[3], label: `${(min + (max-min)/2).toPrecision(4)}` },
            { color: ramp[7], label: `${max.toPrecision(4)}${result.metadata?.units ? ` ${result.metadata.units}` : ''}` },
          ] };
        }
      }
    }
  } catch {
    // Outside provider (tests) — fall back to hardcoded below.
  }
  const key = (analysisType || '').toLowerCase();
  const legend = serverDriven || LEGENDS[key] || Object.values(LEGENDS).find(l =>
    key.includes(Object.keys(LEGENDS).find(k => key.includes(k)) || '')
  );

  useEffect(() => {
    if (!legend || !map) return;

    const el = L.control({ position: 'bottomright' });

    el.onAdd = () => {
      const div = L.DomUtil.create('div', 'info legend');
      div.style.background = 'rgba(255,255,255,0.95)';
      div.style.padding = '8px 10px';
      div.style.borderRadius = '6px';
      div.style.boxShadow = '0 1px 5px rgba(0,0,0,0.3)';
      div.style.fontSize = '11px';
      div.style.fontFamily = 'Arial, sans-serif';
      div.style.lineHeight = '1.7';
      div.style.maxHeight = '300px';
      div.style.overflowY = 'auto';

      const escape = (value) => String(value).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
      let html = `<strong style="font-size:12px;display:block;margin-bottom:4px">${escape(legend.title)}</strong>`;
      legend.items.forEach((item) => {
        html += `<div style="display:flex;align-items:center;gap:6px;margin-top:1px">
          <span style="width:18px;height:12px;background:${item.color};display:inline-block;border-radius:1px;flex-shrink:0;border:1px solid rgba(0,0,0,0.15)"></span>
          <span style="white-space:nowrap">${escape(item.label)}</span>
        </div>`;
      });
      div.innerHTML = html;
      return div;
    };

    el.addTo(map);

    return () => {
      try { map.removeControl(el); } catch (_) {}
    };
  }, [map, legend]);

  return null;
}
