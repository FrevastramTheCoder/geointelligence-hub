import { useState, useEffect } from 'react';
import {
  Box, Typography, Paper, Tabs, Tab, Table, TableBody,
  TableCell, TableRow, Divider, Button, IconButton,
  TextField, FormControl, InputLabel, Select, MenuItem, Alert, CircularProgress, Chip,
} from '@mui/material';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { Close, Download } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';
import { API, TOKEN_KEY } from '../../config/api';
import { exportCSV, exportGeoJSON, exportExcel } from '../../utils/fileUtils';
import { statsToChartData, getAnalysisPalette } from '../../utils/chartUtils';
import {
  requestExport, listExports, exportStatus, downloadHref,
  isCategoricalResult, compatibleFormats,
} from '../../services/exportService';
import { getCurrentAOI } from '../../services/boundaryService';

function exportStyledTIF(results) {
  const palettes = {
    LandCover: ['#FF0000','#00FF00','#FFD700','#0000FF'],
    NDVI: ['red','yellow','green'],
    NDWI: ['#8B4513','#FFD700','#00BFFF','#0000CD'],
    NDBI: ['#00FF00','#FFFF00','#FF0000'],
    Vegetation: ['#d73027','#FFD700','#FF8C00','#228B22','#004d00'],
    Elevation: ['#006400','#32CD32','#FFD700','#8B4513','#FFFFFF'],
    Slope: ['green','yellow','orange','red'],
  };

  const analysisType = results.type || '';
  const palette = palettes[analysisType];

  const token = localStorage.getItem(TOKEN_KEY);
  fetch(`${API.BASE}/export-styled`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      analysis: (results.type || '').toLowerCase(),
      geom: results.geom,
      label: results.label || results.type,
      year: 2024,
      palette: palette,
      visMin: 0,
      visMax: analysisType === 'LandCover' ? 3 : analysisType === 'Vegetation' ? 4 : 1,
      numClasses: results.stats ? Object.keys(results.stats).filter(k => k.includes('(')).length || 4 : 4,
    }),
  }).then(r => r.json()).then(d => {
    if (d.url) window.open(d.url, '_blank');
  }).catch(() => {});
}

