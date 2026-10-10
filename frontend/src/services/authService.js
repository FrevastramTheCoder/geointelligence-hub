import { API, TOKEN_KEY, USER_KEY } from '../config/api';

const GOOGLE_CLIENT_ID =
  import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

/* ============================================================
   GOOGLE OAUTH — authorization CODE flow (primary).
   Google returns ?code=...&state=... in the QUERY string.
   Single-consume + CSRF state + URL cleanup: safe under
   React StrictMode double-effects, never loops.
   ============================================================ */

const GOOGLE_STATE_KEY = 'google_oauth_state';
const GOOGLE_CODE_DONE_KEY = 'google_oauth_code_done';

export function newGoogleState() {
  const arr = new Uint8Array(16);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('');
}

function cleanQuery() {
  window.history.replaceState({}, document.title, window.location.pathname);
}

export function handleGoogleCodeRedirect() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const error = params.get('error');

  if (!code && !error) return null;

  const state = params.get('state');
  const expected = (() => {
    try {
      return sessionStorage.getItem(GOOGLE_STATE_KEY);
    } catch {
      return null;
    }
  })();

  // Consume immediately: a second effect run / reload must not reprocess.
  try {
    sessionStorage.removeItem(GOOGLE_STATE_KEY);
  } catch { /* ignore */ }
  cleanQuery();

  if (error) {
    return { error: params.get('error_description') || 'Google sign-in was cancelled.' };
  }
  if (!code) return null;
  if (!state || !expected || state !== expected) {
    return { error: 'Google sign-in state mismatch. Please click "Continue with Google" again.' };
  }
  try {
    if (sessionStorage.getItem(GOOGLE_CODE_DONE_KEY) === code) return { duplicate: true };
    sessionStorage.setItem(GOOGLE_CODE_DONE_KEY, code);
  } catch { /* ignore */ }
  return { code };
}

export async function loginWithGoogleCode(code, redirectUri) {
  const res = await fetch(API.AUTH.GOOGLE_CODE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, redirect_uri: redirectUri }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 503) {
      throw new Error(
        'Google login is not configured on the server (missing GOOGLE_CLIENT_SECRET in backend/.env). Add the secret from Google Cloud Console > Credentials, restart the backend, then try again.'
      );
    }
    throw new Error(data.error || 'Login failed');
  }
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.setItem(USER_KEY, JSON.stringify(data));
  afterAuth(data);
  return data;
}

/* ============================================================
   GOOGLE REDIRECT (legacy implicit hash flow — fallback only)
   ============================================================ */

export function handleGoogleRedirect() {
  const hash = window.location.hash.substring(1);

  if (!hash) return null;

  const params = new URLSearchParams(hash);

  if (params.has('error')) {
    window.location.hash = '';
    return null;
  }

  const tok = params.get('access_token');
  const scope = params.get('scope') || '';

  if (!tok) return null;

  window.location.hash = '';

  if (scope.includes('earthengine')) {
    return {
      type: 'gee',
      token: tok,
    };
  }

  return {
    type: 'google',
    token: tok,
  };
}


/* ============================================================
   GEE CALLBACK
   ============================================================ */

export function handleGEECallback() {
  const params = new URLSearchParams(
    window.location.search
  );

  const result = params.get('gee_oauth');

  if (!result) return null;

  window.history.replaceState(
    {},
    document.title,
    window.location.pathname
  );

  return {
    success: result === 'success',
    reason: params.get('reason') || null,
  };
}


/* ============================================================
   GOOGLE USER PROFILE
   ============================================================ */

export async function fetchGoogleUser(token) {
  const res = await fetch(
    'https://www.googleapis.com/oauth2/v3/userinfo',
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    }
  );

  if (!res.ok) {
    throw new Error('Failed to get profile');
  }

  return res.json();
}


/* ============================================================
   GOOGLE LOGIN
   ============================================================ */

export async function loginWithGoogle(accessToken) {
  const res = await fetch(
    API.AUTH.GOOGLE,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        access_token: accessToken,
      }),
    }
  );

  const data = await res.json();

  if (!res.ok) {
    throw new Error(
      data.error || 'Login failed'
    );
  }

  localStorage.setItem(
    TOKEN_KEY,
    data.token
  );

  localStorage.setItem(
    USER_KEY,
    JSON.stringify(data)
  );

  afterAuth(data);

  return data;
}


