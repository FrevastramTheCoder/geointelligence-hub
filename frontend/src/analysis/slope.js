import { getSRTM } from '../services/imageryService';

export async function computeSlope(geometry) {
  const ee = window.ee;
  const srtm = getSRTM(geometry);
  const slope = ee.Terrain.slope(srtm).rename('Slope');

  const stats = slope.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry: geometry, scale: 30, maxPixels: 1e9, bestEffort: true,
  });

  const result = await new Promise((resolve) => stats.evaluate((val) => resolve(val)));
  const url = slope.getThumbURL({
    min: 0, max: 45, palette: ['green', 'yellow', 'orange', 'red'],
    region: geometry, dimensions: '800',
  });

  const meanSlope = parseFloat(result?.Slope_mean || 0);
  return {
    type: 'Slope',
    label: 'Slope Analysis (degrees)',
    stats: {
      mean: meanSlope.toFixed(2) + '°',
      min: result?.Slope_min?.toFixed(2) + '°',
      max: result?.Slope_max?.toFixed(2) + '°',
    },
    imageUrl: url,
    interpretation: meanSlope > 15 ? 'Steep terrain. Development and construction may require terracing.' :
      meanSlope > 5 ? 'Moderate slope. Suitable for most development with minor grading.' :
      'Flat to gently sloping terrain. Highly suitable for development.',
    colorPalette: 'green-yellow-red',
  };
}
