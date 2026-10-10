export function statsToChartData(stats, chartData) {
  // Server time-series pass chartData through untouched (yearly values + trend)
  if (Array.isArray(chartData) && chartData.length) {
    return chartData
      .filter((d) => d && d.value !== null && d.value !== undefined)
      .map((d) => ({ name: String(d.year ?? d.name), value: Number(d.value) || 0, display: d.value }));
  }
  if (!stats) return [];
  return Object.entries(stats)
    .filter(([k]) => k !== 'accuracy' && k !== 'kappa')
    .map(([name, value]) => ({
      name,
      value: parseFloat(value) || 0,
      display: value,
    }));
}

export function getAnalysisPalette(type) {
  const palettes = {
    NDVI: ['#d73027', '#fc8d59', '#fee08b', '#91cf60', '#1a9850'],
    NDWI: ['#8B4513', '#FFD700', '#00BFFF', '#0000CD'],
    NDBI: ['#00FF00', '#FFFF00', '#FF0000'],
    default: ['#1565c0', '#00897b', '#f44336', '#ff9800', '#9c27b0'],
  };
  return palettes[type] || palettes.default;
}
