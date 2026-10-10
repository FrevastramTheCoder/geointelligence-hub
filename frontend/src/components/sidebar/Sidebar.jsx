import { useState } from 'react';
import {
  Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  Collapse, IconButton, Typography, Box, Divider,
} from '@mui/material';
import {
  Layers, Analytics, Upload, Bookmark, FolderCopy,
  ExpandLess, ExpandMore, ChevronLeft,
} from '@mui/icons-material';
import { LayerPanel } from './LayerPanel';
import { AnalysisPanel } from './AnalysisPanel';
import { UploadPanel } from '../upload/UploadPanel';
import { AOIPanel } from '../aoi/AOIPanel';
import { ProjectPanel } from './ProjectPanel';
import { useApp } from '../../context/AppContext';

const DRAWER_WIDTH = 248;

export function Sidebar({ open, onToggle }) {
  const [section, setSection] = useState('layers');
  const { state } = useApp();

  const sections = [
    { id: 'layers', icon: <Layers />, label: 'Layers', count: state.layers.length },
    { id: 'analysis', icon: <Analytics />, label: 'Analysis', count: null },
    { id: 'upload', icon: <Upload />, label: 'Upload', count: null },
    { id: 'aoi', icon: <Bookmark />, label: 'AOIs', count: state.aois.length },
    { id: 'projects', icon: <FolderCopy />, label: 'Projects', count: state.projects.length },
  ];

  return (
    <Drawer
      variant="persistent"
      anchor="left"
      open={open}
      sx={{
        width: open ? DRAWER_WIDTH : 0,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          position: 'relative',
          height: '100%',
          borderRight: '1px solid #17344d',
          bgcolor: '#0d2132',
          color: '#e8eef4',
          '& .MuiDivider-root': { borderColor: 'rgba(255,255,255,.12)' },
          '& .MuiTypography-root': { color: 'inherit' },
          '& .MuiListItemIcon-root': { color: '#9fb5c7' },
        },
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', p: 1.5 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, fontSize: 15 }}>
          GeoIntelligence Hub
        </Typography>
        <IconButton onClick={onToggle} size="small">
          <ChevronLeft />
        </IconButton>
      </Box>
      <Divider />
      <List dense sx={{ px: 1 }}>
        {sections.map((s) => (
          <ListItemButton
            key={s.id}
            selected={section === s.id}
            onClick={() => setSection(section === s.id ? null : s.id)}
            sx={{ borderRadius: 1, mb: 0.5, color: '#dbe6ef', '&:hover': { bgcolor: 'rgba(255,255,255,.08)' }, '&.Mui-selected': { bgcolor: '#225bb5', color: '#fff', '& .MuiListItemIcon-root': { color: '#fff' } } }}
          >
            <ListItemIcon sx={{ minWidth: 36 }}>{s.icon}</ListItemIcon>
            <ListItemText primary={s.label} primaryTypographyProps={{ fontSize: 14 }} />
            {s.count !== null && (
              <Typography variant="caption" sx={{ bgcolor: '#23425c', color: '#fff', px: 1, borderRadius: 1 }}>
                {s.count}
              </Typography>
            )}
            {section === s.id ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
          </ListItemButton>
        ))}
      </List>
      <Divider />
      <Box sx={{ flex: 1, overflow: 'auto', p: 1, bgcolor: '#f4f7fa', color: '#1d2d3e' }}>
        <Collapse in={section === 'layers'}>
          <LayerPanel />
        </Collapse>
        <Collapse in={section === 'analysis'}>
          <AnalysisPanel />
        </Collapse>
        <Collapse in={section === 'upload'}>
          <UploadPanel />
        </Collapse>
        <Collapse in={section === 'aoi'}>
          <AOIPanel />
        </Collapse>
        <Collapse in={section === 'projects'}>
          <ProjectPanel />
        </Collapse>
      </Box>
    </Drawer>
  );
}
