import {
  List, ListItem, ListItemButton, ListItemIcon, ListItemText,
  IconButton, Typography, Box, Chip,
} from '@mui/material';
import { Visibility, VisibilityOff, Delete, Circle, CropFree } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';

export function LayerPanel() {
  const { state, toggleLayer, removeLayer, dispatch } = useApp();
  const { layers } = state;

  if (!layers.length) {
    return (
      <Box sx={{ p: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No layers yet. Draw on the map or upload a file.
        </Typography>
      </Box>
    );
  }

  return (
    <List dense>
      {layers.map((layer) => {
        const isAOI = state.aoiLayerId === layer.id;
        const geo = layer.type === 'geojson' && layer.data;
        return (
        <ListItem
          key={layer.id}
          secondaryAction={
            <IconButton edge="end" size="small" onClick={() => removeLayer(layer.id)}>
              <Delete fontSize="small" />
            </IconButton>
          }
          disablePadding
        >
          <ListItemButton selected={state.activeLayer === layer.id}
            onClick={() => dispatch({ type: 'SET_ACTIVE_LAYER', payload: layer.id })}>
            <ListItemIcon sx={{ minWidth: 30 }}>
              <Circle sx={{ color: layer.color || '#3388ff', fontSize: 12 }} />
            </ListItemIcon>
            <ListItemText
              primary={layer.name}
              primaryTypographyProps={{ fontSize: 13, noWrap: true }}
              secondary={`${layer.type?.toUpperCase()}${layer.featureCount ? ` • ${layer.featureCount} feat` : ''}`}
              secondaryTypographyProps={{ fontSize: 10 }}
            />
            {isAOI && <Chip label="AOI" size="small" color="primary" sx={{ mr: 0.5, height: 18, fontSize: 10 }} />}
            {geo && !isAOI && (
              <IconButton size="small" title="Use as analysis boundary (AOI)"
                onClick={(e) => { e.stopPropagation(); dispatch({ type: 'SET_ACTIVE_AOI', payload: layer.id }); }}>
                <CropFree fontSize="small" />
              </IconButton>
            )}
            <IconButton size="small" onClick={(e) => { e.stopPropagation(); toggleLayer(layer.id); }}>
              {layer.visible !== false ? <Visibility fontSize="small" /> : <VisibilityOff fontSize="small" />}
            </IconButton>
          </ListItemButton>
        </ListItem>
        );
      })}
    </List>
  );
}
