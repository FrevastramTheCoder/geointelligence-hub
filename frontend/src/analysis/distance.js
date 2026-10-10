export async function computeDistance(fromFeature, toFeature) {
  const turf = await import('@turf/turf');
  const fromCentroid = turf.centroid(fromFeature);
  const toCentroid = turf.centroid(toFeature);
  const distKm = turf.distance(fromCentroid, toCentroid, { units: 'kilometers' });
  return {
    type: 'Distance', label: 'Distance Calculation',
    stats: { kilometers: `${distKm.toFixed(3)} km`, metres: `${(distKm*1000).toFixed(0)} m` },
    interpretation: `Straight-line distance between centroids: ${distKm.toFixed(2)} km.`,
  };
}
