export async function runProximityAnalysis(feature, targets, maxDistKm = 5) {
  const turf = await import('@turf/turf');
  const results = [];
  for (const target of targets) {
    const dist = turf.distance(turf.centroid(feature), turf.centroid(target), { units: 'kilometers' });
    results.push({ name: target.properties?.name || 'Unnamed', distanceKm: dist.toFixed(2) });
  }
  return {
    type: 'Proximity', label: 'Proximity Analysis',
    stats: results.reduce((a, r) => ({ ...a, [r.name]: r.distanceKm + ' km' }), {}),
    interpretation: `Measured distances to ${results.length} target locations.`,
  };
}
