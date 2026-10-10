export async function runUrbanGrowth(geometry, year1, year2) {
  const ee = window.ee;
  function getNdbiforYear(year) {
    const s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
      .filterBounds(geometry).filterDate(`${year}-01-01`, `${year}-12-31`)
      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
      .map(img => img.divide(10000)).median().clip(geometry);
    return s2.normalizedDifference(['B11', 'B8']).rename('NDBI');
  }
  const n1 = getNdbiforYear(year1);
  const n2 = getNdbiforYear(year2);
  const growth = n2.subtract(n1);

  const stats = growth.reduceRegion({
    reducer: ee.Reducer.mean().combine(ee.Reducer.minMax(), '', true),
    geometry, scale: 10, maxPixels: 1e9, bestEffort: true,
  });
  const result = await new Promise(r => stats.evaluate(v => r(v)));
  const url = growth.getThumbURL({
    min: -0.2, max: 0.2, palette: ['blue','white','orange','red'],
    region: geometry, dimensions: '800',
  });

  const meanG = parseFloat(result?.NDBI_mean || 0);
  return {
    type: 'UrbanGrowth', label: `Urban Growth (${year1}–${year2})`,
    stats: { meanGrowth: meanG.toFixed(4) },
    imageUrl: url,
    interpretation: meanG > 0.05 ? 'Detected urban expansion in this period.' :
      meanG > 0 ? 'Slight urban growth.' : 'No significant urban growth.',
    colorPalette: 'blue-white-red',
  };
}
