import { getSentinel2 } from '../services/imageryService';

export async function computeNDVI(geometry, startDate, endDate) {
  const ee = window.ee;
  const s2 = getSentinel2(geometry, startDate, endDate);
  const ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI');

  const stats = ndvi.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry: geometry, scale: 10, maxPixels: 1e9, bestEffort: true,
  });

  const result = await new Promise((resolve) => stats.evaluate((val) => resolve(val)));
  const url = ndvi.getThumbURL({
    min: -0.2, max: 0.8,
    palette: ['red', 'yellow', 'green'],
    region: geometry, dimensions: '800',
  });

  return {
    type: 'NDVI',
    label: 'NDVI - Vegetation Index',
    stats: {
      mean: result?.NDVI_mean?.toFixed(4),
      min: result?.NDVI_min?.toFixed(4),
      max: result?.NDVI_max?.toFixed(4),
    },
    imageUrl: url,
    interpretation: interpretNDVI(parseFloat(result?.NDVI_mean || 0)),
    colorPalette: 'red-yellow-green',
  };
}

function interpretNDVI(mean) {
  if (mean > 0.6) return 'Dense healthy vegetation cover, likely forest or well-irrigated areas.';
  if (mean > 0.4) return 'Moderate vegetation, typical of mixed urban-green spaces or grassland.';
  if (mean > 0.2) return 'Sparse vegetation, shrubs or stressed vegetation.';
  if (mean > 0) return 'Very sparse vegetation or bare soil with minimal green cover.';
  return 'Non-vegetated surface (water, built-up, or bare ground).';
}
