import { getSentinel2 } from '../services/imageryService';

export async function computeNDWI(geometry, startDate, endDate) {
  const ee = window.ee;
  const s2 = getSentinel2(geometry, startDate, endDate);
  const ndwi = s2.normalizedDifference(['B3', 'B8']).rename('NDWI');

  const stats = ndwi.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry: geometry, scale: 10, maxPixels: 1e9, bestEffort: true,
  });

  const result = await new Promise((resolve) => stats.evaluate((val) => resolve(val)));
  const url = ndwi.getThumbURL({
    min: -1, max: 1, palette: ['#8B4513', '#FFD700', '#00BFFF', '#0000CD'],
    region: geometry, dimensions: '800',
  });

  return {
    type: 'NDWI',
    label: 'NDWI - Water Index',
    stats: {
      mean: result?.NDWI_mean?.toFixed(4),
      min: result?.NDWI_min?.toFixed(4),
      max: result?.NDWI_max?.toFixed(4),
    },
    imageUrl: url,
    interpretation: parseFloat(result?.NDWI_mean || 0) > 0
      ? 'Water bodies or high moisture content detected.'
      : 'Dry surface, limited water presence.',
    colorPalette: 'brown-gold-blue',
  };
}
