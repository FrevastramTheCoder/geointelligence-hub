import { createContext, useContext, useReducer, useCallback, useEffect, useState, useRef } from 'react';
import {
  checkSession, isLoggedIn, handleGoogleRedirect, handleGoogleCodeRedirect,
  handleGEECallback, loginWithGoogle, loginWithGoogleCode, getStoredUser,
  logout as revokeSession, saveWorkspace, loadWorkspace,
} from '../services/authService';

// Google code-callback states: IDLE (no callback) -> CALLBACK (exchanging)
// -> AUTHENTICATED | FAILED. Single-processing is enforced by
// handleGoogleCodeRedirect itself (it consumes state, cleans the URL and
// marks the code done), so this stays correct under React StrictMode
// double-effects and never auto-restarts OAuth.
const GOOGLE_REDIRECT_URI = window.location.origin + '/';

function rememberGoogleError(msg) {
  try {
    sessionStorage.setItem('google_auth_error', msg);
  } catch { /* ignore */ }
}

const AppContext = createContext(null);

const initialState = {
  layers: [], activeLayer: null, aois: [], analyses: [],
  results: null, loading: false, error: null, basemap: 'osm',
  projects: [], activeProject: null,
  // Universal AOI: designated boundary layer + explicitly selected feature.
  aoiLayerId: null, selectedFeature: null,
  coordinates: { lat: -6.7736, lng: 39.2230, zoom: 15 },
  auth: {
    loggedIn: false, verified: false, user: null, geeConnected: false,
    oauthConnected: false, eeAuthenticated: false, earthEngineAvailable: false,
    analysisAvailable: false, geeError: null,
    projectId: null, setupStep: 0, geeSkipped: false,
  },
};

function isSkippedLocally() {
  try {
    return localStorage.getItem('gee_skipped') === 'true';
  } catch {
    return false;
  }
}

