import { useCallback, useState } from 'react';
import { Box, Typography, TextField, Button, Alert, CircularProgress, Chip } from '@mui/material';
import { CloudUpload, Search } from '@mui/icons-material';
import { useDropzone } from 'react-dropzone';
import { useApp } from '../../context/AppContext';
import { generateId } from '../../utils/fileUtils';
import { parseBoundaryFile, validateBoundary } from '../../services/boundaryService';
import { API, TOKEN_KEY } from '../../config/api';

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${localStorage.getItem(TOKEN_KEY) || ''}`,
  };
}

export function UploadPanel() {
  const { state, dispatch, addLayer } = useApp();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [adminName, setAdminName] = useState('');
  const [adminLevel, setAdminLevel] = useState(2);

  const addBoundaryLayer = useCallback((name, features, meta, source) => {
    const layer = {
      id: generateId(),
      name,
      type: 'geojson',
      data: features.length === 1 ? features[0] : { type: 'FeatureCollection', features },
      color: '#ff9800', fillColor: '#ff9800', visible: true, createdAt: Date.now(),
      boundary: true, source, crs: meta?.crs || 4326,
      featureCount: features.length,
      fields: [...new Set(features.flatMap((f) => Object.keys(f.properties || {})))].slice(0, 20),
    };
    addLayer(layer);
    // Uploaded boundary becomes the AOI automatically (priority rule).
    dispatch({ type: 'SET_ACTIVE_AOI', payload: layer.id });
    return layer;
  }, [addLayer, dispatch]);

  const onDrop = useCallback(async (acceptedFiles) => {
    setError('');
    setInfo(null);
    for (const file of acceptedFiles) {
      setBusy(true);
      try {
        if (/\.json$/i.test(file.name)) {
          const raw = JSON.parse(await file.text());
          const isGrid = raw && Array.isArray(raw.values) && raw.crs && raw.transform;
          const isCloud = raw && raw.pointCloud?.type === 'FeatureCollection' && raw.crs && raw.units;
          const isOrtho = raw && raw.bands?.red && raw.bands?.nir && raw.bands.red.values && (raw.crs || raw.bands.red.crs);
          if (isGrid || isCloud || isOrtho) {
            const name = file.name.replace(/\.json$/i, '');
            const type = isGrid ? 'drone-grid' : isCloud ? 'drone-pointcloud' : 'drone-orthomosaic';
            const size = isGrid ? raw.values.reduce((sum, row) => sum + (Array.isArray(row) ? row.length : 0), 0)
              : isCloud ? raw.pointCloud.features?.length || 0 : raw.bands.red.values.reduce((sum, row) => sum + (Array.isArray(row) ? row.length : 0), 0);
            addLayer({ id: generateId(), name, type, data: raw, visible: false, createdAt: Date.now(), featureCount: size,
              crs: raw.crs || raw.bands.red.crs, units: raw.verticalUnits || raw.units || 'm' });
            const sourceCrs = raw.crs || raw.bands.red.crs;
            setInfo({ name, count: size, crs: `${sourceCrs} • ${type.replace('drone-', '')}`, areaHa: null, warnings: [], layerId: null });
            continue;
          }
        }
        const { features, meta } = await parseBoundaryFile(file);
        const check = await validateBoundary(features);
        const base = file.name.replace(/\.(geojson|json|kml|kmz|zip)$/i, '');
        const layer = addBoundaryLayer(base, features, meta, 'upload');
        setInfo({
          name: base,
          count: features.length,
          crs: meta.crsNote,
          areaHa: check.info.areaHa,
          warnings: check.warnings,
          layerId: layer.id,
        });
        if (!check.valid) setError('Invalid geometry in file.');
      } catch (e) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    }
  }, [addBoundaryLayer]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/geo+json': ['.geojson', '.json'],
      'application/json': ['.json'],
      'application/vnd.google-earth.kml+xml': ['.kml'],
      'application/vnd.google-earth.kmz': ['.kmz'],
      'application/zip': ['.zip'],
    },
  });

  const fetchAdminBoundary = async () => {
    if (!adminName.trim()) return;
    setError('');
    setInfo(null);
    setBusy(true);
    try {
      const res = await fetch(API.ADMIN_BOUNDARY, {
        method: 'POST', headers: authHeaders(),
        body: JSON.stringify({ name: adminName.trim(), level: adminLevel }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) throw new Error(data.error || 'Lookup failed');
      const feats = data.featureCollection?.features || [];
      const layer = addBoundaryLayer(
        data.label || adminName.trim(), feats,
        { crs: 4326, crsNote: `WGS84 — ${data.dataset}` }, 'admin');
      setInfo({
        name: data.label, count: feats.length,
        crs: `WGS84 — ${data.dataset}`,
        areaHa: null, warnings: [],
        candidates: data.candidates, layerId: layer.id,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Box {...getRootProps()} sx={{
        border: '2px dashed', borderColor: isDragActive ? 'primary.main' : 'grey.400',
        borderRadius: 2, p: 2, textAlign: 'center', cursor: 'pointer', mb: 1,
        bgcolor: isDragActive ? 'action.hover' : 'transparent',
      }}>
        <input {...getInputProps()} />
        <CloudUpload sx={{ fontSize: 32, color: 'grey.500', mb: 0.5 }} />
        <Typography variant="body2" color="text.secondary">
          {isDragActive ? 'Drop files here...' : 'Drag & drop GIS boundary or drone grid/point-cloud JSON'}
        </Typography>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        GeoJSON • KML/KMZ • Shapefile ZIP • metric elevation-grid JSON • XYZ point-cloud JSON.
      </Typography>

      {busy && <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1 }}><CircularProgress size={14} /><Typography variant="caption">Processing boundary…</Typography></Box>}
      {error && <Alert severity="error" sx={{ mb: 1, fontSize: 12 }}>{error}</Alert>}
      {info && (
        <Box sx={{ mb: 1.5, p: 1, bgcolor: '#e8f5e9', borderRadius: 1 }}>
          <Typography variant="subtitle2" sx={{ fontSize: 13 }}>{info.name}</Typography>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
            <Chip size="small" label={`${info.count} feature(s)`} />
            {info.areaHa != null && <Chip size="small" label={`${info.areaHa} ha`} />}
            <Chip size="small" color="primary" label="Set as AOI ✓" />
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>{info.crs}</Typography>
          {(info.warnings || []).map((w, i) => (
            <Alert key={i} severity="warning" sx={{ mt: 0.5, fontSize: 11 }}>{w}</Alert>
          ))}
          {(info.candidates || []).length > 1 && (
            <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
              Matches: {info.candidates.map((c) => c.name).join(', ')}
            </Typography>
          )}
        </Box>
      )}

      <Typography variant="subtitle2" sx={{ fontSize: 13, mt: 1, mb: 0.5 }}>
        Administrative boundary (GADM/GAUL via GEE)
      </Typography>
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        <TextField size="small" fullWidth placeholder="e.g. Mbozi" value={adminName}
          onChange={(e) => setAdminName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchAdminBoundary()} />
        <TextField size="small" select SelectProps={{ native: true }} value={adminLevel}
          onChange={(e) => setAdminLevel(Number(e.target.value))} sx={{ width: 90 }}>
          <option value={1}>Admin1</option>
          <option value={2}>Admin2</option>
        </TextField>
        <Button size="small" variant="outlined" onClick={fetchAdminBoundary} disabled={busy || !adminName.trim()}>
          <Search fontSize="small" />
        </Button>
      </Box>
      {state.aoiLayerId && (
        <Typography variant="caption" color="primary" sx={{ display: 'block', mt: 1 }}>
          Current AOI: {state.layers.find((l) => l.id === state.aoiLayerId)?.name || '—'}
        </Typography>
      )}
    </Box>
  );
}
