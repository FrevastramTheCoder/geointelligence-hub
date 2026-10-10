export async function runChangeDetection(geometry, year1, year2) {
  const ee = window.ee;
  function getNdvi(year) {
    const s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
      .filterBounds(geometry).filterDate(`${year}-01-01`, `${year}-12-31`)
      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
      .map(img => img.divide(10000)).median().clip(geometry);
    return s2.normalizedDifference(['B8', 'B4']).rename('NDVI');
  }

  const ndvi1 = getNdvi(year1);
  const ndvi2 = getNdvi(year2);
  const diff = ndvi2.subtract(ndvi1).rename('change');

  const stats = diff.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry, scale: 10, maxPixels: 1e9, bestEffort: true,
  });

  const result = await new Promise(r => stats.evaluate(v => r(v)));
  const url = diff.getThumbURL({
    min: -0.5, max: 0.5, palette: ['#FF0000','#FFA500','#FFFF00','#FFFFFF','#90EE90','#006400'],
    region: geometry, dimensions: '800',
  });

  const meanC = parseFloat(result?.change_mean || 0);
  return {
    type: 'ChangeDetection', label: `Change Detection (${year1}–${year2})`,
    stats: { meanChange: meanC.toFixed(4), min: result?.change_min?.toFixed(4), max: result?.change_max?.toFixed(4) },
    imageUrl: url,
    interpretation: meanC < -0.1 ? 'Net vegetation loss (urban expansion or deforestation).' :
      meanC > 0.1 ? 'Net vegetation gain (greening or reforestation).' : 'Minimal change.',
    colorPalette: 'red-orange-yellow-green',
  };
}
