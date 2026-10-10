import { getSRTM } from '../services/imageryService';

export async function computeElevation(geometry) {
  const ee = window.ee;
  const srtm = getSRTM(geometry);
  const elev = srtm.rename('Elevation');

  const stats = elev.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry: geometry, scale: 30, maxPixels: 1e9, bestEffort: true,
  });

  const result = await new Promise((resolve) => stats.evaluate((val) => resolve(val)));
  const url = elev.getThumbURL({
    min: 0, max: 300, palette: ['#006400', '#32CD32', '#FFD700', '#8B4513', '#FFFFFF'],
    region: geometry, dimensions: '800',
  });

  return {
    type: 'Elevation',
    label: 'Elevation (metres)',
    stats: {
      mean: result?.Elevation_mean?.toFixed(1) + ' m',
      min: result?.Elevation_min?.toFixed(1) + ' m',
      max: result?.Elevation_max?.toFixed(1) + ' m',
    },
    imageUrl: url,
    interpretation: `Elevation range: ${result?.Elevation_min?.toFixed(0)} – ${result?.Elevation_max?.toFixed(0)} m`,
    colorPalette: 'green-yellow-brown-white',
  };
}
