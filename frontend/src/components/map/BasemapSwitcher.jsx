import { ToggleButtonGroup, ToggleButton } from '@mui/material';
import { Map as MapIcon, Satellite, Terrain } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';

export function BasemapSwitcher() {
  const { state, dispatch } = useApp();

  return (
    <ToggleButtonGroup
      value={state.basemap}
      exclusive
      size="small"
      onChange={(_, val) => val && dispatch({ type: 'SET_BASEMAP', payload: val })}
      sx={{ position: 'absolute', top: 80, right: 10, zIndex: 1000, bgcolor: 'white' }}
    >
      <ToggleButton value="osm"><MapIcon fontSize="small" /></ToggleButton>
      <ToggleButton value="satellite"><Satellite fontSize="small" /></ToggleButton>
      <ToggleButton value="terrain"><Terrain fontSize="small" /></ToggleButton>
    </ToggleButtonGroup>
  );
}
