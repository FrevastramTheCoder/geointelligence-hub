import { useState } from 'react';

import {
  Box,
  Container,
  Paper,
  Typography,
  Button,
  TextField,
  LinearProgress,
  Alert,
  Chip,
} from '@mui/material';

import {
  OpenInNew,
  Google,
  Public,
  Cloud,
  Api,
  Key,
} from '@mui/icons-material';

import {
  getSetupStep,
  getUserEmail,
  updateSetupStep,
  redirectToGEEAuth,
  skipGEE,
  connectGEE,
} from '../services/authService';

import {
  API,
  TOKEN_KEY,
} from '../config/api';

import { useApp } from '../context/AppContext';


/* ============================================================
   AUTH HEADERS
   ============================================================ */

function authHeaders() {
  const token =
    localStorage.getItem(TOKEN_KEY);

  return {
    'Content-Type':
      'application/json',

    Authorization:
      `Bearer ${token}`,
  };
}


/* ============================================================
   SETUP STEPS
   ============================================================ */

const STEPS = [
  {
    id: 'google-account',
    title: 'Google Account',
    desc: 'Enter the Google email used for Earth Engine.',
    icon: <Public />,
  },

  {
    id: 'gee-signup',
    title: 'Sign Up for GEE',
    desc: 'Register for a free Earth Engine account.',
    icon: <Api />,
  },

  {
    id: 'cloud-project',
    title: 'Create Cloud Project',
    desc: 'Create a GCP project + enable EE API.',
    icon: <Cloud />,
  },

  {
    id: 'project-id',
    title: 'Enter Project ID',
    desc: 'Enter your Cloud Project ID.',
    icon: <Key />,
  },

  {
    id: 'connect-gee',
    title: 'Connect GEE Account',
    desc: 'Link your Google account OR paste your GEE token.',
    icon: <Google />,
  },
];


/* ============================================================
   SETUP WIZARD
   ============================================================ */

