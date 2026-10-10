import { useState, useEffect, useCallback } from 'react';
import { checkSession, getGEEStatus } from '../services/authService';
import { useApp } from '../context/AppContext';

// Status dot in the header. Uses the FAST cached status (checkSession ->
// /api/session, no live Earth Engine probe) so mounting the app can never
// wedge the backend behind a slow EE request. Live verification (real EE
// probe) only runs on explicit user action via reverify().
export function useGEE() {
  const { state } = useApp();
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const applyStatus = useCallback((status) => {
    if (!status || status.valid === false) {
      setError('Not logged in.');
      setLoading(false);
      return;
    }
    if (!status.geeConnected) {
      setError(status.geeError || status.error || 'Google Earth Engine is not connected. Connect your Google account to continue.');
    } else {
      setReady(true);
      setError(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    checkSession()
      .then((session) => { if (!cancelled) applyStatus(session); })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [applyStatus, state.auth.geeConnected, state.auth.geeError]);

  // Explicit live re-verification (EE probe). Call from a Refresh button only.
  const reverify = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const status = await getGEEStatus();
      if (!status.geeConnected) {
        setReady(false);
        setError(status.error || 'Google Earth Engine is not connected. Connect your Google account to continue.');
      } else {
        setReady(true);
        setError(null);
      }
      return status;
    } catch (e) {
      setReady(false);
      setError(e.message);
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  return { ready, error, loading, reverify };
}
