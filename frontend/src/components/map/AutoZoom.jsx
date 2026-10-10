import { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import { useApp } from '../../context/AppContext';
import L from 'leaflet';

export function AutoZoom({ layers }) {
  const map = useMap();
  const prevCount = useRef(0);

  useEffect(() => {
    const geojsonLayers = layers.filter(l => l.type === 'geojson' && l.data && l.visible !== false);
    const currentCount = geojsonLayers.length;

    if (currentCount > prevCount.current && geojsonLayers.length > 0) {
      // Zoom to the newest GeoJSON layer
      const newest = geojsonLayers[geojsonLayers.length - 1];
      try {
        const gj = L.geoJSON(newest.data);
        const bounds = gj.getBounds();
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [50, 50], maxZoom: 18 });
        }
      } catch (e) {
        console.warn('AutoZoom failed:', e);
      }
    }
    prevCount.current = currentCount;
  }, [layers, map]);

  return null;
}
