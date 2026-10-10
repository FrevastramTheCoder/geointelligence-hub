import { Box, Button, Chip, Divider, Paper, Typography } from '@mui/material';
import { Agriculture, ChangeCircle, Flood, Terrain, WaterDrop, Hub, LocalFireDepartment, Place } from '@mui/icons-material';
import { useApp } from '../../context/AppContext';

const tools = [
  { label: 'Land cover', command: 'classify land cover', icon: <Agriculture />, color: '#3a9d76' },
  { label: 'Change detection', command: 'change detection', icon: <ChangeCircle />, color: '#4779c7' },
  { label: 'NDVI', command: 'NDVI vegetation analysis', icon: <LocalFireDepartment />, color: '#4a9b66' },
  { label: 'Flood mapping', command: 'map flood extent', icon: <Flood />, color: '#4786bd' },
  { label: 'Suitability', command: 'suitability analysis', icon: <Hub />, color: '#299c8d' },
  { label: 'Terrain', command: 'slope terrain analysis', icon: <Terrain />, color: '#68966a' },
  { label: 'Water bodies', command: 'water extent', icon: <WaterDrop />, color: '#388ac5' },
  { label: 'Spatial stats', command: 'global Moran', icon: <Place />, color: '#8063ba' },
];

export function DashboardRail() {
  const { state } = useApp();
  const recent = [...(state.analyses || [])].reverse().slice(0, 5);
  const selectTool = (command) => window.dispatchEvent(new CustomEvent('geoai:quick-command', { detail: command }));

  return (
    <Box sx={{ width: 270, flex: '0 0 270px', p: 1.25, overflow: 'auto', bgcolor: '#f4f7fb', borderLeft: '1px solid #e1e7ef', '@media (max-width: 1120px)': { display: 'none' } }}>
      <Paper variant="outlined" sx={{ p: 1.25, borderRadius: 2, mb: 1.25 }}>
        <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>Analysis tools</Typography>
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 0.75 }}>
          {tools.map((tool) => (
            <Button key={tool.label} onClick={() => selectTool(tool.command)} variant="outlined"
              sx={{ minWidth: 0, minHeight: 72, p: 0.5, borderColor: '#e6ebf1', color: '#263449', display: 'flex', flexDirection: 'column', gap: 0.35,
                textTransform: 'none', fontSize: 10.5, '&:hover': { bgcolor: '#f7faff', borderColor: tool.color } }}>
              <Box sx={{ color: tool.color, display: 'flex', '& svg': { fontSize: 22 } }}>{tool.icon}</Box>{tool.label}
            </Button>
          ))}
        </Box>
      </Paper>
      <Paper variant="outlined" sx={{ p: 1.25, borderRadius: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="subtitle2" fontWeight={700}>Recent analyses</Typography>
          <Chip size="small" label={recent.length} sx={{ height: 20 }} />
        </Box>
        {recent.length ? recent.map((item, index) => (
          <Box key={item.id || item.timestamp || index} sx={{ py: 0.8, borderTop: index ? '1px solid #edf0f4' : 0 }}>
            <Typography variant="body2" fontWeight={600} noWrap>{item.label || item.type || 'GIS analysis'}</Typography>
            <Typography variant="caption" color="text.secondary">
              {item.timestamp ? new Date(item.timestamp).toLocaleString() : 'Saved result'}
            </Typography>
          </Box>
        )) : (
          <>
            <Divider sx={{ mb: 1 }} />
            <Typography variant="body2" color="text.secondary">Your completed analyses will appear here. Choose a tool to start.</Typography>
          </>
        )}
      </Paper>
    </Box>
  );
}
