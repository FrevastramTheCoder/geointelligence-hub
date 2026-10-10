import { useState } from 'react';
import {
  List, ListItem, ListItemButton, ListItemText, ListItemIcon,
  IconButton, TextField, Box, Typography, Dialog, DialogTitle,
  DialogContent, DialogActions, Button,
} from '@mui/material';
import { Bookmark, Delete, Edit, Download } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';
import { generateId } from '../../utils/fileUtils';

export function AOIPanel() {
  const { state, dispatch } = useApp();
  const { aois } = state;
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editName, setEditName] = useState('');
  const [editId, setEditId] = useState(null);

  const saveAOI = () => {
    const layer = state.layers.find(l => l.type === 'geojson');
    if (!layer) return;
    dispatch({
      type: 'ADD_AOI',
      payload: { id: generateId(), name: `AOI ${aois.length + 1}`, data: layer.data, createdAt: Date.now() },
    });
  };

  const openRename = (aoi) => { setEditId(aoi.id); setEditName(aoi.name); setDialogOpen(true); };
  const handleRename = () => {
    if (editId && editName.trim()) {
      dispatch({ type: 'RENAME_AOI', payload: { id: editId, name: editName.trim() } });
    }
    setDialogOpen(false);
  };

  const exportAOI = (aoi) => {
    const blob = new Blob([JSON.stringify(aoi.data, null, 2)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `${aoi.name}.geojson`; a.click();
  };

  return (
    <Box>
      <Button fullWidth variant="outlined" size="small" onClick={saveAOI} sx={{ mb: 1 }}>
        Save Current AOI
      </Button>
      {!aois.length ? (
        <Typography variant="body2" color="text.secondary" textAlign="center">
          No saved AOIs. Draw on the map and click Save.
        </Typography>
      ) : (
        <List dense>
          {aois.map((aoi) => (
            <ListItem key={aoi.id} disablePadding
              secondaryAction={
                <Box>
                  <IconButton size="small" onClick={() => exportAOI(aoi)}><Download fontSize="small" /></IconButton>
                  <IconButton size="small" onClick={() => openRename(aoi)}><Edit fontSize="small" /></IconButton>
                  <IconButton size="small" onClick={() => dispatch({ type: 'REMOVE_AOI', payload: aoi.id })}><Delete fontSize="small" /></IconButton>
                </Box>
              }
            >
              <ListItemButton>
                <ListItemIcon sx={{ minWidth: 30 }}><Bookmark fontSize="small" /></ListItemIcon>
                <ListItemText primary={aoi.name} secondary={new Date(aoi.createdAt).toLocaleDateString()}
                  primaryTypographyProps={{ fontSize: 13 }} secondaryTypographyProps={{ fontSize: 10 }} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)}>
        <DialogTitle>Rename AOI</DialogTitle>
        <DialogContent>
          <TextField autoFocus fullWidth value={editName} onChange={e => setEditName(e.target.value)} label="Name" />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleRename} variant="contained">Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
