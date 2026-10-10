import { MapContainer as LeafletMap, TileLayer, ScaleControl, ZoomControl } from 'react-leaflet';
import { useApp } from '../../context/AppContext';
import { DrawingToolbar } from '../drawing/DrawingToolbar';
import { CoordinateDisplay } from './CoordinateDisplay';
import { LayerRenderer } from './LayerRenderer';
import { AutoZoom } from './AutoZoom';
import { MapLegend } from './MapLegend';
import { useCallback } from 'react';

const BASEMAPS = {
  osm: { url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', attr: 'OSM', name: 'OpenStreetMap' },
  satellite: { url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr: 'Esri', name: 'Satellite' },
  terrain: { url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', attr: 'OpenTopoMap', name: 'Terrain' },
};

export function MapView() {
  const { state, dispatch } = useApp();
  const { basemap, coordinates, layers } = state;
  const bm = BASEMAPS[basemap] || BASEMAPS.osm;

  const handleMoveEnd = useCallback((e) => {
    const map = e.target;
    const center = map.getCenter();
    dispatch({
      type: 'SET_COORDINATES',
      payload: { lat: center.lat, lng: center.lng, zoom: map.getZoom() },
    });
  }, [dispatch]);

  return (
    <div className="map-wrapper">
      <LeafletMap
        center={[coordinates.lat, coordinates.lng]}
        zoom={coordinates.zoom}
        zoomControl={false}
        style={{ height: '100%', width: '100%' }}
        onMoveEnd={handleMoveEnd}
      >
        <TileLayer url={bm.url} attribution={`&copy; ${bm.attr}`} />
        <ZoomControl position="topright" />
        <ScaleControl position="bottomleft" imperial={false} />
        <CoordinateDisplay />
        <DrawingToolbar />
        <LayerRenderer layers={layers} />
        <AutoZoom layers={layers} />
        <MapLegend analysisType={state.results?.type} />
      </LeafletMap>
    </div>
  );
}
