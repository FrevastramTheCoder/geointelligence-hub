/**
 * Polygon intersection for two uploaded GeoJSON layers.
 * Runs locally with Turf; coordinates must be WGS84 longitude/latitude (EPSG:4326).
 */
export async function runIntersectionAnalysis(sourceFeatures, targetFeatures, options = {}) {
  const turf = await import('@turf/turf');
  const asFeatures = (value) => {
    if (Array.isArray(value)) return value;
    if (value?.type === 'FeatureCollection') return value.features || [];
    if (value?.type === 'Feature') return [value];
    if (value?.type && value.coordinates) return [{ type: 'Feature', properties: {}, geometry: value }];
    return [];
  };
  const polygons = (features) => asFeatures(features).filter((feature) =>
    feature?.type === 'Feature' && ['Polygon', 'MultiPolygon'].includes(feature.geometry?.type)
      && Array.isArray(feature.geometry.coordinates));
  const left = polygons(sourceFeatures);
  const right = polygons(targetFeatures);
  if (!left.length || !right.length) {
    throw new Error('Intersection needs at least one valid Polygon or MultiPolygon in each input layer.');
  }
  const pairCount = left.length * right.length;
  if (pairCount > 2500) {
    throw new Error(`Intersection would compare ${pairCount.toLocaleString()} feature pairs. Filter the layers to 2,500 pairs or fewer first.`);
  }

  const output = [];
  let areaM2 = 0;
  for (let i = 0; i < left.length; i += 1) {
    for (let j = 0; j < right.length; j += 1) {
      let overlap;
      try {
        overlap = turf.intersect(turf.featureCollection([left[i], right[j]]));
      } catch (error) {
        throw new Error(`Could not intersect feature pair ${i + 1}/${j + 1}: ${error.message}`);
      }
      if (!overlap) continue;
      const area = turf.area(overlap);
      if (!Number.isFinite(area) || area <= 0) continue;
      areaM2 += area;
      const propsA = left[i].properties || {};
      const propsB = right[j].properties || {};
      const properties = {
        source_feature: left[i].id ?? i,
        target_feature: right[j].id ?? j,
        overlap_area_m2: Number(area.toFixed(2)),
      };
      Object.entries(propsA).forEach(([key, value]) => { properties[`source_${key}`] = value; });
      Object.entries(propsB).forEach(([key, value]) => { properties[`target_${key}`] = value; });
      output.push({ ...overlap, properties });
    }
  }

  const featureCollection = turf.featureCollection(output);
  const hectares = areaM2 / 10000;
  const stats = {
    'Source polygons': left.length,
    'Target polygons': right.length,
    'Feature pairs checked': pairCount,
    'Intersecting pairs': output.length,
    'Total overlap area': `${hectares.toFixed(4)} ha`,
    'Total overlap area (m²)': `${areaM2.toFixed(2)} m²`,
  };
  const noOverlap = output.length === 0;
  return {
    type: 'Intersection',
    label: options.label || 'Polygon Intersection',
    geometry: featureCollection,
    stats,
    interpretation: noOverlap
      ? 'No polygon overlap was found between these layers.'
      : `Found ${output.length} intersecting polygon pair${output.length === 1 ? '' : 's'} with a combined overlap area of ${hectares.toFixed(4)} ha. Area is geodesic and assumes input coordinates are WGS84 longitude/latitude.`,
    metadata: { operation: 'polygon_intersection', crs: 'EPSG:4326', sourceLayer: options.sourceLayer || null, targetLayer: options.targetLayer || null },
  };
}
