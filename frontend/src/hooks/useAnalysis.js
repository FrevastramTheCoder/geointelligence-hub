import { useState, useCallback, useRef } from 'react';
import { useApp } from '../context/AppContext';
import { generateId } from '../utils/fileUtils';
import { runAnalysis } from '../services/geeService';

// In-flight dedupe: identical concurrent requests share one GEE call
// (avoids "Too Many Requests" / concurrency-limit errors on double sends).
const IN_FLIGHT = new Map();
function requestKey(type, geometry, extra) {
  try {
    const g = JSON.stringify(geometry)?.slice(0, 400) || '';
    const e = JSON.stringify({ ...extra, projectId: extra.projectId || '' });
    return `${type}|${g}|${e}`;
  } catch {
    return `${type}|${Date.now()}`;
  }
}

export function useAnalysis() {
  const { dispatch, state } = useApp();
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState('');
  const stateRef = useRef(state);
  stateRef.current = state;

  const run = useCallback(async (analysisType, geometry, extra = {}) => {
    const auth = stateRef.current.auth;
    if (!auth.geeConnected) {
      const message = auth.geeError || 'Google Earth Engine is not connected. Connect your Google account to continue.';
      const blocked = new Error(message);
      // Expired tokens keep their identity so the UI can offer
      // one-click "Update token" instead of the full wizard.
      blocked.code = /expired|revoked/i.test(message) ? 'GEE_AUTH_EXPIRED' : 'GEE_AUTH_REQUIRED';
      dispatch({ type: 'SET_ERROR', payload: message });
      throw blocked;
    }
    const key = requestKey(analysisType, geometry, extra);
    if (IN_FLIGHT.has(key)) return IN_FLIGHT.get(key);
    setRunning(true);
    dispatch({ type: 'SET_LOADING', payload: true });
    setProgress('Running analysis via GEE Bridge...');
    const p = (async () => {
      const result = await runAnalysis(analysisType, geometry, extra);

      if (result.error) throw new Error(result.error);

      dispatch({ type: 'SET_RESULTS', payload: result });
      dispatch({ type: 'ADD_ANALYSIS', payload: { type: analysisType, timestamp: Date.now(), ...result } });

      // Add tile layer to map (single layer per result — no duplicate tiles)
      const tileUrl = result.tileUrl || result.layer?.tile_url;
      if (tileUrl) {
        dispatch({
          type: 'ADD_LAYER',
          payload: {
            id: generateId(),
            name: result.label || result.layer?.name || analysisType,
            type: 'image',
            url: tileUrl,
            visible: true,
            createdAt: Date.now(),
          },
        });
      }
      if (result.uncertaintyTileUrl) {
        dispatch({
          type: 'ADD_LAYER',
          payload: {
            id: generateId(), name: `${result.label || 'Classification'} — uncertainty`,
            type: 'image', url: result.uncertaintyTileUrl, visible: true,
            createdAt: Date.now(),
          },
        });
      }

      return result;
      })();
    try {
      return await p;
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err.message });
      throw err;
    } finally {
      IN_FLIGHT.delete(key);
      setRunning(false);
      setProgress('');
      dispatch({ type: 'SET_LOADING', payload: false });
    }
  }, [dispatch]);

  return { running, progress, run };
}
