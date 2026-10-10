export async function runBufferAnalysis(feature, radiusMeters) {
  const turf = await import('@turf/turf');
  const buffered = turf.buffer(feature, radiusMeters / 1000, { units: 'kilometers' });
  const area = turf.area(buffered);
  return {
    type: 'BufferAnalysis',
    label: `Buffer (${radiusMeters}m)`,
    stats: { radius: `${radiusMeters} m`, bufferArea: `${(area / 10000).toFixed(2)} ha` },
    geometry: buffered,
    interpretation: `Circular buffer of ${radiusMeters}m applied. Buffer area: ${(area/10000).toFixed(1)} hectares.`,
  };
}