export function ResultsPanel() {
  const { state, dispatch } = useApp();
  const { results, analyses } = state;
  const [tab, setTab] = useState(0);
  const [expFormat, setExpFormat] = useState('geotiff');
  const [expScale, setExpScale] = useState('');
  const [expCrs, setExpCrs] = useState('EPSG:4326');
  const [expName, setExpName] = useState('');
  const [expBusy, setExpBusy] = useState(false);
  const [expMsg, setExpMsg] = useState(null);
  const [expHistory, setExpHistory] = useState([]);

  useEffect(() => {
    if (tab === 3) {
      listExports().then((d) => setExpHistory(d.exports || [])).catch(() => {});
    }
  }, [tab, results?.resultId]);

  if (!results) return null;

  const chartData = statsToChartData(results.stats, results.chartData);
  const transitionRows = Object.entries(results.transition || {}).map(([transition, values]) => ({
    transition, ...(typeof values === 'object' && values ? values : { area: values }),
  }));
  const periodTransitionRows = Object.entries(results.transitionByPeriod || {}).flatMap(([period, rows]) =>
    Object.entries(rows || {}).map(([transition, values]) => ({ period, transition, ...values })));
  const resultRows = Array.isArray(results.tableData) ? results.tableData : [];
  const palette = getAnalysisPalette(results.type);
  const formats = compatibleFormats(results);
  const activeExpFormat = formats.some((format) => format.id === expFormat) ? expFormat : (formats[0]?.id || expFormat);

  const handleExport = (format) => {
    const data = { ...results, exportedAt: new Date().toISOString() };
    switch (format) {
      case 'geojson': exportGeoJSON(data, results.type); break;
      case 'csv': exportCSV(resultRows.length ? resultRows : periodTransitionRows.length ? periodTransitionRows : transitionRows.length ? transitionRows : results.chartData?.length ? results.chartData : results.stats, results.type); break;
      case 'excel': exportExcel([data], results.type); break;
    }
  };

  const pollStatus = async (taskId, tries = 12) => {
    for (let i = 0; i < tries; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      try {
        const s = await exportStatus(taskId);
        if (s.status === 'completed') {
          setExpMsg({ ok: true, text: `Export completed.${s.downloadUrl ? '' : ' Check history.'}`, url: s.downloadUrl });
          const h = await listExports().catch(() => null);
          if (h) setExpHistory(h.exports || []);
          return;
        }
        if (s.status === 'failed' || s.status === 'cancelled') {
          setExpMsg({ ok: false, text: `Export ${s.status}.` });
          return;
        }
      } catch { return; }
    }
  };

  const handleGEEExport = async () => {
    if (results.geometry?.type === 'FeatureCollection') {
      const filename = (expName.trim() || results.label || results.type || 'intersection').replace(/[^a-z0-9_-]+/gi, '_');
      if (activeExpFormat === 'geojson') exportGeoJSON(results.geometry, filename);
      else if (activeExpFormat === 'csv') exportCSV(resultRows.length ? resultRows : results.chartData?.length ? results.chartData : results.stats || {}, filename);
      else { setExpMsg({ ok: false, text: 'This local vector result supports GeoJSON and CSV export.' }); return; }
      setExpMsg({ ok: true, text: `Downloaded local ${activeExpFormat.toUpperCase()} result.` });
      return;
    }
    setExpBusy(true);
    setExpMsg(null);
    try {
      const aoi = getCurrentAOI(state);
      const rec = await requestExport({
        resultId: results.resultId || undefined,
        analysis: results.analysis?.id || results.type?.toLowerCase(),
        geometry: aoi?.geometry || undefined,
        format: expFormat,
        scale: expScale ? Number(expScale) : undefined,
        crs: expCrs || undefined,
        filename: expName.trim() || (results.label || results.type || 'result'),
      });
      if (rec.status === 'running' && rec.eeTaskId) {
        setExpMsg({ ok: true, text: 'Export submitted (large region) — RUNNING. This panel will update.' });
        pollStatus(rec.eeTaskId);
      } else {
        const url = downloadHref(rec);
        setExpMsg({ ok: true, text: `Ready: ${rec.filename || expFormat}. Opens directly in QGIS.`, url });
      }
      const h = await listExports().catch(() => null);
      if (h) setExpHistory(h.exports || []);
    } catch (e) {
      setExpMsg({ ok: false, text: e.message });
    } finally {
      setExpBusy(false);
    }
  };

  return (
    <Paper sx={{
      width: 340, height: '100%', position: 'relative', display: 'flex',
      flexDirection: 'column', borderLeft: '1px solid #e0e0e0', overflow: 'hidden',
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', p: 1.5, borderBottom: '1px solid #e0e0e0' }}>
        <Typography variant="subtitle1" fontWeight={600}>Analysis Results</Typography>
        <IconButton size="small" onClick={() => dispatch({ type: 'CLEAR_RESULTS' })}>
          <Close fontSize="small" />
        </IconButton>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="fullWidth" sx={{ minHeight: 40 }}>
        <Tab label="Stats" />
        <Tab label="Chart" />
        <Tab label="Interpret." sx={{ minWidth: 0 }} />
        <Tab label="Export" sx={{ minWidth: 0 }} />
      </Tabs>

      <Box sx={{ flex: 1, overflow: 'auto', p: 1.5 }}>
        {tab === 0 && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>{results.label}</Typography>
            <Table size="small">
              <TableBody>
                {results.stats && Object.entries(results.stats).map(([key, val]) => (
                  <TableRow key={key}>
                    <TableCell sx={{ fontWeight: 500, fontSize: 13, py: 0.5 }}>{key}</TableCell>
                    <TableCell sx={{ fontSize: 13, py: 0.5, fontFamily: 'monospace' }}>
                      {typeof val === 'number' ? val.toLocaleString() : String(val)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {(periodTransitionRows.length > 0 || transitionRows.length > 0) && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle2" gutterBottom>Transition matrix areas</Typography>
                <Table size="small">
                  <TableBody>
                    {(periodTransitionRows.length ? periodTransitionRows : transitionRows).map((row, index) => (
                      <TableRow key={`${row.period || ''}-${row.transition}-${index}`}>
                        {row.period && <TableCell sx={{ fontSize: 11, py: 0.5 }}>{row.period}</TableCell>}
                        <TableCell sx={{ fontSize: 12, py: 0.5 }}>{row.transition}</TableCell>
                        <TableCell sx={{ fontSize: 12, py: 0.5, fontFamily: 'monospace' }}>
                          {row.hectares != null ? `${row.hectares} ha` : row.area}
                          {row.square_kilometres != null ? ` / ${row.square_kilometres} km²` : ''}
                          {row.percent_of_AOI != null ? ` (${row.percent_of_AOI}%)` : ''}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
            {resultRows.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle2" gutterBottom>Feature statistics ({resultRows.length})</Typography>
                <Box sx={{ maxHeight: 360, overflow: 'auto' }}>
                  <Table size="small"><TableBody>
                    {resultRows.slice(0, 500).map((row, index) => (
                      <TableRow key={`feature-${index}`}>
                        {Object.entries(row).map(([key, value]) => (
                          <TableCell key={`${index}-${key}`} sx={{ fontSize: 11, py: 0.35, fontFamily: 'monospace' }}>
                            <b>{key}:</b> {typeof value === 'number' ? Number(value.toPrecision(6)).toString() : String(value ?? '')}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody></Table>
                </Box>
                {resultRows.length > 500 && <Typography variant="caption">Showing 500 rows; CSV export includes all {resultRows.length}.</Typography>}
              </Box>
            )}
          </Box>
        )}

        {tab === 1 && chartData.length > 0 && (
          <Box>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="value" fill={palette[0]} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <Box sx={{ mt: 1 }}>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={chartData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={60} label>
                    {chartData.map((_, i) => <Cell key={i} fill={palette[i % palette.length]} />)}
                  </Pie>
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                </PieChart>
              </ResponsiveContainer>
            </Box>
          </Box>
        )}

        {tab === 2 && (
          <Box>
            <Typography variant="body2" sx={{ lineHeight: 1.7 }}>
              {results.interpretation || 'No interpretation available.'}
            </Typography>
            {results.imageUrl && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="caption" gutterBottom display="block" color="text.secondary">
                  Result Preview:
                </Typography>
                <img src={results.imageUrl} alt="Result" style={{ width: '100%', borderRadius: 8, border: '1px solid #e0e0e0' }} />
              </Box>
            )}
          </Box>
        )}

        {tab === 3 && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>Export for QGIS</Typography>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              {results.geometry?.type === 'FeatureCollection'
                ? 'Download the computed vector cells/points and attribute table.'
                : 'Earth Engine exports are georeferenced downloads, not map screenshots.'}
            </Typography>
            <FormControl fullWidth size="small" sx={{ mb: 1 }}>
              <InputLabel>Format</InputLabel>
              <Select value={activeExpFormat} label="Format" onChange={(e) => setExpFormat(e.target.value)}>
                {formats.map((f) => <MenuItem key={f.id} value={f.id}>{f.label}</MenuItem>)}
              </Select>
            </FormControl>
            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
              <TextField size="small" label="Scale (m)" placeholder={String(results.scale || 30)}
                value={expScale} onChange={(e) => setExpScale(e.target.value)} sx={{ width: 110 }} />
              <TextField size="small" label="CRS" value={expCrs}
                onChange={(e) => setExpCrs(e.target.value)} sx={{ flex: 1 }} />
            </Box>
            <TextField size="small" fullWidth label="Filename" placeholder={results.label || results.type}
              value={expName} onChange={(e) => setExpName(e.target.value)} sx={{ mb: 1 }} />
            <Button fullWidth size="small" variant="contained" startIcon={expBusy ? <CircularProgress size={14} color="inherit" /> : <Download fontSize="small" />}
              onClick={handleGEEExport} disabled={expBusy} sx={{ textTransform: 'none', mb: 1 }}>
              {expBusy ? 'Exporting…' : 'Export'}
            </Button>
            {expMsg && (
              <Box sx={{ mb: 1 }}>
                <Alert severity={expMsg.ok ? 'success' : 'error'} sx={{ fontSize: 12 }}>{expMsg.text}</Alert>
                {expMsg.url && (
                  <Button size="small" variant="outlined" href={expMsg.url} target="_blank"
                    sx={{ mt: 0.5, textTransform: 'none' }}>
                    Download
                  </Button>
                )}
              </Box>
            )}
            {expHistory.length > 0 && (
              <Box>
                <Typography variant="caption" color="text.secondary">History</Typography>
                {expHistory.slice(0, 8).map((h) => {
                  const url = downloadHref(h);
                  return (
                    <Box key={h.id} sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
                      <Chip size="small" label={h.status} color={h.status === 'completed' ? 'success' : h.status === 'failed' ? 'error' : 'warning'} />
                      <Typography variant="caption" sx={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {h.filename} ({h.format})
                      </Typography>
                      {url && h.status === 'completed' && (
                        <Button size="small" href={url} target={url.startsWith('http') ? '_blank' : undefined}>Get</Button>
                      )}
                    </Box>
                  );
                })}
              </Box>
            )}
          </Box>
        )}
      </Box>

      <Divider />
      <Box sx={{ p: 1, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        <Button size="small" variant="outlined" startIcon={<Download />} onClick={() => handleExport('geojson')}>GeoJSON</Button>
        <Button size="small" variant="outlined" onClick={() => handleExport('csv')}>CSV</Button>
        <Button size="small" variant="outlined" onClick={() => handleExport('excel')}>Excel</Button>
        {results.tileUrl && (
          <Button size="small" variant="outlined" color="secondary" onClick={() => exportStyledTIF(results)}>GeoTIFF (QGIS)</Button>
        )}
      </Box>
    </Paper>
  );
}
