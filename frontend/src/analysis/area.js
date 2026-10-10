export async function computeArea(feature) {
  const turf = await import('@turf/turf');
  const areaM2 = turf.area(feature);
  return {
    type: 'Area', label: 'Area Calculation',
    stats: {
      sqMeters: `${areaM2.toFixed(0)} m²`,
      hectares: `${(areaM2 / 10000).toFixed(2)} ha`,
      sqKm: `${(areaM2 / 1_000_000).toFixed(4)} km²`,
    },
    interpretation: `Total area: ${(areaM2/10000).toFixed(2)} hectares (${(areaM2/1_000_000).toFixed(3)} km²).`,
  };
}
