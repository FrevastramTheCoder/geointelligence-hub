import { getSentinel2 } from '../services/imageryService';

export async function computeNDBI(geometry, startDate, endDate) {
  const ee = window.ee;
  const s2 = getSentinel2(geometry, startDate, endDate);
  const ndbi = s2.normalizedDifference(['B11', 'B8']).rename('NDBI');

  const stats = ndbi.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry: geometry, scale: 10, maxPixels: 1e9, bestEffort: true,
  });

  const result = await new Promise((resolve) => stats.evaluate((val) => resolve(val)));
  const url = ndbi.getThumbURL({
    min: -0.3, max: 0.3, palette: ['#00FF00', '#FFFF00', '#FF0000'],
    region: geometry, dimensions: '800',
  });

  return {
    type: 'NDBI',
    label: 'NDBI - Built-up Index',
    stats: {
      mean: result?.NDBI_mean?.toFixed(4),
      min: result?.NDBI_min?.toFixed(4),
      max: result?.NDBI_max?.toFixed(4),
    },
    imageUrl: url,
    interpretation: parseFloat(result?.NDBI_mean || 0) > 0.1
      ? 'Significant built-up / urban area detected.'
      : 'Low built-up density, predominantly non-urban surface.',
    colorPalette: 'green-yellow-red',
  };
}