// Onboarding is complete when the backend setup_step reached 5
// (connected OR explicitly skipped). Skipped users can use the map;
// analysis still requires GEE (enforced in useAnalysis).
function canEnterDashboard(session, opts = {}) {
  if (!session) return false;
  if (session.geeConnected) return true;
  if (opts.geeSkipped) return true;
  if (session.user?.geeSkipped) return true;
  if (isSkippedLocally()) return true;
  const step = session.setupStep ?? session.setup_step ?? session.user?.setup_step ?? 0;
  if (Number(step) >= 5) return true;
  return false;
}

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_AUTH': return { ...state, auth: { ...state.auth, ...action.payload } };
    case 'RESET_AUTH': return { ...state, auth: { ...initialState.auth } };
    case 'RESTORE_WORKSPACE': {
      const ws = action.payload || {};
      return {
        ...state,
        layers: Array.isArray(ws.layers) ? ws.layers : state.layers,
        aois: Array.isArray(ws.aois) ? ws.aois : state.aois,
        aoiLayerId: ws.aoiLayerId ?? state.aoiLayerId,
        selectedFeature: ws.selectedFeature ?? state.selectedFeature,
        coordinates: ws.coordinates || state.coordinates,
        basemap: ws.basemap || state.basemap,
      };
    }
    case 'SET_BASEMAP': return { ...state, basemap: action.payload };
    case 'SET_COORDINATES': return { ...state, coordinates: action.payload };
    case 'ADD_LAYER': return { ...state, layers: [...state.layers, action.payload] };
    case 'REMOVE_LAYER': return { ...state, layers: state.layers.filter(l => l.id !== action.payload) };
    case 'TOGGLE_LAYER': return { ...state, layers: state.layers.map(l => l.id === action.payload ? { ...l, visible: !l.visible } : l) };
    case 'ADD_ANALYSIS': return { ...state, analyses: [...state.analyses, action.payload] };
    case 'SET_RESULTS': return { ...state, results: action.payload };
    case 'CLEAR_RESULTS': return { ...state, results: null };
    case 'SET_LOADING': return { ...state, loading: action.payload };
    case 'SET_ERROR': return { ...state, error: action.payload };
    case 'SET_ACTIVE_LAYER': return { ...state, activeLayer: action.payload };
    case 'SET_ACTIVE_PROJECT': return { ...state, activeProject: action.payload };
    case 'SET_ACTIVE_AOI': return { ...state, aoiLayerId: action.payload, selectedFeature: null };
    case 'SET_SELECTED_FEATURE': return { ...state, selectedFeature: action.payload };
    case 'SET_PROJECTS': return { ...state, projects: action.payload };
    case 'ADD_AOI': return { ...state, aois: [...state.aois, action.payload] };
    case 'REMOVE_AOI': return { ...state, aois: state.aois.filter(a => a.id !== action.payload) };
    case 'RENAME_AOI': return {
      ...state,
      aois: state.aois.map(a => a.id === action.payload.id ? { ...a, name: action.payload.name } : a),
    };
    default: return state;
  }
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  const [page, setPage] = useState('loading');
  // Standalone token-update dialog (no wizard required).
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  // Workspace restore runs once per email — never overwrites live drawing.
  const restoredEmailRef = useRef(null);
  const addLayer = useCallback((l) => dispatch({ type: 'ADD_LAYER', payload: l }), []);
  const removeLayer = useCallback((id) => dispatch({ type: 'REMOVE_LAYER', payload: id }), []);
  const toggleLayer = useCallback((id) => dispatch({ type: 'TOGGLE_LAYER', payload: id }), []);

  const applySession = useCallback((session) => {
    const setupStep = Number(
      session.setupStep ?? session.setup_step ?? session.user?.setup_step ?? session.user?.setupStep ?? 0
    ) || 0;
    const geeSkipped = Boolean(
      session.user?.geeSkipped || session.geeSkipped || isSkippedLocally()
    );
    const email = (session.email || '').toLowerCase();
    dispatch({
      type: 'SET_AUTH',
      payload: {
        loggedIn: true,
        verified: session.verified,
        user: { email: session.email, name: session.user?.name ?? session.name },
        geeConnected: !!session.geeConnected,
        oauthConnected: !!session.oauthConnected,
        eeAuthenticated: !!session.eeAuthenticated,
        earthEngineAvailable: !!session.earthEngineAvailable,
        analysisAvailable: !!session.analysisAvailable,
        geeError: session.geeError || session.error || null,
        projectId: session.projectId || null,
        setupStep,
        geeSkipped,
      },
    });
    // Restore this user's saved workspace (layers/AOIs survive logout).
    // Once per email so live drawing is never clobbered.
    if (email && restoredEmailRef.current !== email) {
      restoredEmailRef.current = email;
      const ws = loadWorkspace(email);
      dispatch({
        type: 'RESTORE_WORKSPACE',
        payload: ws || { layers: [], aois: [], aoiLayerId: null, selectedFeature: null },
      });
    }
  }, []);

  // Continuously persist workspace per user — logout/reload forgets nothing.
  const authEmail = (state.auth.user?.email || '').toLowerCase();
  useEffect(() => {
    if (!state.auth.loggedIn || !authEmail) return;
    saveWorkspace(authEmail, {
      layers: state.layers,
      aois: state.aois,
      aoiLayerId: state.aoiLayerId,
      selectedFeature: state.selectedFeature,
      coordinates: state.coordinates,
      basemap: state.basemap,
    });
  }, [state.auth.loggedIn, authEmail, state.layers, state.aois,
    state.aoiLayerId, state.selectedFeature, state.coordinates, state.basemap]);

  const handleLogout = useCallback(async () => {
    await revokeSession();
    restoredEmailRef.current = null;
    dispatch({ type: 'RESET_AUTH' });
    setPage('welcome');
  }, []);

  useEffect(() => {
    (async () => {
      const geeCallback = handleGEECallback();
      if (geeCallback) {
        const session = await checkSession();
        if (!session.valid) { setPage('welcome'); return; }
        applySession({
          ...session,
          geeError: geeCallback.success ? null : (
            geeCallback.reason === 'authorization'
              ? 'Google authorization failed.'
              : 'Google account connected, but Earth Engine authentication failed.'
          ),
        });
        setPage(canEnterDashboard(session) ? 'dashboard' : 'wizard');
        return;
      }

      // Primary: authorization-code callback (?code=…&state=…).
      // handleGoogleCodeRedirect single-consumes (state + URL + done-marker),
      // so concurrent/duplicate effect runs cannot double-process or loop.
      const codeRedirect = handleGoogleCodeRedirect();
      if (codeRedirect && !codeRedirect.duplicate) {
        if (codeRedirect.error) {
          rememberGoogleError(codeRedirect.error);
          setPage('welcome');
          return;
        }
        try {
          const result = await loginWithGoogleCode(codeRedirect.code, GOOGLE_REDIRECT_URI);
          const session = {
            valid: true, email: result.email, user: result,
            verified: result.verified, geeConnected: result.geeConnected,
            oauthConnected: result.oauthConnected, eeAuthenticated: result.eeAuthenticated,
            earthEngineAvailable: result.earthEngineAvailable,
            analysisAvailable: result.analysisAvailable,
            projectId: result.projectId,
            setupStep: result.setupStep ?? result.setup_step ?? 0,
          };
          applySession(session);
          setPage(canEnterDashboard(session) ? 'dashboard' : 'wizard');
        } catch (e) {
          console.error('[Auth] Google login failed:', e);
          rememberGoogleError(e.message || 'Google sign-in failed. Please try again.');
          setPage('welcome');
        }
        return;
      }

      // Legacy: implicit hash callback (#access_token=…) — fallback only.
      const redirect = handleGoogleRedirect();
      if (redirect) {
        try {
          const result = await loginWithGoogle(redirect.token);
          const session = {
            valid: true, email: result.email, user: result,
            verified: result.verified, geeConnected: result.geeConnected,
            oauthConnected: result.oauthConnected, eeAuthenticated: result.eeAuthenticated,
            earthEngineAvailable: result.earthEngineAvailable,
            analysisAvailable: result.analysisAvailable,
            projectId: result.projectId,
            setupStep: result.setupStep ?? result.setup_step ?? 0,
          };
          applySession(session);
          setPage(canEnterDashboard(session) ? 'dashboard' : 'wizard');
        } catch (e) {
          console.error('[Auth] Google login failed:', e);
          setPage('welcome');
        }
        return;
      }

      if (!isLoggedIn()) { setPage('welcome'); return; }
      const session = await checkSession();
      if (!session.valid) { setPage('welcome'); return; }
      applySession(session);
      setPage(canEnterDashboard(session) ? 'dashboard' : 'wizard');
    })();
  }, [applySession]);

  const handleLoginComplete = (result) => {
    const email = result.email || '';
    const session = { ...result, valid: true, email, user: result, geeConnected: !!result.geeConnected };
    applySession(session);
    setPage(canEnterDashboard(session) ? 'dashboard' : 'wizard');
  };

  const handleWizardComplete = async (opts = {}) => {
    // SetupWizard calls onComplete({ geeSkipped: true }) when skipping.
    if (opts && opts.geeSkipped) {
      setPage('dashboard');
      return;
    }
    const session = await checkSession();
    if (!session.valid) { setPage('welcome'); return; }
    applySession(session);
    setPage(canEnterDashboard(session, opts) ? 'dashboard' : 'wizard');
  };

  return (
    <AppContext.Provider value={{
      state, dispatch, addLayer, removeLayer, toggleLayer, page,
      handleLoginComplete, handleWizardComplete, handleLogout,
      tokenDialogOpen, setTokenDialogOpen,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export const useApp = () => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
};
