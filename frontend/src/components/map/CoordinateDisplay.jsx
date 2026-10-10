import { useMapEvents } from 'react-leaflet';
import { useState } from 'react';
import { Box, Typography } from '@mui/material';

export function CoordinateDisplay() {
  const [pos, setPos] = useState({ lat: 0, lng: 0, zoom: 0 });

  useMapEvents({
    mousemove(e) {
      setPos(prev => ({
        ...prev,
        lat: e.latlng.lat.toFixed(6),
        lng: e.latlng.lng.toFixed(6),
      }));
    },
    zoom(e) {
      setPos(prev => ({ ...prev, zoom: e.target.getZoom() }));
    },
  });

  return (
    <Box className="leaflet-bottom leaflet-left" sx={{ mb: 5 }}>
      <Box sx={{
        background: 'rgba(255,255,255,0.9)', px: 1, py: 0.5, borderRadius: 1,
        fontSize: 11, fontFamily: 'monospace', border: '1px solid #ccc',
      }}>
        <Typography variant="caption">
          Lat: {pos.lat} | Lng: {pos.lng} | Zoom: {pos.zoom}
        </Typography>
      </Box>
    </Box>
  );
}