/* ============================================================
   EMAIL LOGIN
   ============================================================ */

export async function loginWithEmail(
  email,
  password
) {
  const res = await fetch(
    API.AUTH.LOGIN,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email,
        password,
      }),
    }
  );

  const data = await res.json();

  if (!res.ok) {
    throw new Error(
      data.error || 'Login failed'
    );
  }

  localStorage.setItem(
    TOKEN_KEY,
    data.token
  );

  localStorage.setItem(
    USER_KEY,
    JSON.stringify(data)
  );

  afterAuth(data);

  return data;
}


/* ============================================================
   REGISTER
   ============================================================ */

export async function registerWithEmail(
  email,
  password,
  name
) {
  const res = await fetch(
    API.AUTH.REGISTER,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email,
        password,
        name,
      }),
    }
  );

  const data = await res.json();

  if (!res.ok) {
    throw new Error(
      data.error || 'Registration failed'
    );
  }

  localStorage.setItem(
    TOKEN_KEY,
    data.token
  );

  localStorage.setItem(
    USER_KEY,
    JSON.stringify(data)
  );

  afterAuth(data);

  return data;
}


/* ============================================================
   CONNECT GEE WITH ACCESS TOKEN
   ============================================================ */

export async function connectGEE(
  accessToken,
  projectId = ''
) {
  const token = getSessionToken();

  if (!token) {
    throw new Error('Not logged in');
  }

  const finalProjectId =
    projectId ||
    localStorage.getItem(
      'gee_pending_project'
    ) ||
    '';

  const res = await fetch(
    API.GEE.CONNECT,
    {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        access_token: accessToken,
        project_id: finalProjectId,
      }),
    }
  );

  const data = await res.json();

  if (!res.ok || data.error) {
    throw new Error(
      data.error ||
      'GEE connection failed'
    );
  }

  localStorage.removeItem(
    'gee_pending_project'
  );

  localStorage.removeItem(
    'gee_skipped'
  );

  try {
    const connEmail = ((getStoredUser() || {}).email || '').toLowerCase();
    if (connEmail) localStorage.removeItem(skipKey(connEmail));
  } catch { /* ignore */ }

  return data;
}


/* ============================================================
   CHECK SESSION
   ============================================================ */

export async function checkSession() {
  const token = getSessionToken();

  if (!token) {
    return {
      valid: false,
    };
  }

  try {
    const res = await fetch(
      API.AUTH.ME,
      {
        headers: getAuthHeaders(),
      }
    );

    if (!res.ok) {
      return {
        valid: false,
      };
    }

    const data = await res.json();

    if (!data.valid) {
      return {
        valid: false,
      };
    }

    const user = {
      email: data.email,

      setup_step:
        data.setupStep,

      verified:
        data.verified,

      geeConnected:
        data.geeConnected,

      oauthConnected:
        data.oauthConnected,

      eeAuthenticated:
        data.eeAuthenticated,

      earthEngineAvailable:
        data.earthEngineAvailable,

      analysisAvailable:
        data.analysisAvailable,

      geeError:
        data.geeError || data.error || null,

      projectId:
        data.projectId || null,

      name:
        data.name,

      geeSkipped:
        localStorage.getItem(
          'gee_skipped'
        ) === 'true',
    };

    localStorage.setItem(
      USER_KEY,
      JSON.stringify(user)
    );

    return {
      valid: true,

      email:
        data.email,

      verified:
        data.verified,

      geeConnected:
        data.geeConnected,

      oauthConnected:
        data.oauthConnected,

      eeAuthenticated:
        data.eeAuthenticated,

      earthEngineAvailable:
        data.earthEngineAvailable,

      analysisAvailable:
        data.analysisAvailable,

      geeError:
        data.geeError || data.error || null,

      projectId:
        data.projectId || null,

      setupStep:
        data.setupStep || 0,

      user,
    };

  } catch {
    return {
      valid: false,
    };
  }
}


/* ============================================================
   UPDATE SETUP STEP
   ============================================================ */

export async function updateSetupStep(step) {
  const res = await fetch(
    API.AUTH.SETUP,
    {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        step,
      }),
    }
  );

  if (!res.ok) {
    throw new Error(
      'Failed to update setup'
    );
  }

  const data = await res.json();

  if (data.error) {
    throw new Error(data.error);
  }

  const user =
    getStoredUser() || {};

  user.setup_step =
    data.setupStep;

  user.verified =
    data.verified;

  localStorage.setItem(
    USER_KEY,
    JSON.stringify(user)
  );

  return data;
}


