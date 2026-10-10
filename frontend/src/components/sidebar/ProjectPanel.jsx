import { useEffect, useState } from 'react';
import {
  Box, Button, Chip, CircularProgress, Divider, List, ListItem,
  ListItemButton, ListItemText, TextField, Typography,
} from '@mui/material';
import { Delete, FolderOpen, Save } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';
import { createProject, deleteProject, getProject, listProjects } from '../../services/projectService';

export function ProjectPanel() {
  const { state, dispatch } = useApp();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);
  const [openingId, setOpeningId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState('');

  const refresh = async () => {
    try {
      const data = await listProjects();
      dispatch({ type: 'SET_PROJECTS', payload: data.projects || [] });
      return data.projects || [];
    } catch (e) {
      setError(e.message);
      return [];
    }
  };

  useEffect(() => {
    if (state.auth.loggedIn) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.auth.loggedIn]);

  const handleCreate = async () => {
    if (!name.trim() || loading) return;
    setLoading(true); setError('');
    try {
      const project = await createProject(name.trim(), description.trim());
      // Re-fetch to avoid stale-closure loss on rapid creates.
      const projects = await refresh();
      const created = projects.find(p => p.id === project.id) || project;
      // Fetch full detail once so results[] exists for the new project.
      try {
        const full = await getProject(created.id);
        dispatch({ type: 'SET_ACTIVE_PROJECT', payload: full });
      } catch {
        dispatch({ type: 'SET_ACTIVE_PROJECT', payload: created });
      }
      setName(''); setDescription('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const openProject = async (project) => {
    // Guard: your logs showed 5x GET /api/projects/:id in 1s (double-clicks).
    if (loading || openingId) return;
    // Clicking the already-open project is a no-op (no extra GET).
    if (state.activeProject?.id === project.id && state.activeProject?.results) return;
    setOpeningId(project.id); setError('');
    try {
      const full = await getProject(project.id);
      dispatch({ type: 'SET_ACTIVE_PROJECT', payload: full });
      const latest = full.results?.[0];
      if (latest) dispatch({ type: 'SET_RESULTS', payload: latest });
      else dispatch({ type: 'CLEAR_RESULTS' });
    } catch (e) {
      setError(e.message);
    } finally {
      setOpeningId(null);
    }
  };

  const handleDelete = async (project) => {
    if (deletingId) return;
    setDeletingId(project.id); setError('');
    try {
      await deleteProject(project.id);
      // Re-fetch instead of stale filtering.
      await refresh();
      if (state.activeProject?.id === project.id) {
        dispatch({ type: 'SET_ACTIVE_PROJECT', payload: null });
        dispatch({ type: 'CLEAR_RESULTS' });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Box sx={{ p: 1 }}>
      <TextField fullWidth size="small" label="Project name" value={name}
        onChange={e => setName(e.target.value)} sx={{ mb: 1 }} />
      <TextField fullWidth size="small" label="Description" value={description}
        onChange={e => setDescription(e.target.value)} sx={{ mb: 1 }} />
      <Button fullWidth size="small" variant="contained" startIcon={loading ? <CircularProgress size={14} /> : <Save />}
        onClick={handleCreate} disabled={loading || !name.trim()} sx={{ textTransform: 'none' }}>
        Create Project
      </Button>
      {error && <Typography color="error" variant="caption" sx={{ display: 'block', mt: 1 }}>{error}</Typography>}
      <Divider sx={{ my: 1 }} />
      {!state.projects.length ? (
        <Typography variant="body2" color="text.secondary" textAlign="center">No projects yet.</Typography>
      ) : (
        <List dense>
          {state.projects.map(project => {
            const isOpening = openingId === project.id;
            const isDeleting = deletingId === project.id;
            return (
            <ListItem key={project.id} disablePadding secondaryAction={
              <Button size="small" color="error" onClick={() => handleDelete(project)}
                disabled={Boolean(openingId || deletingId)} sx={{ minWidth: 0 }}>
                {isDeleting ? <CircularProgress size={14} /> : <Delete fontSize="small" />}
              </Button>
            }>
              <ListItemButton selected={state.activeProject?.id === project.id}
                onClick={() => openProject(project)} disabled={Boolean(openingId || deletingId)}>
                {isOpening ? <CircularProgress size={14} sx={{ mr: 1 }} /> : <FolderOpen fontSize="small" sx={{ mr: 1 }} />}
                <ListItemText primary={project.name} secondary={project.status} primaryTypographyProps={{ fontSize: 13 }} />
                {project.id === state.activeProject?.id && <Chip label="Open" size="small" color="primary" />}
              </ListItemButton>
            </ListItem>
            );
          })}
        </List>
      )}
    </Box>
  );
}