export function SetupWizard({
  onComplete,
}) {
  const { state } = useApp();

  /*
   * Setup step is 0-based in this UI.
   */
  const initialStep = Math.min(
    Math.max(
      getSetupStep(),
      0
    ),
    4
  );

  const [step, setStep] =
    useState(initialStep);

  const [email, setEmail] =
    useState(
      getUserEmail() || ''
    );

  const [projectId, setProjectId] =
    useState(
      localStorage.getItem(
        'gee_pending_project'
      ) || ''
    );

  const [done, setDone] =
    useState(
      new Set(
        Array.from(
          {
            length: initialStep,
          },
          (_, i) => i
        )
      )
    );

  const [preview, setPreview] =
    useState({
      show: false,
      ok: false,
      msg: '',
    });

  const [geeToken, setGeeToken] =
    useState('');

  const [saving, setSaving] =
    useState(false);

  const [skippingGEE, setSkippingGEE] =
    useState(false);

  const [error, setError] =
    useState('');


  /* ==========================================================
     PROJECT ID VALIDATION
     ========================================================== */

  const validateProjectId = (id) => {
    return /^[a-z][a-z0-9\-]{4,28}[a-z0-9]$/.test(
      id
    );
  };


  /* ==========================================================
     MARK STEP DONE
     ========================================================== */

  const markDone = async (i) => {
    const nd =
      new Set([
        ...done,
        i,
      ]);

    setError('');

    /*
     * Step 4 = Project ID
     */
    if (i === 3) {
      setSaving(true);

      try {
        await saveProject();

        await updateSetupStep(4);

        setDone(nd);

        setStep(4);

      } catch (e) {
        setError(
          e?.message ||
          'Failed to save project.'
        );
      } finally {
        setSaving(false);
      }

      return;
    }

    setDone(nd);

    setStep(
      Math.min(
        i + 1,
        4
      )
    );

    updateSetupStep(
      i + 1
    ).catch(
      (e) =>
        setError(
          e?.message ||
          'Failed to update setup.'
        )
    );
  };


  /* ==========================================================
     SAVE GOOGLE CLOUD PROJECT
     ========================================================== */

  const saveProject = async () => {
    const cleanProjectId =
      projectId.trim();

    if (
      !cleanProjectId ||
      !validateProjectId(
        cleanProjectId
      )
    ) {
      throw new Error(
        'Enter a valid Google Cloud Project ID'
      );
    }

    const res = await fetch(
      API.PROJECTS,
      {
        method: 'POST',

        headers:
          authHeaders(),

        body: JSON.stringify({
          projectId:
            cleanProjectId,
        }),
      }
    );

    const data =
      await res.json();

    if (
      !res.ok ||
      data.error
    ) {
      throw new Error(
        data.error ||
        'Failed to save Google Cloud Project ID'
      );
    }

    localStorage.setItem(
      'gee_pending_project',
      cleanProjectId
    );

    return data;
  };


  /* ==========================================================
     CONNECT GEE WITH GOOGLE OAUTH
     ========================================================== */

  const handleConnectGEE =
    async () => {
      setSaving(true);
      setError('');

      try {
        const cleanProjectId =
          projectId.trim();

        if (!cleanProjectId) {
          throw new Error(
            'Enter Project ID first'
          );
        }

        if (
          !validateProjectId(
            cleanProjectId
          )
        ) {
          throw new Error(
            'Invalid Project ID format'
          );
        }

        /*
         * Keep project ID available
         * for the OAuth callback.
         */
        localStorage.setItem(
          'gee_pending_project',
          cleanProjectId
        );

        await redirectToGEEAuth(
          cleanProjectId
        );

      } catch (e) {
        setError(
          e?.message ||
          'Google authorization failed.'
        );

        setSaving(false);
      }
    };


  /* ==========================================================
     CONNECT GEE WITH MANUAL TOKEN
     ========================================================== */

  const isPlausibleGoogleToken = (t) =>
    t.startsWith('ya29.') && t.length > 30;

  const handleManualToken =
    async () => {
      setError('');

      const tok = geeToken.trim();

      if (!tok) {
        setError(
          'Paste your GEE access token (starts with "ya29.").'
        );

        return;
      }

      // The 40-char hex string in your screenshot is NOT a Google token.
      // Fail fast with guidance instead of "Earth Engine authentication failed".
      if (!isPlausibleGoogleToken(tok)) {
        setError(
          `That (${tok.length} chars) is not a Google access token. A real token starts ` +
          `with "ya29." and is ~200 chars. Use the blue "Connect Google Earth Engine" ` +
          `button, or in OAuth Playground copy the Access token (earthengine + ` +
          `cloud-platform scopes), not an auth code or session id.`
        );

        return;
      }

      if (!projectId.trim()) {
        setError(
          'Enter Project ID first (Step 4 value, e.g. my-project-12345)'
        );

        return;
      }

      if (
        !validateProjectId(
          projectId.trim()
        )
      ) {
        setError(
          'Invalid Project ID format'
        );

        return;
      }

      setSaving(true);
      localStorage.setItem('gee_pending_project', projectId.trim());

      try {
        await connectGEE(
          tok,
          projectId.trim()
        );

        /*
         * GEE successfully connected.
         */
        await updateSetupStep(5);

        if (onComplete) {
          onComplete();
        }

      } catch (e) {
        setError(
          e?.message ||
          'GEE connection failed'
        );
      } finally {
        setSaving(false);
      }
    };


  /* ==========================================================
     SKIP GEE
     ========================================================== */

  const handleSkipGEE =
    async () => {
      setError('');
      setSkippingGEE(true);

      try {
        /*
         * Mark GEE as intentionally skipped.
         *
         * This DOES NOT pretend GEE is connected.
         */
        skipGEE();

        /*
         * Complete onboarding.
         */
        await updateSetupStep(5);

        /*
         * Tell parent component that
         * setup has finished.
         */
        if (onComplete) {
          onComplete({
            geeConnected: false,
            geeSkipped: true,
          });

          return;
        }

        /*
         * Fallback.
         *
         * Only used if SetupWizard is rendered
         * without an onComplete callback.
         */
        window.location.href =
          '/dashboard';

      } catch (e) {
        console.error(
          'Failed to skip GEE:',
          e
        );

        setError(
          e?.message ||
          'Unable to continue without GEE.'
        );

        setSkippingGEE(false);
      }
    };


  /* ==========================================================
     PROGRESS
     ========================================================== */

  const progress =
    (done.size / 5) * 100;


  /* ==========================================================
     UI
     ========================================================== */

  return (
    <Box
      sx={{
        minHeight: '100vh',

        background:
          'linear-gradient(135deg,#e8eaf6,#c5cae9,#e3f2fd)',

        overflow: 'auto',

        display: 'flex',

        justifyContent:
          'center',

        p: 3,

        pt: 2,

        pb: 6,
      }}
    >

      <Container
        maxWidth="sm"
        sx={{
          my: 'auto',
        }}
      >

        <Paper
          sx={{
            p: 4,

            borderRadius: 4,

            boxShadow:
              '0 8px 40px rgba(0,0,0,0.12)',
          }}
        >

          {/* ==================================================
              HEADER
              ================================================== */}

          <Box
            sx={{
              textAlign: 'center',
              mb: 2,
            }}
          >

            <Public
              sx={{
                fontSize: 44,
                color: '#1a237e',
              }}
            />

            <Typography
              variant="h5"
              fontWeight={700}
              color="#1a237e"
              sx={{
                mt: 1,
              }}
            >
              Earth Engine Setup
            </Typography>

            <Typography
              variant="body2"
              color="text.secondary"
            >
              Step {step + 1} of 5
            </Typography>

          </Box>


          {/* ==================================================
              PROGRESS BAR
              ================================================== */}

          <LinearProgress
            variant="determinate"
            value={progress}
            sx={{
              mb: 3,

              height: 10,

              borderRadius: 5,

              bgcolor: '#e0e0e0',

              '& .MuiLinearProgress-bar':
                {
                  bgcolor:
                    '#1a237e',
                },
            }}
          />


          {/* ==================================================
              STEP 1
              ================================================== */}

          {step === 0 && (
            <Box>

              <Typography
                variant="subtitle1"
                fontWeight={600}
                gutterBottom
              >
                {STEPS[0].title}
              </Typography>

              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mb: 2,
                }}
              >
                {STEPS[0].desc}
              </Typography>

              <TextField
                fullWidth
                size="small"
                label="Google Email"
                placeholder="you@gmail.com"
                value={email}
                onChange={(e) =>
                  setEmail(
                    e.target.value
                  )
                }
                sx={{
                  mb: 2,
                }}
              />

              <Button
                variant="contained"
                onClick={() =>
                  markDone(0)
                }
                disabled={
                  !email.trim()
                }
                sx={{
                  textTransform:
                    'none',

                  bgcolor:
                    '#1a237e',
                }}
              >
                Continue
              </Button>

            </Box>
          )}


          {/* ==================================================
              STEP 2
              ================================================== */}

          {step === 1 && (
            <Box>

              <Typography
                variant="subtitle1"
                fontWeight={600}
                gutterBottom
              >
                {STEPS[1].title}
              </Typography>

              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mb: 2,
                }}
              >
                {STEPS[1].desc}
              </Typography>

              <Box
                sx={{
                  display: 'flex',
                  gap: 1,
                }}
              >

                <Button
                  variant="outlined"
                  endIcon={
                    <OpenInNew />
                  }
                  href="https://signup.earthengine.google.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{
                    textTransform:
                      'none',
                  }}
                >
                  Open Signup
                </Button>

                <Button
                  variant="contained"
                  onClick={() =>
                    markDone(1)
                  }
                  sx={{
                    textTransform:
                      'none',

                    bgcolor:
                      '#1a237e',
                  }}
                >
                  Done, Continue
                </Button>

              </Box>

            </Box>
          )}


          {/* ==================================================
              STEP 3
              ================================================== */}

          {step === 2 && (
            <Box>

              <Typography
                variant="subtitle1"
                fontWeight={600}
                gutterBottom
              >
                {STEPS[2].title}
              </Typography>

              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mb: 2,
                }}
              >
                {STEPS[2].desc}
              </Typography>

              {[
                'Go to console.cloud.google.com',
                'Create a new project',
                'Enable Earth Engine API',
                'Copy your Project ID',
              ].map(
                (s, i) => (
                  <Box
                    key={i}
                    sx={{
                      display:
                        'flex',

                      gap: 1,

                      mb: 0.5,
                    }}
                  >

                    <Chip
                      label={i + 1}
                      size="small"
                    />

                    <Typography
                      variant="body2"
                    >
                      {s}
                    </Typography>

                  </Box>
                )
              )}

              <Box
                sx={{
                  display: 'flex',
                  gap: 1,
                  mt: 2,
                }}
              >

                <Button
                  variant="outlined"
                  endIcon={
                    <OpenInNew />
                  }
                  href="https://console.cloud.google.com/projectcreate"
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{
                    textTransform:
                      'none',
                  }}
                >
                  Open Console
                </Button>

                <Button
                  variant="contained"
                  onClick={() =>
                    markDone(2)
                  }
                  sx={{
                    textTransform:
                      'none',

                    bgcolor:
                      '#1a237e',
                  }}
                >
                  Done
                </Button>

              </Box>

            </Box>
          )}


          {/* ==================================================
              STEP 4
              ================================================== */}

          {step === 3 && (
            <Box>

              <Typography
                variant="subtitle1"
                fontWeight={600}
                gutterBottom
              >
                {STEPS[3].title}
              </Typography>

              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mb: 2,
                }}
              >
                {STEPS[3].desc}
              </Typography>

              <TextField
                fullWidth
                size="small"
                label="Project ID"
                placeholder="my-project-12345"
                value={projectId}
                onChange={(e) => {
                  const v =
                    e.target.value;

                  setProjectId(v);

                  if (!v) {
                    setPreview({
                      show: false,
                      ok: false,
                      msg: '',
                    });
                  }

                  else if (
                    validateProjectId(
                      v
                    )
                  ) {
                    setPreview({
                      show: true,
                      ok: true,
                      msg: 'Valid format.',
                    });
                  }

                  else {
                    setPreview({
                      show: true,
                      ok: false,
                      msg:
                        'Invalid. Use lowercase, numbers, dashes. 6-30 chars.',
                    });
                  }
                }}
                InputProps={{
                  sx: {
                    fontFamily:
                      'monospace',
                  },
                }}
                sx={{
                  mb: 2,
                }}
              />

              {preview.show && (
                <Alert
                  severity={
                    preview.ok
                      ? 'success'
                      : 'error'
                  }
                  sx={{
                    mb: 2,
                  }}
                >
                  {preview.msg}
                </Alert>
              )}

              <Button
                variant="contained"
                onClick={() =>
                  markDone(3)
                }
                disabled={
                  !validateProjectId(
                    projectId
                  ) || saving
                }
                sx={{
                  textTransform:
                    'none',

                  bgcolor:
                    '#1a237e',
                }}
              >
                {saving
                  ? 'Saving...'
                  : 'Save & Continue'}
              </Button>

            </Box>
          )}


          {/* ==================================================
              STEP 5 — CONNECT GEE
              ================================================== */}

          {step === 4 && (
            <Box
              sx={{
                textAlign: 'center',
              }}
            >

              <Typography
                variant="subtitle1"
                fontWeight={600}
                gutterBottom
              >
                {STEPS[4].title}
              </Typography>

              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mb: 2,
                }}
              >
                {STEPS[4].desc}
              </Typography>


              {/* ==============================================
                  EXISTING GEE ERROR
                  ============================================== */}

              {state?.auth?.geeError && (
                <Alert
                  severity="error"
                  sx={{
                    mb: 2,
                  }}
                >
                  {state.auth.geeError}
                </Alert>
              )}


              {/* ==============================================
                  GOOGLE CONNECT BUTTON
                  ============================================== */}

              <Button
                variant="contained"
                size="large"
                startIcon={
                  <Google />
                }
                onClick={
                  handleConnectGEE
                }
                disabled={
                  saving ||
                  skippingGEE
                }
                sx={{
                  textTransform:
                    'none',

                  fontWeight: 700,

                  px: 5,

                  py: 1.8,

                  fontSize: 16,

                  bgcolor:
                    '#4285F4',

                  '&:hover': {
                    bgcolor:
                      '#3367D6',
                  },

                  borderRadius: 3,
                }}
              >
                {saving
                  ? 'Connecting...'
                  : 'Connect Google Earth Engine'}
              </Button>


              {/* ==============================================
                  MANUAL TOKEN DIVIDER
                  ============================================== */}

              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mt: 2,
                  mb: 2,
                }}
              >
                — OR paste token manually —
              </Typography>


              {/* ==============================================
                  ERROR
                  ============================================== */}

              {error && (
                <Alert
                  severity="error"
                  sx={{
                    mb: 1,
                  }}
                >
                  {error}
                </Alert>
              )}


              {/* ==============================================
                  PROJECT ID (editable on Step 5 too)
                  ============================================== */}

              <TextField
                fullWidth
                size="small"
                label="Google Cloud Project ID (from Step 4)"
                placeholder="my-project-12345"
                value={projectId}
                onChange={(e) =>
                  setProjectId(
                    e.target.value.trim()
                  )
                }
                sx={{
                  mb: 1,
                  mt: 1,
                  textAlign: 'left',
                }}
                InputProps={{
                  sx: {
                    fontFamily:
                      'monospace',

                    fontSize: 12,
                  },
                }}
                helperText={
                  projectId && !validateProjectId(projectId)
                    ? 'Invalid format: lowercase, 6-30 chars.'
                    : 'Must match a project with Earth Engine API enabled.'
                }
                error={Boolean(projectId && !validateProjectId(projectId))}
              />

              {/* ==============================================
                  MANUAL TOKEN
                  ============================================== */}

              <TextField
                fullWidth
                size="small"
                label="GEE Access Token (ya29.*)"
                placeholder="ya29.a0AfH6..."
                value={geeToken}
                onChange={(e) =>
                  setGeeToken(
                    e.target.value.trim()
                  )
                }
                sx={{
                  mb: 1,
                }}
                InputProps={{
                  sx: {
                    fontFamily:
                      'monospace',

                    fontSize: 12,
                  },
                }}
                helperText={
                  geeToken && !(geeToken.startsWith('ya29.') && geeToken.length > 30)
                    ? `This (${geeToken.length} chars) is not a Google token. Delete it and use the blue button or paste a ya29.* token.`
                    : ''
                }
                error={Boolean(geeToken && !(geeToken.startsWith('ya29.') && geeToken.length > 30))}
              />


              {/* ==============================================
                  MANUAL TOKEN BUTTON
                  ============================================== */}

              <Button
                variant="contained"
                size="small"
                onClick={
                  handleManualToken
                }
                disabled={
                  saving ||
                  skippingGEE
                }
                sx={{
                  textTransform:
                    'none',

                  bgcolor:
                    '#1a237e',
                }}
              >
                {saving
                  ? 'Saving...'
                  : 'Save Token & Enter'}
              </Button>


              <Typography
                variant="caption"
                color="text.secondary"
                sx={{
                  mt: 1,
                  display: 'block',
                  textAlign: 'left',
                }}
              >
                Recommended: blue button above (gets refresh token, lasts months).
                Manual fallback: OAuth 2.0 Playground → select scopes
                https://www.googleapis.com/auth/earthengine + cloud-platform →
                Authorize → copy <b>Access token</b> (ya29.*, ~1h expiry). Do NOT paste
                auth codes, session ids, or 40-char hex strings.
              </Typography>


              {/* ==============================================
                  SKIP GEE
                  ============================================== */}

              <Box
                sx={{
                  mt: 3,
                  pt: 2,
                  borderTop:
                    '1px solid #eeeeee',
                }}
              >

                <Button
                  variant="text"
                  onClick={
                    handleSkipGEE
                  }
                  disabled={
                    saving ||
                    skippingGEE
                  }
                  sx={{
                    textTransform:
                      'none',

                    color:
                      '#666',

                    fontWeight: 500,

                    '&:hover': {
                      backgroundColor:
                        'transparent',

                      color:
                        '#1a237e',
                    },
                  }}
                >
                  {skippingGEE
                    ? 'Continuing...'
                    : 'Skip for now'}
                </Button>

                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{
                    display:
                      'block',

                    mt: 0.5,
                  }}
                >
                  You can connect
                  Google Earth Engine
                  later.
                </Typography>

              </Box>

            </Box>
          )}

        </Paper>

      </Container>

    </Box>
  );
}

export default SetupWizard;