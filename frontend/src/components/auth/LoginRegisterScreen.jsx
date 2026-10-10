import { useState } from 'react';
import {
  Box, Container, Paper, TextField, Button, Typography, Tabs, Tab,
  Alert, CircularProgress, Divider, Chip,
} from '@mui/material';
import { Google, Public, Map, Analytics, CheckCircle, Link } from '@mui/icons-material';
import { registerWithEmail, loginWithEmail, redirectToGEEAuth } from '../../services/authService';
import { useApp } from '../../context/AppContext';

export function LoginRegisterScreen() {
  const { dispatch } = useApp();
  const [tab, setTab] = useState(0);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [needGEE, setNeedGEE] = useState(false);
  const [connecting, setConnecting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      const fn = tab === 0 ? loginWithEmail : registerWithEmail;
      const result = tab === 0 ? await fn(email, password) : await fn(email, password, name);
      setSuccess(result.message || 'Success');
      if (result.geeConnected) {
        dispatch({ type: 'SET_AUTH', payload: { loggedIn: true, geeConnected: true, user: { email: result.email } } });
      } else {
        setNeedGEE(true);
        dispatch({ type: 'SET_AUTH', payload: { loggedIn: true, geeConnected: false, user: { email: result.email } } });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleConnectGEE = async () => {
    setConnecting(true);
    try {
      await redirectToGEEAuth();
    } catch (e) {
      setError(e.message);
      setConnecting(false);
    }
  };

  return (
    <Box
      sx={{
        height: '100vh', width: '100vw', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'linear-gradient(135deg, #1a237e 0%, #0d47a1 50%, #01579b 100%)',
      }}
    >
      <Container maxWidth="sm">
        <Paper elevation={8} sx={{ p: 4, borderRadius: 4 }}>
          {/* Header */}
          <Box sx={{ textAlign: 'center', mb: 3 }}>
            <Public sx={{ fontSize: 48, color: '#1a237e' }} />
            <Typography variant="h4" fontWeight={700} sx={{ color: '#1a237e', mt: 1 }}>
              GeoIntelligence Hub
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Multi-User Earth Engine Analysis
            </Typography>
          </Box>

          {/* Feature chips */}
          <Box sx={{ display: 'flex', justifyContent: 'center', gap: 1, mb: 3, flexWrap: 'wrap' }}>
            {['NDVI', 'Land Cover', 'Change Detection', 'Elevation', 'Water Index'].map((f) => (
              <Chip key={f} label={f} size="small" variant="outlined" sx={{ fontSize: 11 }} />
            ))}
          </Box>

          <Divider sx={{ mb: 3 }} />

          {!needGEE ? (
            <>
              <Tabs value={tab} onChange={(_, v) => { setTab(v); setError(''); setSuccess(''); }} centered sx={{ mb: 2 }}>
                <Tab label="Login" />
                <Tab label="Register" />
              </Tabs>

              {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
              {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

              <Box component="form" onSubmit={handleSubmit}>
                <TextField
                  fullWidth label="Email" type="email" size="small"
                  value={email} onChange={(e) => setEmail(e.target.value)}
                  sx={{ mb: 1.5 }}
                  required
                />
                <TextField
                  fullWidth label="Password" type="password" size="small"
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  sx={{ mb: 2 }}
                  required
                  inputProps={{ minLength: 6 }}
                />
                <Button
                  fullWidth variant="contained" type="submit"
                  disabled={loading || !email || !password}
                  sx={{ py: 1.2, fontWeight: 600, textTransform: 'none', bgcolor: '#1a237e' }}
                >
                  {loading ? <CircularProgress size={20} color="inherit" /> : tab === 0 ? 'Login' : 'Create Account'}
                </Button>
              </Box>
            </>
          ) : (
            <Box sx={{ textAlign: 'center' }}>
              <CheckCircle sx={{ fontSize: 56, color: '#4caf50', mb: 1 }} />
              <Typography variant="h6" fontWeight={600} gutterBottom>
                Account Ready
              </Typography>

              {/* Step-by-step guide */}
              <Paper variant="outlined" sx={{ p: 2, mb: 2, textAlign: 'left', bgcolor: '#f5f5f5' }}>
                <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                  Before connecting, make sure you have an Earth Engine account:
                </Typography>
                <Box sx={{ pl: 1 }}>
                  {[
                    'Go to signup.earthengine.google.com',
                    'Sign up with your Google account (free, 2 minutes)',
                    'Wait for approval email (usually instant)',
                    'Come back here and click "Connect Earth Engine" below',
                  ].map((step, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1 }}>
                      <Box sx={{
                        width: 20, height: 20, borderRadius: '50%', bgcolor: '#1a237e',
                        color: 'white', fontSize: 11, display: 'flex', alignItems: 'center',
                        justifyContent: 'center', flexShrink: 0, mt: 0.3,
                      }}>
                        {i + 1}
                      </Box>
                      <Typography variant="body2" sx={{ lineHeight: 1.5 }}>
                        {i === 0 ? (
                          <>
                            Go to{' '}
                            <a href="https://signup.earthengine.google.com" target="_blank" rel="noopener noreferrer"
                              style={{ color: '#1565c0', fontWeight: 600, textDecoration: 'underline' }}>
                              signup.earthengine.google.com
                            </a>
                          </>
                        ) : step}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </Paper>

              <Button
                fullWidth variant="contained"
                startIcon={connecting ? <CircularProgress size={18} color="inherit" /> : <Google />}
                onClick={handleConnectGEE}
                disabled={connecting}
                sx={{
                  py: 1.5, fontWeight: 600, textTransform: 'none',
                  bgcolor: '#4285F4', '&:hover': { bgcolor: '#3367D6' },
                }}
              >
                {connecting ? 'Redirecting to Google...' : 'Connect Earth Engine'}
              </Button>
            </Box>
          )}

          <Divider sx={{ my: 2 }}>
            <Chip label="How It Works" size="small" variant="outlined" />
          </Divider>
          <Box sx={{ display: 'flex', justifyContent: 'center', gap: 2 }}>
            {[
              { icon: '1', label: 'Register/Login' },
              { icon: <Google sx={{ fontSize: 14 }} />, label: 'Connect GEE' },
              { icon: <Map sx={{ fontSize: 14 }} />, label: 'Analyze' },
            ].map((step, i) => (
              <Box key={i} sx={{ textAlign: 'center' }}>
                <Typography variant="body2" fontWeight={600} color="#1a237e">
                  {step.icon}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {step.label}
                </Typography>
              </Box>
            ))}
          </Box>
        </Paper>
      </Container>
    </Box>
  );
}
