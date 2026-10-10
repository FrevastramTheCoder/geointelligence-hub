import { useState } from 'react';
import {
  Button, Avatar, Typography, Box, Menu, MenuItem, CircularProgress,
} from '@mui/material';
import { Google, Logout, AccountCircle, Link } from '@mui/icons-material';
import { getUserEmail, redirectToGEEAuth } from '../../services/authService';
import { useApp } from '../../context/AppContext';

export function LoginButton() {
  const { state, handleLogout } = useApp();
  const [anchorEl, setAnchorEl] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const email = state.auth.user?.email || getUserEmail();
  const geeConnected = state.auth.geeConnected;

  const handleLogout = () => {
    setAnchorEl(null);
    handleLogout();
  };

  const handleConnectGEE = async () => {
    setAnchorEl(null);
    setConnecting(true);
    try {
      await redirectToGEEAuth(state.auth.projectId);
    } catch (e) {
      setConnecting(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      {!geeConnected && (
        <Button
          variant="contained" size="small"
          startIcon={connecting ? <CircularProgress size={14} color="inherit" /> : <Link />}
          onClick={handleConnectGEE}
          disabled={connecting}
          sx={{
            bgcolor: '#ff9800', '&:hover': { bgcolor: '#f57c00' },
            textTransform: 'none', fontWeight: 600, fontSize: 12, py: 0.3,
          }}
        >
          Connect GEE
        </Button>
      )}
      <Avatar
        onClick={(e) => setAnchorEl(e.currentTarget)}
        sx={{
          width: 30, height: 30, bgcolor: '#4285F4', fontSize: 14, cursor: 'pointer',
          border: '2px solid rgba(255,255,255,0.5)',
        }}
      >
        {email ? email.charAt(0).toUpperCase() : <AccountCircle />}
      </Avatar>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        PaperProps={{ sx: { minWidth: 200, mt: 0.5 } }}
      >
        <Box sx={{ px: 2, py: 1 }}>
          <Typography variant="body2" fontWeight={600}>{email}</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
            <Box sx={{
              width: 8, height: 8, borderRadius: '50%',
              bgcolor: geeConnected ? '#4caf50' : '#ff9800',
            }} />
            <Typography variant="caption" color="text.secondary">
              {geeConnected ? 'GEE Connected' : 'GEE not connected'}
            </Typography>
          </Box>
        </Box>
        {!geeConnected && (
          <MenuItem onClick={handleConnectGEE} sx={{ gap: 1 }}>
            <Google fontSize="small" />
            <Typography variant="body2">Connect GEE</Typography>
          </MenuItem>
        )}
        <MenuItem onClick={handleLogout} sx={{ gap: 1 }}>
          <Logout fontSize="small" />
          <Typography variant="body2">Sign Out</Typography>
        </MenuItem>
      </Menu>
    </Box>
  );
}
