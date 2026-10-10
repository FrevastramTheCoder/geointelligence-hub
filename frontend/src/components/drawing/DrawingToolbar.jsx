import { useEffect, useRef, useCallback, useState } from 'react';
import { useMap } from 'react-leaflet';
import { Paper, ToggleButtonGroup, ToggleButton, Tooltip, IconButton } from '@mui/material';
import {
  RectangleOutlined, PentagonOutlined, TimelineOutlined,
  LocationOnOutlined, DeleteOutlined,
} from '@mui/icons-material';
import { useApp } from '../../context/AppContext';
import { generateId } from '../../utils/fileUtils';
import L from 'leaflet';
import 'leaflet-draw';
import 'leaflet/dist/leaflet.css';
import 'leaflet-draw/dist/leaflet.draw.css';

// Fix Leaflet default marker icon
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

// Ensure L is available globally for leaflet-draw
window.L = L;

const COLORS = ['#1565c0', '#00897b', '#f44336', '#ff9800', '#9c27b0'];

const TOOLS = [
  { mode: 'polygon', icon: <PentagonOutlined />, label: 'Draw Polygon' },
  { mode: 'rectangle', icon: <RectangleOutlined />, label: 'Draw Rectangle' },
  { mode: 'marker', icon: <LocationOnOutlined />, label: 'Place Marker' },
  { mode: 'polyline', icon: <TimelineOutlined />, label: 'Draw Line' },
];

export function DrawingToolbar() {
  const map = useMap();
  const { dispatch, addLayer, removeLayer, state } = useApp();
  const [activeMode, setActiveMode] = useState(null);
  const colorIdx = useRef(0);
  const fgRef = useRef(null);

  const getColor = useCallback(() => COLORS[colorIdx.current++ % COLORS.length], []);

  useEffect(() => {
    if (!map || !L.Draw) return;

    fgRef.current = new L.FeatureGroup();
    map.addLayer(fgRef.current);

    const onCreated = (e) => {
      const layer = e.layer;
      const color = getColor();
      if (layer.setStyle) layer.setStyle({ color, fillColor: color, fillOpacity: 0.2, weight: 2 });
      fgRef.current?.addLayer(layer);
      const geom = layer.toGeoJSON();
      addLayer({
        id: generateId(),
        name: `AOI ${new Date().toLocaleTimeString()}`,
        type: 'geojson', data: geom,
        color, fillColor: color, visible: true, createdAt: Date.now(),
      });
      setActiveMode(null);
    };

    map.on(L.Draw.Event.CREATED, onCreated);

    return () => {
      map.off(L.Draw.Event.CREATED, onCreated);
      if (fgRef.current) map.removeLayer(fgRef.current);
    };
  }, [map, addLayer, getColor]);

  const activateDraw = (mode) => {
    if (!L.Draw) return;
    if (activeMode === mode) { setActiveMode(null); return; }
    setActiveMode(mode);

    const opts = {
      polygon: { shapeOptions: { color: getColor(), fillOpacity: 0.2, weight: 2 }, allowIntersection: false },
      rectangle: { shapeOptions: { color: getColor(), fillOpacity: 0.2, weight: 2 } },
      marker: {},
      polyline: { shapeOptions: { color: getColor(), weight: 3 } },
    };

    const className = mode === 'polyline' ? 'Polyline' : mode.charAt(0).toUpperCase() + mode.slice(1);
    const Klass = L.Draw[className];
    if (Klass) {
      const drawer = new Klass(map, opts[mode] || {});
      drawer.enable();
    }
  };

  const clearAll = () => {
    fgRef.current?.clearLayers();
    state.layers.filter(l => l.type === 'geojson').forEach(l => removeLayer(l.id));
  };

  return (
    <Paper sx={{
      position: 'absolute', top: 80, left: 10, zIndex: 1000,
      p: 0.5, bgcolor: 'white', borderRadius: 2, display: 'flex', flexDirection: 'column',
    }}>
      <ToggleButtonGroup orientation="vertical" value={activeMode} exclusive size="small">
        {TOOLS.map(t => (
          <ToggleButton key={t.mode} value={t.mode} onClick={() => activateDraw(t.mode)} sx={{ px: 1 }}>
            <Tooltip title={t.label} placement="right">{t.icon}</Tooltip>
          </ToggleButton>
        ))}
      </ToggleButtonGroup>
      <Tooltip title="Clear All" placement="right">
        <IconButton size="small" color="error" onClick={clearAll} sx={{ mt: 0.5 }}>
          <DeleteOutlined fontSize="small" />
        </IconButton>
      </Tooltip>
    </Paper>
  );
}
