import { useState } from 'react';
import {
  Box, Container, Paper, Typography, Button, TextField, Tabs, Tab,
  Alert, CircularProgress, Divider, InputAdornment, IconButton,
} from '@mui/material';
import { Google, Public, Visibility, VisibilityOff } from '@mui/icons-material';
import { loginWithEmail, registerWithEmail, newGoogleState, getLastEmail } from '../services/authService';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const REDIRECT_URI = window.location.origin + '/';
const GOOGLE_AUTH_ERROR_KEY = 'google_auth_error';

export function WelcomePage({ onComplete }) {
  const [tab, setTab] = useState(0);
  const [email, setEmail] = useState(() => getLastEmail());
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(() => {
    // OAuth callback failure (e.g. denied at Google) surfaces here once.
    try {
      const msg = sessionStorage.getItem(GOOGLE_AUTH_ERROR_KEY);
      if (msg) sessionStorage.removeItem(GOOGLE_AUTH_ERROR_KEY);
      // Earth Engine token expiry is a workspace issue, not a login failure.
      return /Google access token is expired or revoked/i.test(msg || '') ? '' : (msg || '');
    } catch {
      return '';
    }
  });
  const [showPw, setShowPw] = useState(false);

  const handleGoogleLogin = () => {
    if (!GOOGLE_CLIENT_ID) { setError('Google OAuth not configured'); return; }
    // Authorization CODE flow (login scopes only — never GEE scopes here).
    const state = newGoogleState();
    try {
      sessionStorage.setItem('google_oauth_state', state);
      sessionStorage.removeItem('google_oauth_code_done');
    } catch { /* ignore */ }
    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID, redirect_uri: REDIRECT_URI,
      response_type: 'code', scope: 'openid profile email', prompt: 'select_account',
      access_type: 'online', state,
    })}`;
  };

  const handleEmailSubmit = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const data = tab === 0
        ? await loginWithEmail(email, password)
        : await registerWithEmail(email, password, name);
      onComplete(data);
    } catch (err) {
      if (tab === 1 && /already registered/i.test(err.message)) {
        setTab(0);
        setError('An account with this email already exists. Sign in with your password or use Google sign-in.');
      } else {
        setError(err.message);
      }
    } finally { setLoading(false); }
  };

  return (
    <Box sx={{
      minHeight: '100vh', overflow: 'auto', display: 'flex', alignItems: 'safe center', justifyContent: 'center', p: 2,
      background: 'linear-gradient(135deg, #0a1628 0%, #0d2137 25%, #132742 50%, #0a1628 100%)',
      position: 'relative',
    }}>
      <Container maxWidth="xs" sx={{ position: 'relative', zIndex: 1, my: 'auto' }}>
        <Paper sx={{ p: 3, borderRadius: 4 }}>
          <Box sx={{ textAlign: 'center', mb: 2 }}>
            <Public sx={{ fontSize: 44, color: '#1a237e' }} />
            <Typography variant="h5" fontWeight={700} color="#1a237e">GeoIntelligence Hub</Typography>
            <Typography variant="body2" color="text.secondary">Your Gateway to Earth Engine Analysis</Typography>
          </Box>

          <Button fullWidth variant="contained" startIcon={<Google />} onClick={handleGoogleLogin}
            sx={{ py: 1.2, fontWeight: 600, textTransform: 'none', fontSize: 14,
              bgcolor: '#4285F4', '&:hover': { bgcolor: '#3367D6' }, borderRadius: 2 }}>
            Continue with Google
          </Button>

          <Divider sx={{ my: 2 }}>
            <Typography variant="caption" color="text.secondary">OR</Typography>
          </Divider>

          <Tabs value={tab} onChange={(_, v) => { setTab(v); setError(''); }} variant="fullWidth" sx={{ minHeight: 36, mb: 1.5 }}>
            <Tab label="Sign In" sx={{ minHeight: 36, py: 0 }} />
            <Tab label="Register" sx={{ minHeight: 36, py: 0 }} />
          </Tabs>

          {error && <Alert severity="error" sx={{ mb: 1.5, py: 0 }}>{error}</Alert>}

          <Box component="form" onSubmit={handleEmailSubmit}>
            {tab === 1 && (
              <TextField fullWidth label="Full Name" size="small" value={name}
                onChange={e => setName(e.target.value)} sx={{ mb: 1.2 }} />
            )}
            <TextField fullWidth label="Email" type="email" size="small" value={email}
              onChange={e => setEmail(e.target.value)} sx={{ mb: 1.2 }} required />
            <TextField fullWidth label="Password" type={showPw ? 'text' : 'password'} size="small"
              value={password} onChange={e => setPassword(e.target.value)} sx={{ mb: 1.5 }}
               required inputProps={{ minLength: 8 }}
              InputProps={{ endAdornment: (
                <InputAdornment position="end">
                  <IconButton size="small" onClick={() => setShowPw(!showPw)} edge="end">
                    {showPw ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                  </IconButton>
                </InputAdornment>
              )}} />

            <Button fullWidth variant="contained" type="submit" disabled={loading || !email || !password}
              sx={{ py: 1.2, fontWeight: 600, textTransform: 'none', bgcolor: '#1a237e' }}>
              {loading ? <CircularProgress size={20} color="inherit" /> : tab === 0 ? 'Sign In' : 'Create Account'}
            </Button>
          </Box>
        </Paper>
      </Container>
    </Box>
  );
}