/* ============================================================
   VERIFY GEE
   ============================================================ */

export async function verifyGEE() {
  const res = await fetch(
    API.GEE.STATUS,
    {
      headers: getAuthHeaders(),
    }
  );

  const data = await res.json();

  if (!res.ok) {
    throw new Error(
      data.error ||
      'Earth Engine status unavailable'
    );
  }

  return data;
}


/* ============================================================
   GET GEE STATUS
   ============================================================ */

export async function getGEEStatus() {
  return verifyGEE();
}


/* ============================================================
   LOGOUT — soft logout that NEVER forgets user information.
   Server session is revoked, but on this device we keep:
   - per-user workspace (map layers, AOIs, position) under
     `geointel_ws_<email>` (restored on next login),
   - per-user GEE-skipped flag,
   - last email (login form prefill).
   Only the session token + transient OAuth keys are removed.
   ============================================================ */

const LAST_EMAIL_KEY = 'geointel_last_email';
const WS_PREFIX = 'geointel_ws_';
const SKIP_PREFIX = 'gee_skipped_';

export function getLastEmail() {
  try {
    return localStorage.getItem(LAST_EMAIL_KEY) || '';
  } catch {
    return '';
  }
}

function wsKey(email) {
  return WS_PREFIX + (email || '').toLowerCase();
}

function skipKey(email) {
  return SKIP_PREFIX + (email || '').toLowerCase();
}

export function saveWorkspace(email, ws) {
  if (!email) return;
  try {
    localStorage.setItem(wsKey(email), JSON.stringify(ws));
  } catch {
    // Quota exceeded (big GeoJSON): keep newest layers only, retry once.
    try {
      const slim = { ...(ws || {}) };
      if (Array.isArray(slim.layers) && slim.layers.length > 10) {
        slim.layers = slim.layers.slice(-10);
      }
      localStorage.setItem(wsKey(email), JSON.stringify(slim));
    } catch { /* last resort: keep old snapshot */ }
  }
}

export function loadWorkspace(email) {
  if (!email) return null;
  try {
    const raw = localStorage.getItem(wsKey(email));
    if (!raw) return null;
    const ws = JSON.parse(raw);
    return ws && typeof ws === 'object' ? ws : null;
  } catch {
    return null;
  }
}

// Called after every successful auth: remember who logged in and
// restore their personal GEE-skipped flag (logout namespaces it).
function afterAuth(data) {
  try {
    const email = (data?.email || '').toLowerCase();
    if (email) {
      localStorage.setItem(LAST_EMAIL_KEY, email);
      if (localStorage.getItem(skipKey(email)) === 'true') {
        localStorage.setItem('gee_skipped', 'true');
      } else if (!localStorage.getItem('gee_skipped')) {
        localStorage.removeItem('gee_skipped');
      }
    }
  } catch { /* ignore */ }
}

export async function logout() {
  const token = getSessionToken();
  const user = getStoredUser();
  const email = (user?.email || '').toLowerCase();

  if (token) {
    try {
      await fetch(
        API.LOGOUT,
        {
          method: 'POST',

          headers: {
            'Content-Type':
              'application/json',

            Authorization:
              `Bearer ${token}`,
          },
        }
      );
    } catch {
      // Ignore logout network errors
    }
  }

  try {
    // Remember who this device belongs to (login prefill).
    if (email) {
      localStorage.setItem(LAST_EMAIL_KEY, email);
      // Namespace the skipped flag so a different user on this
      // device is never marked skipped by mistake.
      if (localStorage.getItem('gee_skipped') === 'true') {
        localStorage.setItem(skipKey(email), 'true');
      }
    }
  } catch { /* ignore */ }

  localStorage.removeItem(
    TOKEN_KEY
  );

  localStorage.removeItem(
    USER_KEY
  );

  // Global skipped flag cleared; per-user copy above survives and
  // is restored by afterAuth() on next login.
  localStorage.removeItem(
    'gee_skipped'
  );

  localStorage.removeItem(
    'gee_pending_project'
  );

  // Transient OAuth handshake keys — never user data.
  localStorage.removeItem(
    'google_oauth_state'
  );

  localStorage.removeItem(
    'google_oauth_code_done'
  );

  // NOTE: no page reload here — workspace (layers/AOIs) stays in
  // memory AND in per-user storage. Caller routes to welcome.
  return email;
}


