import { useState, useRef } from 'react';
import {
  Box, Paper, Typography, TextField, Button, IconButton,
  CircularProgress, Divider, Chip, Collapse,
} from '@mui/material';
import { Code, PlayArrow, Close, Add, Map } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';
import { API, TOKEN_KEY } from '../../config/api';
import { generateId } from '../../utils/fileUtils';

const DEFAULT_CODE = `# GEE Python Code Editor
# Draw a polygon on the map first, then run code here

# Example: NDVI
# s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \\
#   .filterDate('2024-01-01', '2024-06-30') \\
#   .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \\
#   .median()
# ndvi = s2.normalizedDifference(['B8', 'B4']).rename('NDVI')
# print('NDVI computed:', ndvi)
`;

export function CodeEditor({ open, onClose }) {
  const { dispatch, state } = useApp();
  const [code, setCode] = useState(
    localStorage.getItem('gee_code_editor') || DEFAULT_CODE
  );
  const [output, setOutput] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [tiles, setTiles] = useState([]);

  const runCode = async () => {
    setRunning(true);
    setError('');
    setOutput('');
    setTiles([]);

    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const res = await fetch(API.CODE, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ code }),
      });
      const data = await res.json();

      if (data.error) {
        setError(data.error);
      } else {
        setOutput(data.output || 'Done.');

        if (data.tileUrls?.length) {
          setTiles(data.tileUrls);
          data.tileUrls.forEach((t) => {
            dispatch({
              type: 'ADD_LAYER',
              payload: {
                id: generateId(),
                name: t.name || 'Code Result',
                type: 'image',
                url: t.url,
                visible: true,
                createdAt: Date.now(),
              },
            });
          });
        }
      }
    } catch (e) {
      setError(`Network error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  const handleClose = () => {
    localStorage.setItem('gee_code_editor', code);
    onClose();
  };

  return (
    <Collapse in={open} orientation="horizontal">
      <Paper sx={{
        width: 420, height: '100%', display: 'flex', flexDirection: 'column',
        borderLeft: '1px solid #e0e0e0', overflow: 'hidden', flexShrink: 0,
      }}>
        <Box sx={{
          p: 1.5, bgcolor: '#263238', color: 'white',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Code fontSize="small" />
            <Typography variant="subtitle2">GEE Code Editor</Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <IconButton size="small" sx={{ color: 'white' }} onClick={handleClose}>
              <Close fontSize="small" />
            </IconButton>
          </Box>
        </Box>

        <Box sx={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            style={{
              flex: 1, width: '100%', border: 'none', outline: 'none',
              resize: 'none', padding: 12, fontFamily: '"Fira Code", "Consolas", monospace',
              fontSize: 13, lineHeight: 1.5, backgroundColor: '#fafafa',
              color: '#263238', tabSize: 2,
            }}
            placeholder="# Write GEE Python code here..."
            spellCheck={false}
          />
        </Box>

        <Box sx={{ p: 1, borderTop: '1px solid #e0e0e0', display: 'flex', gap: 1 }}>
          <Button
            fullWidth variant="contained" size="small"
            startIcon={running ? <CircularProgress size={14} color="inherit" /> : <PlayArrow />}
            onClick={runCode} disabled={running || !code.trim()}
            sx={{
              bgcolor: '#4caf50', '&:hover': { bgcolor: '#388e3c' },
              textTransform: 'none', fontWeight: 600,
            }}
          >
            {running ? 'Running...' : 'Run'}
          </Button>
          <IconButton size="small" onClick={() => setCode(DEFAULT_CODE)} title="Reset to example">
            <Add fontSize="small" />
          </IconButton>
        </Box>

        <Divider />

        <Box sx={{ height: 180, overflow: 'auto', p: 1.5, bgcolor: '#1e1e1e' }}>
          {error ? (
            <Typography variant="body2" sx={{ fontFamily: 'monospace', color: '#ff5252', fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {error}
            </Typography>
          ) : output ? (
            <Typography variant="body2" sx={{ fontFamily: 'monospace', color: '#a5d6a7', fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {output}
            </Typography>
          ) : (
            <Typography variant="body2" sx={{ fontFamily: 'monospace', color: '#616161', fontSize: 12, fontStyle: 'italic' }}>
              Output will appear here...
            </Typography>
          )}
        </Box>

        {tiles.length > 0 && (
          <Box sx={{ p: 1, borderTop: '1px solid #e0e0e0' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
              <Map fontSize="small" color="primary" />
              <Typography variant="caption" fontWeight={600}>
                {tiles.length} layer(s) added to map
              </Typography>
            </Box>
            {tiles.map((t, i) => (
              <Chip key={i} label={t.name} size="small" variant="outlined" sx={{ mr: 0.5, mb: 0.5 }} />
            ))}
          </Box>
        )}
      </Paper>
    </Collapse>
  );
}
