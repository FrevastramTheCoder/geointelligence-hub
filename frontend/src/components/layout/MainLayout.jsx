import { useState, useEffect } from 'react';
import {
  Box, AppBar, Toolbar, Typography, IconButton, LinearProgress, Button,
} from '@mui/material';
import { Menu, ChevronRight, AdminPanelSettings, Code, Logout, AccountCircle, Link } from '@mui/icons-material';
import { Sidebar } from '../sidebar/Sidebar';
import { MapView } from '../map/MapContainer';
import { BasemapSwitcher } from '../map/BasemapSwitcher';
import { ResultsPanel } from '../results/ResultsPanel';
import { AIAssistant } from '../assistant/AIAssistant';
import { AdminPanel } from '../admin/AdminPanel';
import { CodeEditor } from '../code/CodeEditor';
import { useApp } from '../../context/AppContext';
import { useGEE } from '../../hooks/useGEE';
import { getUserEmail } from '../../services/authService';
import { UpdateTokenDialog } from '../auth/UpdateTokenDialog';
import { DashboardRail } from './DashboardRail';

export function MainLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [adminOpen, setAdminOpen] = useState(false);
  const [codeOpen, setCodeOpen] = useState(false);
  const { state, handleLogout, setTokenDialogOpen } = useApp();
  const { ready, error: geeError, loading: geeLoading } = useGEE();
  const email = getUserEmail();
  const skipped = !state.auth.geeConnected && state.auth.geeSkipped;
  const tokenExpired = /expired|revoked/i.test(geeError || '');
  const statusText = skipped
    ? 'GEE skipped – map available, analysis disabled'
    : geeLoading ? 'Connecting...'
    : ready ? 'EE Ready'
    : tokenExpired ? 'Earth Engine token expired'
    : geeError || '';

  useEffect(() => {
    if (!geeLoading && tokenExpired) setTokenDialogOpen(true);
  }, [geeLoading, tokenExpired, setTokenDialogOpen]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <AppBar position="static" elevation={0} sx={{ zIndex: 1201, bgcolor: '#fff', color: '#18283e', minHeight: 56, borderBottom: '1px solid #e5eaf0' }}>
        <Toolbar variant="dense" sx={{ minHeight: 56 }}>
          <IconButton color="inherit" edge="start" onClick={() => setSidebarOpen(!sidebarOpen)} size="small" sx={{ mr: 1 }}>
            {sidebarOpen ? <Menu /> : <ChevronRight />}
          </IconButton>
          <Box sx={{ width: 30, height: 30, borderRadius: 1.5, bgcolor: '#e9f2ff', color: '#2563a6', display: 'grid', placeItems: 'center', mr: 1 }}>
            <Typography fontWeight={800} fontSize={13}>G</Typography>
          </Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
            GeoIntelligence Hub
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
            {statusText && (
              <Typography variant="caption" sx={{ color: ready ? '#218454' : skipped ? '#9b6a00' : '#bb3939', mr: 0.25 }}>
                {statusText}
              </Typography>
            )}
            <Box sx={{
              width: 8, height: 8, borderRadius: '50%',
              bgcolor: ready ? '#4caf50' : skipped ? '#ff9800' : geeError ? '#f44336' : '#ff9800',
            }} />
              <Typography variant="caption" sx={{ color: '#526276', maxWidth: 190, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {email}
            </Typography>
            <Button color="primary" size="small" startIcon={<Link />}
              onClick={() => setTokenDialogOpen(true)}
              sx={{ textTransform: 'none', fontSize: 12 }}>
              Update GEE token
            </Button>
            <IconButton color="inherit" size="small" onClick={() => setAdminOpen(true)} title="Admin">
              <AdminPanelSettings fontSize="small" />
            </IconButton>
            <IconButton color="inherit" size="small" onClick={() => setCodeOpen(!codeOpen)} title="Code Editor"
              sx={{ bgcolor: codeOpen ? '#e9f2ff' : 'transparent' }}>
              <Code fontSize="small" />
            </IconButton>
            <IconButton color="inherit" size="small" onClick={handleLogout} title="Logout">
              <Logout fontSize="small" />
            </IconButton>
          </Box>
        </Toolbar>
        {state.loading && <LinearProgress sx={{ height: 2 }} />}
      </AppBar>

      <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen(false)} />
        <Box sx={{ flex: 1, minWidth: 0, position: 'relative', display: 'flex', flexDirection: 'column', p: 1, bgcolor: '#eef2f6' }}>
          <Box sx={{ flex: 1, minHeight: 260, position: 'relative', overflow: 'hidden', borderRadius: 2, border: '1px solid #d9e1e9', boxShadow: '0 2px 8px rgba(22,42,65,.08)' }}>
          <BasemapSwitcher />
          <MapView />
          <AIAssistant />
          </Box>
        </Box>
        {state.results ? <ResultsPanel /> : <DashboardRail />}
        <CodeEditor open={codeOpen} onClose={() => setCodeOpen(false)} />
      </Box>
      <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />
      <UpdateTokenDialog />
    </Box>
  );
}