/* ============================================================
   AUTH HEADERS
   ============================================================ */

function getAuthHeaders() {
  const token =
    localStorage.getItem(
      TOKEN_KEY
    );

  return {
    'Content-Type':
      'application/json',

    Authorization:
      `Bearer ${token}`,
  };
}


/* ============================================================
   START GEE OAUTH
   ============================================================ */

export async function redirectToGEEAuth(
  projectId
) {
  const token =
    getSessionToken();

  if (!token) {
    throw new Error(
      'Not logged in'
    );
  }

  const finalProjectId =
    projectId ||
    localStorage.getItem(
      'gee_pending_project'
    ) ||
    '';

  if (!finalProjectId) {
    throw new Error(
      'Enter Project ID first'
    );
  }

  localStorage.setItem(
    'gee_pending_project',
    finalProjectId
  );

  const res = await fetch(
    API.GEE.OAUTH_START,
    {
      method: 'POST',

      headers:
        getAuthHeaders(),

      body: JSON.stringify({
        project_id:
          finalProjectId,
      }),
    }
  );

  const data =
    await res.json();

  if (!res.ok || data.error) {
    throw new Error(
      data.error ||
      'Google authorization failed.'
    );
  }

  window.location.assign(
    data.authorization_url
  );
}


/* ============================================================
   SKIP GEE
   ============================================================ */

export function skipGEE() {
  /*
   * Remember that the user skipped GEE (global + per-user copy
   * so logout/login never forgets it).
   */
  localStorage.setItem(
    'gee_skipped',
    'true'
  );
  try {
    const skipEmail = ((getStoredUser() || {}).email || getLastEmail() || '').toLowerCase();
    if (skipEmail) localStorage.setItem(skipKey(skipEmail), 'true');
  } catch { /* ignore */ }

  /*
   * Get current user.
   */
  const user =
    getStoredUser() || {};

  /*
   * IMPORTANT:
   * We do NOT mark GEE as connected.
   */
  user.geeConnected = false;

  user.oauthConnected = false;

  user.eeAuthenticated = false;

  user.earthEngineAvailable = false;

  user.analysisAvailable = false;

  user.geeSkipped = true;

  /*
   * Complete onboarding locally.
   */
  user.setup_step = 5;

  localStorage.setItem(
    USER_KEY,
    JSON.stringify(user)
  );

  /*
   * Remove unfinished project.
   */
  localStorage.removeItem(
    'gee_pending_project'
  );

  return user;
}


/* ============================================================
   SESSION TOKEN
   ============================================================ */

export function getSessionToken() {
  return localStorage.getItem(
    TOKEN_KEY
  );
}


/* ============================================================
   STORED USER
   ============================================================ */

export function getStoredUser() {
  try {
    const value =
      localStorage.getItem(
        USER_KEY
      );

    if (!value) {
      return null;
    }

    return JSON.parse(value);

  } catch {
    return null;
  }
}


/* ============================================================
   LOGIN STATUS
   ============================================================ */

export function isLoggedIn() {
  return !!localStorage.getItem(
    TOKEN_KEY
  );
}


/* ============================================================
   VERIFIED STATUS
   ============================================================ */

export function isVerified() {
  const user =
    getStoredUser() || {};

  return (
    user.setup_step ??
    user.setupStep ??
    0
  ) >= 2;
}


/* ============================================================
   GEE CONNECTED STATUS
   ============================================================ */

export function isGEEConnected() {
  return !!(
    getStoredUser()
      ?.geeConnected
  );
}


/* ============================================================
   USER EMAIL
   ============================================================ */

export function getUserEmail() {
  return (
    getStoredUser()
      ?.email || null
  );
}


/* ============================================================
   SETUP STEP
   ============================================================ */

export function getSetupStep() {
  const user =
    getStoredUser() || {};

  return (
    user.setup_step ??
    user.setupStep ??
    0
  );
}


/* ============================================================
   GEE SKIPPED STATUS
   ============================================================ */

export function isGEESkipped() {
  return (
    localStorage.getItem(
      'gee_skipped'
    ) === 'true'
  );
}