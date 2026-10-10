import { useState } from 'react';
import {
  Box, Button, FormControl, InputLabel, Select, MenuItem,
  TextField, Typography, CircularProgress, Divider, Chip, Slider,
} from '@mui/material';
import { PlayArrow } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';
import { useAnalysis } from '../../hooks/useAnalysis';
import { getProject, listProjects } from '../../services/projectService';
import { getCurrentAOI } from '../../services/boundaryService';

const ANALYSES = [
  { id: 'ndvi', label: 'NDVI - Vegetation Index', cat: 'Spectral', hasYear: true, hasSource: true },
  { id: 'ndwi', label: 'NDWI - Water Index', cat: 'Spectral', hasYear: true, hasSource: true },
  { id: 'ndbi', label: 'NDBI - Built-up Index', cat: 'Spectral', hasYear: true, hasSource: true },
  { id: 'elevation', label: 'Elevation (SRTM)', cat: 'Terrain', hasYear: false, hasSource: false },
  { id: 'slope', label: 'Slope Analysis', cat: 'Terrain', hasYear: false, hasSource: false },
  { id: 'landcover', label: 'Land Cover (RF Classified)', cat: 'Classification', hasYear: true, hasSource: true },
  { id: 'dynamicworld', label: 'Dynamic World (9-class, 10m)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'worldcover_v200', label: 'ESA WorldCover (11-class, 10m)', cat: 'Land Cover Datasets', hasYear: false, hasSource: false },
  { id: 'modis_lc', label: 'MODIS MCD12Q1 (17-class, 500m)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'modis_cmg', label: 'MODIS MCD12C1 CMG (17-class)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'copernicus_lc', label: 'Copernicus GLCS (100m)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'glc_fcs30', label: 'GLC_FCS30D (35-class, 30m)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'nlcd', label: 'NLCD (USA, 30m)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'corine', label: 'CORINE Land Cover (EU, 100m)', cat: 'Land Cover Datasets', hasYear: true, hasSource: false },
  { id: 'vegetation', label: 'Vegetation Classification', cat: 'Vegetation', hasYear: true, hasSource: true },
  { id: 'change', label: 'Change Detection', cat: 'Change', hasYear: true, hasSource: true },
  { id: 'flood', label: 'Flood Risk Simulation', cat: 'Change', hasYear: true, hasSource: false },
];

const VEG_CLASSES = [
  { value: 3, label: '3 (Rangeland, Shrubs/Crops, Forest)' },
  { value: 4, label: '4 (Rangeland, Shrubs, Cropland, Forest)' },
  { value: 5, label: '5 (Bare, Rangeland, Shrubs, Cropland, Forest)' },
  { value: 6, label: '6 (Bare, Range, Shrubs, Mixed Veg, Crops, Forest)' },
];

const CATS = [...new Set(ANALYSES.map(a => a.cat))];

const SOURCES = [
  { id: 'sentinel2', label: 'Sentinel-2 (10m)' },
  { id: 'landsat8', label: 'Landsat 8 (30m)' },
  { id: 'landsat9', label: 'Landsat 9 (30m)' },
];

export function AnalysisPanel() {
  const { state, dispatch } = useApp();
  const { run, running, progress } = useAnalysis();
  const [selected, setSelected] = useState('');
  const [cat, setCat] = useState('Spectral');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  // Year & source controls
  const [year, setYear] = useState(2024);
  const [year2, setYear2] = useState(2020);
  const [source, setSource] = useState('sentinel2');
  const [maxCloud, setMaxCloud] = useState(30);
  const [numClasses, setNumClasses] = useState(4);

  const filtered = ANALYSES.filter(a => a.cat === cat);
  const current = ANALYSES.find(a => a.id === selected);
  const aoi = getCurrentAOI(state);
  const hasAOI = !!aoi?.geometry;

  const activeProject = state.activeProject;

  const handleRun = async () => {
    if (!selected || !hasAOI || running) return;
    setError(null);
    setResult(null);
    try {
      const geometry = aoi.geometry;
      if (!geometry) throw new Error('Draw a polygon on the map first.');

      // Real EE analysis — backend runs on YOUR GEE account and persists
      // job + result under the project. Pass the active project id so the
      // result is linked (backend falls back to Default Project if omitted).
      const res = await run(selected, geometry, {
        year, year2, source, maxCloud, numClasses,
        projectId: activeProject?.id,
      });
      // Attach project context for display; backend already returns projectId/jobId/resultId.
      const withProject = { ...res, projectId: res.projectId || activeProject?.id || null };
      setResult(withProject);

      // Refresh project detail so Projects tab shows the new result without
      // the user spamming GET /api/projects/:id (see server logs).
      const pid = withProject.projectId;
      if (pid) {
        try {
          const full = await getProject(pid);
          dispatch({ type: 'SET_ACTIVE_PROJECT', payload: full });
        } catch {
          // Non-fatal: result is already on screen + map.
        }
        try {
          const all = await listProjects();
          if (all.projects) dispatch({ type: 'SET_PROJECTS', payload: all.projects });
        } catch {
          // ignore
        }
      }
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <Box sx={{ p: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
        <Typography variant="caption" color="text.secondary">Project:</Typography>
        {activeProject ? (
          <Chip label={activeProject.name} size="small" color="primary" />
        ) : (
          <Chip label="None — will use Default Project" size="small" variant="outlined" />
        )}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
        <Typography variant="caption" color="text.secondary">AOI:</Typography>
        {aoi ? (
          <Chip label={aoi.label} size="small" color="secondary" />
        ) : (
          <Chip label="None — draw or upload a boundary" size="small" variant="outlined" />
        )}
      </Box>
      {!hasAOI && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Draw a polygon, rectangle, or place a marker on the map first.
        </Typography>
      )}
      {!state.auth.geeConnected && (
        <Typography variant="body2" color="error" sx={{ mb: 1 }}>
          Google Earth Engine is not connected. Connect your Google account to continue.
          Analysis runs real EE on your account — no mock.
        </Typography>
      )}

      {/* Category */}
      <FormControl fullWidth size="small" sx={{ mb: 1 }}>
        <InputLabel>Category</InputLabel>
        <Select value={cat} label="Category" onChange={e => { setCat(e.target.value); setSelected(''); }}>
          {CATS.map(c => <MenuItem key={c} value={c}>{c}</MenuItem>)}
        </Select>
      </FormControl>

      {/* Analysis */}
      <FormControl fullWidth size="small" sx={{ mb: 1 }}>
        <InputLabel>Analysis</InputLabel>
        <Select value={selected} label="Analysis" onChange={e => setSelected(e.target.value)}>
          {filtered.map(a => <MenuItem key={a.id} value={a.id}>{a.label}</MenuItem>)}
        </Select>
      </FormControl>

      {/* Year selector (for analyses that support it) */}
      {current?.hasYear && (
        <TextField
          fullWidth size="small" label="Year"
          type="number" value={year}
          onChange={e => setYear(Number(e.target.value))}
          sx={{ mb: 1 }}
          inputProps={{ min: 2015, max: 2025 }}
        />
      )}

      {/* Year 2 (for change detection) */}
      {selected === 'change' && (
        <TextField
          fullWidth size="small" label="Compare with Year"
          type="number" value={year2}
          onChange={e => setYear2(Number(e.target.value))}
          sx={{ mb: 1 }}
          inputProps={{ min: 2015, max: 2025 }}
        />
      )}

      {/* Source selector */}
      {current?.hasSource && (
        <FormControl fullWidth size="small" sx={{ mb: 1 }}>
          <InputLabel>Source</InputLabel>
          <Select value={source} label="Source" onChange={e => setSource(e.target.value)}>
            {SOURCES.map(s => <MenuItem key={s.id} value={s.id}>{s.label}</MenuItem>)}
          </Select>
        </FormControl>
      )}

      {/* Number of Classes selector (vegetation only) */}
      {selected === 'vegetation' && (
        <FormControl fullWidth size="small" sx={{ mb: 1 }}>
          <InputLabel>Classes</InputLabel>
          <Select value={numClasses} label="Classes" onChange={e => setNumClasses(Number(e.target.value))}>
            {VEG_CLASSES.map(v => <MenuItem key={v.value} value={v.value}>{v.label}</MenuItem>)}
          </Select>
        </FormControl>
      )}

      {/* Cloud cover slider */}
      {current?.hasSource && (
        <Box sx={{ mb: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Max Cloud Cover: {maxCloud}%
          </Typography>
          <Slider
            size="small" value={maxCloud} min={5} max={100}
            onChange={(_, v) => setMaxCloud(v)}
          />
        </Box>
      )}

      <Button
        fullWidth variant="contained"
        startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrow />}
        onClick={handleRun}
        disabled={!selected || !hasAOI || running || !state.auth.geeConnected}
        sx={{ mb: 1 }}
      >
        {running ? progress || 'Processing...' : 'Run Analysis'}
      </Button>

      {error && (
        <Typography variant="body2" color="error" sx={{ mt: 1, wordBreak: 'break-word' }}>
          {error}
        </Typography>
      )}

      {result && (
        <Box sx={{ mt: 1 }}>
          <Divider sx={{ mb: 1 }} />
          <Typography variant="subtitle2" gutterBottom>{result.label}</Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
            Real EE analysis
            {result.projectId ? ` • saved to project ${result.projectId.slice(0, 8)}…` : ''}
            {result.jobId ? ` • job ${String(result.jobId).slice(0, 8)}…` : ''}
          </Typography>
          {result.stats && Object.entries(result.stats).map(([k, v]) => (
            <Chip key={k} label={`${k}: ${v}`} size="small" sx={{ mr: 0.5, mb: 0.5 }} />
          ))}
          {result.interpretation && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              {result.interpretation}
            </Typography>
          )}
        </Box>
      )}
    </Box>
  );
}
