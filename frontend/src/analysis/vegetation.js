import { getSentinel2 } from '../services/imageryService';

export async function runVegetationAnalysis(geometry, startDate, endDate) {
  const ee = window.ee;
  const s2 = getSentinel2(geometry, startDate, endDate);
  const ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI');

  const thresholds = [
    { name: 'Dense Vegetation (NDVI > 0.6)', min: 0.6, max: 1.0 },
    { name: 'Moderate Vegetation (0.4–0.6)', min: 0.4, max: 0.6 },
    { name: 'Sparse Vegetation (0.2–0.4)', min: 0.2, max: 0.4 },
    { name: 'Bare / Built-up (< 0.2)', min: -1.0, max: 0.2 },
  ];

  const areaImg = ee.Image.pixelArea();
  const results = {};
  for (const t of thresholds) {
    const mask = ndvi.gte(t.min).and(ndvi.lt(t.max));
    const area = areaImg.updateMask(mask).reduceRegion({
      reducer: ee.Reducer.sum(), geometry, scale: 10, maxPixels: 1e9, bestEffort: true,
    });
    const val = await new Promise(r => area.evaluate(v => r(v)));
    const ha = (val?.area || 0) / 10000;
    results[t.name] = ha < 0.01 ? '<0.01 ha' : `${ha.toFixed(1)} ha`;
  }

  const url = ndvi.getThumbURL({
    min: -0.2, max: 0.8, palette: ['#d73027','#fc8d59','#fee08b','#91cf60','#1a9850'],
    region: geometry, dimensions: '800',
  });

  return {
    type: 'Vegetation', label: 'Vegetation Analysis',
    stats: results, imageUrl: url,
    interpretation: `Classified vegetation into 4 density categories based on NDVI thresholds.`,
    colorPalette: 'red-orange-yellow-green',
  };
}
