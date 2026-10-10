import { useState, useEffect } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Typography, Alert, CircularProgress, Divider, Box,
} from '@mui/material';
import { Link, Key } from '@mui/icons-material';
import { connectGEE, redirectToGEEAuth, updateSetupStep } from '../../services/authService';
import { useApp } from '../../context/AppContext';

const isPlausibleGoogleToken = (t) => t.startsWith('ya29.') && t.length > 30;
const isValidProjectId = (p) => /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(p);

/**
 * Standalone GEE token update — available everywhere (header menu,
 * chatbot error button). No wizard required: paste a fresh token
 * (or OAuth when the backend is configured) and keep working.
 */
export function UpdateTokenDialog() {
  const { state, handleWizardComplete, tokenDialogOpen, setTokenDialogOpen } = useApp();
  const [projectId, setProjectId] = useState('');
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);

  useEffect(() => {
    if (tokenDialogOpen) {
      setError('');
      setToken('');
      setProjectId(
        state.auth.projectId ||
        localStorage.getItem('gee_pending_project') ||
        ''
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tokenDialogOpen]);

  const close = () => {
    if (!saving && !oauthBusy) setTokenDialogOpen(false);
  };

  const handleConnect = async () => {
    setError('');
    const tok = token.trim();
    const pid = projectId.trim();
    if (!isValidProjectId(pid)) {
      setError('Enter a valid Google Cloud Project ID (lowercase, 6-30 chars).');
      return;
    }
    if (!isPlausibleGoogleToken(tok)) {
      setError(
        `That (${tok.length} chars) is not a Google access token. A real token starts ` +
        `with "ya29." and is ~200 chars — copy the Access token from OAuth 2.0 Playground ` +
        `(scopes: earthengine + cloud-platform). Playground tokens expire after ~1 hour.`
      );
      return;
    }
    setSaving(true);
    try {
      localStorage.setItem('gee_pending_project', pid);
      await connectGEE(tok, pid);
      await updateSetupStep(5).catch(() => null);
      setTokenDialogOpen(false);
      await handleWizardComplete();
    } catch (e) {
      setError(e?.message || 'GEE connection failed.');
    } finally {
      setSaving(false);
    }
  };

  const handleOAuth = async () => {
    setError('');
    const pid = projectId.trim();
    if (!isValidProjectId(pid)) {
      setError('Enter Project ID first — OAuth needs it.');
      return;
    }
    setOauthBusy(true);
    try {
      localStorage.setItem('gee_pending_project', pid);
      await redirectToGEEAuth(pid);
    } catch (e) {
      setError(e?.message || 'Google authorization failed.');
      setOauthBusy(false);
    }
  };

  return (
    <Dialog open={!!tokenDialogOpen} onClose={close} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ fontSize: 16, fontWeight: 700 }}>
        Connect / Update Earth Engine token
      </DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Token expired or revoked? Paste a fresh one here — no wizard needed.
          Playground tokens last ~1 hour. Your maps, layers and projects are kept.
        </Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <TextField
          fullWidth size="small" label="Google Cloud Project ID"
          value={projectId} onChange={(e) => setProjectId(e.target.value)}
          placeholder="finalurbancontrol" sx={{ mb: 2 }}
        />
        <TextField
          fullWidth size="small" label="Google access token (ya29…)"
          value={token} onChange={(e) => setToken(e.target.value)}
          placeholder="ya29.…"
          multiline minRows={2} sx={{ mb: 2 }}
        />
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="contained" startIcon={saving ? <CircularProgress size={16} color="inherit" /> : <Key />}
            onClick={handleConnect} disabled={saving || oauthBusy}
            sx={{ textTransform: 'none', fontWeight: 600 }}
          >
            {saving ? 'Connecting…' : 'Update token'}
          </Button>
          <Button
            variant="outlined" startIcon={<Link />}
            onClick={handleOAuth} disabled={saving || oauthBusy}
            sx={{ textTransform: 'none' }}
          >
            Use Google OAuth
          </Button>
        </Box>
        <Divider sx={{ my: 2 }} />
        <Typography variant="caption" color="text.secondary">
          Get a token: OAuth 2.0 Playground → select scopes{' '}
          <code>earthengine</code> + <code>cloud-platform</code> → Authorize →
          Exchange → copy the Access token.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={close} sx={{ textTransform: 'none' }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
