import { useState, useEffect } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableRow,
  TableHead, TableContainer, IconButton, Dialog, DialogTitle,
  DialogContent, DialogActions, Button, TextField, Alert, Chip,
  CircularProgress,
} from '@mui/material';
import { Visibility, Close, AdminPanelSettings } from '@mui/icons-material';
import { API } from '../../config/api';

export function AdminPanel({ open, onClose }) {
  const [key, setKey] = useState('');
  const [authed, setAuthed] = useState(false);
  const [users, setUsers] = useState([]);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchUsers = async (adminKey) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API.BASE}/admin/users`, {
        headers: { 'X-Admin-Key': adminKey },
      });
      if (!res.ok) throw new Error('Unauthorized - wrong admin key');
      const data = await res.json();
      setUsers(Object.entries(data.users || {}).map(([email, info]) => ({ email, ...info })));
      setAuthed(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setAuthed(false);
    setKey('');
    setUsers([]);
    setDetail(null);
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <AdminPanelSettings color="primary" />
        Admin Panel
        <IconButton onClick={handleClose} sx={{ ml: 'auto' }}>
          <Close />
        </IconButton>
      </DialogTitle>
      <DialogContent>
        {!authed ? (
          <Box sx={{ py: 3, textAlign: 'center' }}>
            <AdminPanelSettings sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Enter admin key to view registered users
            </Typography>
            <TextField
              type="password" label="Admin Key" size="small"
              value={key} onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchUsers(key)}
              sx={{ mb: 1 }}
              fullWidth
            />
            {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
          </Box>
        ) : (
          <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
              <Typography variant="subtitle1" fontWeight={600}>
                Registered Users
              </Typography>
              <Chip label={users.length} size="small" color="primary" />
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              Backend never returns passwords or GEE tokens. Only connection status is shown.
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Email</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Name</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>GEE</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>OAuth</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Verified</TableCell>
                    <TableCell sx={{ fontWeight: 600 }}>Step</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {users.map((u) => (
                    <TableRow key={u.email} hover>
                      <TableCell sx={{ fontSize: 13 }}>{u.email}</TableCell>
                      <TableCell sx={{ fontSize: 13 }}>{u.name || '-'}</TableCell>
                      <TableCell>
                        <Chip
                          label={u.geeConnected ? 'Connected' : 'Not Connected'}
                          size="small"
                          color={u.geeConnected ? 'success' : 'warning'}
                        />
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={u.oauthConnected ? 'Yes' : 'No'}
                          size="small"
                          variant="outlined"
                        />
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={u.verified ? 'Yes' : 'No'}
                          size="small"
                          color={u.verified ? 'success' : 'default'}
                        />
                      </TableCell>
                      <TableCell sx={{ fontSize: 13 }}>{u.setupStep ?? '-'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {authed ? (
          <Box sx={{ display: 'flex', gap: 1, width: '100%', justifyContent: 'space-between' }}>
            <Typography variant="caption" color="text.secondary">
              {users.length} users registered
            </Typography>
            <Button onClick={handleClose} size="small">Close</Button>
          </Box>
        ) : (
          <Button onClick={() => fetchUsers(key)} variant="contained" size="small" disabled={!key || loading}>
            {loading ? <CircularProgress size={16} /> : 'Access Admin'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
