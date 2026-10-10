import { useState, useRef, useEffect } from 'react';
import {
  Box, Paper, TextField, IconButton, Typography, Chip,
  CircularProgress, Button,
} from '@mui/material';
import { Send, SmartToy, Close, Download } from '@mui/icons-material';
import { processMessage } from '../../services/aiAssistant';
import { recordCapabilityGap } from '../../services/methodologyCatalog';
import { useApp } from '../../context/AppContext';
import { useAnalysis } from '../../hooks/useAnalysis';
import { API, TOKEN_KEY } from '../../config/api';
import { computeArea } from '../../analysis/area';
import { computeDistance } from '../../analysis/distance';
import { runBufferAnalysis } from '../../analysis/buffer';
import { runIntersectionAnalysis } from '../../analysis/intersection';
import { generateId } from '../../utils/fileUtils';
import { generateGEECode } from '../../services/geeCodeGenerator';
import { getAssistantLang, setAssistantLang, tr } from '../../services/assistantLang';
import { getCurrentAOI } from '../../services/boundaryService';
import {
  requestExport, requestBoundaryExport, exportStatus, downloadHref,
  isRasterResult, isCategoricalResult, compatibleFormats,
} from '../../services/exportService';

function aoiFeature(state) {
  return getCurrentAOI(state);
}

// One result: professional GIS report (analysis/AOI/dataset/period/stats/exports).
function formatResultMessage(result, lang = 'en', ctx = {}) {
  const L = lang === 'sw' ? 'sw' : 'en';
  const T = (k, v) => tr(L, k, v);
  const name = result.label || result.layer?.name || result.analysis?.name || 'Analysis complete';
  const a = result.analysis || {};
  const lines = [name];
  const head = [];
  if (a.name) head.push(`${L === 'sw' ? 'Uchambuzi' : 'Analysis'}: ${a.name}`);
  if (a.method) head.push(`${L === 'sw' ? 'Mbinu' : 'Method'}: ${a.method}`);
  if (head.length) lines.push(head.join(' • '));
  const meta = [];
  if (ctx.aoi) meta.push(`AOI: ${ctx.aoi}`);
  if (result.metadata?.dataset) meta.push(`${L === 'sw' ? 'Data' : 'Dataset'}: ${result.metadata.dataset}`);
  const yr = result.parameters?.year ?? result.metadata?.date;
  const yr2 = result.parameters?.year2 ?? result.metadata?.year2;
  if (yr && yr2 && yr !== yr2) meta.push(`${L === 'sw' ? 'Kipindi' : 'Period'}: ${yr2} → ${yr}`);
  else if (yr) meta.push(`${L === 'sw' ? 'Mwaka' : 'Year'}: ${yr}`);
  if (result.metadata?.scale) meta.push(`${L === 'sw' ? 'Azimio' : 'Resolution'}: ${result.metadata.scale}m`);
  if (meta.length) lines.push(meta.join(' • '));
  const legend = result.legend;
  if (Array.isArray(legend) && legend.length) {
    lines.push('\n' + T('legend'));
    legend.slice(0, 12).forEach((l) => lines.push(`■ ${l.label ?? l}`));
  } else if (legend && legend.type === 'continuous') {
    lines.push(`\n${T('legend')}: continuous ${legend.min} → ${legend.max}${legend.unit ? ' ' + legend.unit : ''}`);
  }
  const stats = result.statistics || result.stats;
  if (stats) {
    lines.push('\n' + T('statistics'));
    Object.entries(stats).slice(0, 12).forEach(([k, v]) => lines.push(`${k}: ${v}`));
  }
  if (result.interpretation || result.message) lines.push(`\n${result.interpretation || result.message}`);
  const ex = compatibleFormats(result).map((f) => f.label);
  if (ex.length) lines.push(`\n${L === 'sw' ? 'Hamisha' : 'Exports'}: ${ex.join(', ')}`);
  return lines.join('\n');
}

export function AIAssistant() {
  const { state, dispatch } = useApp();
  const { run, running, progress } = useAnalysis();
  const [open, setOpen] = useState(false);
  const [lang, setLang] = useState(() => getAssistantLang());
  const L = lang === 'sw' ? 'sw' : 'en';
  const [messages, setMessages] = useState(() => [
    { role: 'assistant', text: tr(getAssistantLang(), 'welcome') }
  ]);
  const [input, setInput] = useState('');
  const [lastPlan, setLastPlan] = useState(null);
  const [llmError, setLlmError] = useState('');
  const inputRef = useRef(null);
  const chatRef = useRef(null);
  const sendingRef = useRef(false);
  // Command asked before AOI existed ("onyesha mimea" -> draw first).
  // Kept so "done"/"sawa" after drawing auto-runs it by command.
  const pendingPlanRef = useRef(null);

  const switchLang = (l) => {
    setAssistantLang(l);
    setLang(l === 'sw' ? 'sw' : 'en');
  };

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  const addMessage = (role, text, extra = {}) => {
    setMessages(prev => [...prev, { role, text, ...extra }]);
  };

  const callLLM = async (msg, history) => {
    try {
      setLlmError('');
      const res = await fetch(API.CHAT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY) || ''}`,
        },
        body: JSON.stringify({ message: msg, history: history.slice(-6) }),
      });
      const data = await res.json();
      if (data.error) {
        setLlmError(data.error);
        return null;
      }
      return data;
    } catch (e) {
      setLlmError(tr(L, 'llm_error') + e.message);
      return null;
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || running || sendingRef.current) return;
    sendingRef.current = true;
    setInput('');

    addMessage('user', text);

    try {
      // The rule-based planner handles GIS intent and analysis selection first.
      const pending = pendingPlanRef.current;
      if (pending) {
        const aoiNow = aoiFeature(state);
        const isConfirm = /^(done!?\.?|ok\.?|okay|sawa|ready|nimechora|nimeshachora|nimemaliza|nipo tayari|iko tayari|run it|run now|kimbia|endesha)$/i.test(text.trim());
        if (isConfirm && aoiNow?.geometry) {
          pendingPlanRef.current = null;
          addMessage('assistant', tr(L, 'running'));
          await executePlan(pending);
          return;
        }
        // New analysis command replaces pending (handled below).
        if (!isConfirm) pendingPlanRef.current = null;
      }
      const parsed = processMessage(text, lastPlan || pending, {
        lang: L, layerNames: state.layers.map((l) => l.name).filter(Boolean),
      });
      // Only conversational/unknown requests may consult Gemini. Registered GIS
      // methods always use deterministic planner rules and their real executors.
      let llmResult = null;
      if (['chat', 'unknown', 'empty'].includes(parsed.type)) {
        llmResult = await callLLM(text, messages);
        if (llmResult?.type === 'error') {
          addMessage('assistant', llmResult.error || 'LLM Error', { error: true });
          return;
        }
      }
      const llmLive = llmResult?.type === 'llm' ? llmResult.reply : null;

      if (parsed.type === 'knowledge') {
        if (parsed.methodologyStatus !== 'implemented') recordCapabilityGap(text, parsed.methodId);
        addMessage('assistant', parsed.reply);
        return;
      }
      if (parsed.type === 'chat' || parsed.type === 'unknown' || parsed.type === 'empty') {
        addMessage('assistant', llmLive || parsed.reply);
        return;
      }
      if (parsed.type === 'clarify') {
        addMessage('assistant', llmLive || parsed.reply, { options: parsed.options });
        return;
      }
      if (parsed.type === 'multi_step') {
        addMessage('assistant', (llmLive ? llmLive + '\n' : '') + parsed.reply);
        await executeMultiStep(parsed.steps);
        return;
      }
      if (parsed.type === 'code') {
        // Code generation — no EE run, no AOI needed.
        try {
          const code = generateGEECode({ backend: parsed.plan?.backend || parsed.analysis,
            parameters: parsed.plan?.parameters || parsed.parameters || {} });
          setLastPlan(parsed.plan || null);
          addMessage('assistant',
            (parsed.reply || 'GEE code') + '\n\n--- JavaScript (Code Editor) ---\n' +
            code.javascript.slice(0, 3500) + '\n\n' + tr(L, 'code_note'),
            { result: true, analysis: 'code' });
        } catch (e) {
          addMessage('assistant', 'Could not generate code: ' + e.message);
        }
        return;
      }
      if (parsed.type === 'export') {
        addMessage('assistant', (llmLive ? llmLive + '\n' : '') + parsed.reply);
        await executeExport(parsed);
        return;
      }
      if (parsed.type === 'zonal') {
        addMessage('assistant', (llmLive ? llmLive + '\n' : '') + parsed.reply);
        await executeZonal(parsed);
        return;
      }
      if (parsed.type === 'admin') {
        addMessage('assistant', (llmLive ? llmLive + '\n' : '') + parsed.reply);
        await executeAdmin(parsed);
        return;
      }
      if (parsed.type === 'analysis') {
        const label = parsed.plan?.backend || parsed.analysis;
        addMessage('assistant', (llmLive ? llmLive + '\n' : '') + (parsed.reply || tr(L, 'processing')), { analysis: label });
        await executePlan(parsed.plan || { intent: parsed.analysis, backend: parsed.analysis, parameters: {
          year: parsed.year || 2024, year2: parsed.year2, numClasses: parsed.numClasses || 5 } });
        return;
      }

      addMessage('assistant', llmResult?.reply || tr(L, 'unknown'));
    } finally {
      sendingRef.current = false;
    }
  };

  useEffect(() => {
    const onQuickCommand = (event) => {
      if (typeof event.detail !== 'string') return;
      setInput(event.detail);
      setOpen(true);
      setTimeout(() => inputRef.current?.focus(), 0);
    };
    window.addEventListener('geoai:quick-command', onQuickCommand);
    return () => window.removeEventListener('geoai:quick-command', onQuickCommand);
  }, []);

  // Structured plan -> existing executor (planner never touches GEE itself)
  const executePlan = async (plan) => {
    if (!plan) return;
    // Local tools (no GEE, no auth needed beyond login)
    if (plan.local) {
      await executeLocal(plan);
      return;
    }
    const backend = plan.backend || plan.intent;
    if (!backend) {
      addMessage('assistant', plan.reply || 'I need more detail to run that.');
      return;
    }
    const aoi = aoiFeature(state);
    if (!aoi?.geometry) {
      // Remember command so "done" after drawing runs it automatically.
      pendingPlanRef.current = plan;
      setLastPlan(plan);
      addMessage('assistant',
        tr(L, 'aoi_needed', { tool: backend }) + '\n' +
        (L === 'sw'
          ? 'Chora poligoni, kisha andika "done" — nitaendesha moja kwa moja.'
          : 'Draw a polygon, then type "done" — I will run it automatically.'),
        { options: L === 'sw' ? ['done', 'onyesha mimea'] : ['done', 'show vegetation'] });
      return;
    }
    const p = plan.parameters || {};
    try {
      const { wantsCode, ...planParams } = p;
      let importedClassCount = null;
      if (backend === 'landcover' || backend === 'lulc_change') {
        const sampleLayers = state.layers.filter((layer) => layer.type === 'geojson' && layer.data);
        const toCollection = (layer) => layer?.data?.type === 'FeatureCollection'
          ? layer.data : layer?.data?.type === 'Feature' ? { type: 'FeatureCollection', features: [layer.data] } : null;
        const trainingLayer = sampleLayers.find((layer) => /training|train(?:ing)?\s*samples/i.test(layer.name || ''));
        const validationLayer = sampleLayers.find((layer) => /validation|valid(?:ation)?\s*samples|test\s*samples/i.test(layer.name || ''));
        const trainingSamples = toCollection(trainingLayer);
        const validationSamples = toCollection(validationLayer);
        if (trainingSamples) {
          const props = trainingSamples.features?.find((feature) => feature.properties)?.properties || {};
          const propNames = Object.keys(props);
          const classProperty = ['class', 'class_id', 'classid', 'lc', 'label', 'landcover']
            .map((candidate) => propNames.find((key) => key.toLowerCase() === candidate))
            .find(Boolean);
          if (classProperty) {
            planParams.trainingSamples = trainingSamples;
            planParams.classProperty = classProperty;
            importedClassCount = new Set(trainingSamples.features.map((feature) => String(feature.properties?.[classProperty]))).size;
            planParams.numClasses = importedClassCount;
            delete planParams.classNames;
            if (validationSamples) planParams.validationSamples = validationSamples;
          }
        }
      }
      const result = await run(backend, aoi.geometry, {
        ...planParams,
        year: p.year ?? 2024, year2: p.year2 ?? 2020,
        source: p.source || 'sentinel2', maxCloud: p.maxCloud ?? 30,
        numClasses: importedClassCount || p.numClasses || 5,
        ...(state.activeProject?.id ? { projectId: state.activeProject.id } : {}),
      });
      setLastPlan({ intent: plan.intent, backend, parameters: p });
      pendingPlanRef.current = null;
      addMessage('assistant', formatResultMessage(result, L, { aoi: aoi.label }) + '\n\n' + tr(L, 'ask_more'), { result: true, analysis: backend });
    } catch (e) {
      addMessage('assistant', tr(L, 'err_prefix') + e.message);
    }
  };

  const executeLocal = async (plan) => {
    const aoi = aoiFeature(state);
    try {
      if (plan.local === 'area') {
        if (!aoi?.geometry) { addMessage('assistant', tr(L, 'aoi_none')); return; }
        const result = await computeArea(aoi.feature);
        dispatch({ type: 'ADD_ANALYSIS', payload: { type: 'Area', timestamp: Date.now(), ...result } });
        dispatch({ type: 'SET_RESULTS', payload: result });
        setLastPlan(plan);
        addMessage('assistant', formatResultMessage(result, L), { result: true, analysis: 'area' });
      } else if (plan.local === 'distance') {
        const geos = state.layers.filter((l) => l.type === 'geojson' && l.data);
        if (geos.length < 2) { addMessage('assistant', tr(L, 'draw_two')); return; }
        const toF = (d) => (d.type === 'Feature' ? d : { type: 'Feature', geometry: d.geometry, properties: {} });
        const result = await computeDistance(toF(geos[geos.length - 2].data), toF(geos[geos.length - 1].data));
        dispatch({ type: 'ADD_ANALYSIS', payload: { type: 'Distance', timestamp: Date.now(), ...result } });
        dispatch({ type: 'SET_RESULTS', payload: result });
        setLastPlan(plan);
        addMessage('assistant', formatResultMessage(result, L), { result: true, analysis: 'distance' });
      } else if (plan.local === 'intersection') {
        const layers = state.layers.filter((layer) => layer.type === 'geojson' && layer.data);
        const sourceName = plan.parameters?.sourceLayer;
        const targetName = plan.parameters?.targetLayer;
        const sourceLayer = sourceName
          ? layers.find((layer) => layer.name === sourceName)
          : layers.at(-2);
        const targetLayer = targetName
          ? layers.find((layer) => layer.name === targetName)
          : layers.at(-1);
        if (!sourceLayer || !targetLayer || sourceLayer.id === targetLayer.id) {
          addMessage('assistant', L === 'sw'
            ? 'Pakia GeoJSON/KML/shapefile yenye poligoni mbili tofauti. Kisha omba “intersect” au taja majina ya layers zote mbili.'
            : 'Upload two different polygon layers as GeoJSON, KML or Shapefile, then ask for “intersection” and optionally name both layers.');
          return;
        }
        addMessage('assistant', L === 'sw' ? 'Ninafanya polygon intersection…' : 'Computing polygon intersection…');
        const result = await runIntersectionAnalysis(sourceLayer.data, targetLayer.data, {
          sourceLayer: sourceLayer.name, targetLayer: targetLayer.name,
          label: `${sourceLayer.name} ∩ ${targetLayer.name}`,
        });
        if (result.geometry.features.length) {
          dispatch({ type: 'ADD_LAYER', payload: { id: generateId(), name: result.label, type: 'geojson',
            data: result.geometry, featureCount: result.geometry.features.length, visible: true, createdAt: Date.now() } });
        }
        dispatch({ type: 'ADD_ANALYSIS', payload: { type: 'Intersection', timestamp: Date.now(), ...result } });
        dispatch({ type: 'SET_RESULTS', payload: result });
        setLastPlan(plan);
        addMessage('assistant', formatResultMessage(result, L), { result: true, analysis: 'intersection' });
      } else if (plan.local === 'buffer') {
        if (!aoi?.geometry) { addMessage('assistant', tr(L, 'aoi_none')); return; }
        const radius = plan.parameters?.radius || 500;
        const result = await runBufferAnalysis(aoi.feature, radius);
        if (result.geometry) {
          dispatch({ type: 'ADD_LAYER', payload: { id: generateId(), name: result.label, type: 'geojson',
            data: result.geometry, visible: true, createdAt: Date.now() } });
        }
        dispatch({ type: 'ADD_ANALYSIS', payload: { type: 'Buffer', timestamp: Date.now(), ...result } });
        dispatch({ type: 'SET_RESULTS', payload: result });
        setLastPlan(plan);
        addMessage('assistant', formatResultMessage(result, L), { result: true, analysis: 'buffer' });
      } else if (plan.local === 'spatial_statistics') {
        const p = { ...(plan.parameters || {}) };
        const method = p.method || plan.intent;
        const pointLayers = state.layers.filter((layer) => layer.type === 'geojson' && layer.data)
          .map((layer) => ({ layer, data: layer.data?.type === 'FeatureCollection' ? layer.data
            : layer.data?.type === 'Feature' ? { type: 'FeatureCollection', features: [layer.data] } : null }))
          .filter((item) => item.data?.features?.length && item.data.features.every((f) => f.geometry?.type === 'Point'));
        const isSampling = method === 'spatial_sampling';
        if (!isSampling && !pointLayers.length) {
          addMessage('assistant', L === 'sw'
            ? 'Pakia GeoJSON ya pointi zenye sifa za namba (numeric properties), kisha taja field, kwa mfano “Global Moran field incidents k-nearest 4”.'
            : 'Upload a GeoJSON point layer with numeric properties, then name a field, for example “Global Moran field incidents k-nearest 4”.');
          return;
        }
        const selected = pointLayers.at(-1);
        const sampleFeature = selected?.data.features.find((f) => f.properties && typeof f.properties === 'object');
        const numericFields = sampleFeature ? Object.keys(sampleFeature.properties).filter((key) =>
          selected.data.features.every((f) => Number.isFinite(Number(f.properties?.[key])) && f.properties?.[key] !== null)) : [];
        if (!isSampling && !p.valueField && numericFields.length === 1) p.valueField = numericFields[0];
        if (!isSampling && !p.valueField) {
          addMessage('assistant', (L === 'sw' ? 'Taja field ya namba ya kuchanganua. Fields zilizopo: ' : 'Name the numeric field to analyze. Available fields: ')
            + (numericFields.join(', ') || 'none') + (L === 'sw' ? '. Mfano: “Global Moran field value k-nearest 4”.' : '. Example: “Global Moran field value k-nearest 4”.'));
          return;
        }
        if (method === 'spatial_regression' && !p.predictors?.length) {
          addMessage('assistant', (L === 'sw' ? 'Taja predictor field moja au zaidi tofauti na outcome field ' : 'Name one or more predictor fields that differ from outcome field ')
            + p.valueField + '.');
          return;
        }
        if (['global_moran', 'local_moran', 'getis_ord_gi_star'].includes(method) && p.k == null && p.distanceThreshold == null) {
          addMessage('assistant', L === 'sw'
            ? 'Spatial weights zinahitaji umbali au k-nearest. Taja, kwa mfano “k-nearest 4” au “threshold 500 m”.'
            : 'Specify spatial weights using k-nearest neighbours or a distance threshold, for example “k-nearest 4” or “threshold 500 m”.');
          return;
        }
        if (['kde', 'spatial_regression'].includes(method) && !(Number(p.bandwidth) > 0)) {
          addMessage('assistant', L === 'sw' ? 'Taja bandwidth chanya kwa mita.' : 'Specify a positive bandwidth in metres.');
          return;
        }
        if (method === 'kriging' && ['sill', 'range', 'nugget'].some((key) => p[key] == null)) {
          addMessage('assistant', L === 'sw'
            ? 'Kriging inahitaji variogram sill, range (m) na nugget kutoka variogram iliyofitishwa. Taja vyote wazi.'
            : 'Kriging needs explicit variogram sill, range (m), and nugget from a fitted variogram. Provide all three.');
          return;
        }
        if (aoi?.geometry) p.studyArea = { type: 'Feature', geometry: aoi.geometry, properties: {} };
        if (['spatial_sampling', 'kde', 'nearest_neighbor', 'point_pattern', 'idw', 'kriging'].includes(method) && !p.studyArea) {
          addMessage('assistant', L === 'sw' ? 'Chora au chagua polygon ya eneo la utafiti kwanza.' : 'Draw or select a polygon study area first.');
          return;
        }
        if (!isSampling) p.points = selected.data;
        p.crs = 'EPSG:4326';
        addMessage('assistant', L === 'sw' ? 'Ninaendesha spatial statistics…' : 'Computing spatial statistics…');
        const token = localStorage.getItem(TOKEN_KEY);
        const response = await fetch(API.SPATIAL_STATISTICS, {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify(p),
        });
        const result = await response.json();
        if (!response.ok || result.error) throw new Error(result.error || `Spatial statistics failed (${response.status}).`);
        if (result.geometry?.features?.length) {
          dispatch({ type: 'ADD_LAYER', payload: { id: generateId(), name: result.label, type: 'geojson', data: result.geometry,
            styleBy: result.styleBy, featureCount: result.geometry.features.length, visible: true, createdAt: Date.now() } });
        }
        dispatch({ type: 'ADD_ANALYSIS', payload: { type: result.label, timestamp: Date.now(), ...result } });
        dispatch({ type: 'SET_RESULTS', payload: result });
        setLastPlan(plan);
        addMessage('assistant', formatResultMessage(result, L), { result: true, analysis: method });
      } else if (plan.local === 'drone_analysis') {
        const p = { ...(plan.parameters || {}) };
        const method = p.method || plan.intent;
        const cloud = state.layers.filter((layer) => layer.type === 'drone-pointcloud').at(-1);
        const grids = state.layers.filter((layer) => layer.type === 'drone-grid' && layer.data);
        if (method === 'point_cloud_inspection') {
          if (!cloud) {
            addMessage('assistant', L === 'sw' ? 'Pakia XYZ point-cloud JSON kwanza.' : 'Upload an XYZ point-cloud JSON first.');
            return;
          }
          p.crs = cloud.data.crs;
          p.units = cloud.data.units;
          p.pointCloud = cloud.data.pointCloud;
        } else if (method === 'orthomosaic_analysis' || method === 'orthomosaic_ndvi') {
          const ortho = state.layers.filter((layer) => layer.type === 'drone-orthomosaic').at(-1);
          if (!ortho) {
            addMessage('assistant', L === 'sw' ? 'Pakia orthomosaic yenye red/NIR reflectance bands.' : 'Upload an orthomosaic with calibrated red/NIR reflectance bands.');
            return;
          }
          p.method = 'orthomosaic_ndvi';
          p.bands = ortho.data.bands;
        } else {
          if (!grids.length) {
            addMessage('assistant', L === 'sw' ? 'Pakia elevation-grid JSON iliyogeoreference kwanza.' : 'Upload a georeferenced elevation-grid JSON first.');
            return;
          }
          const surfaceLayer = grids.find((layer) => /dsm|surface|after|current/i.test(layer.name)) || grids.at(-1);
          const referenceLayer = grids.filter((layer) => layer.id !== surfaceLayer.id)
            .find((layer) => /dtm|reference|before|base/i.test(layer.name)) || grids.find((layer) => layer.id !== surfaceLayer.id);
          p.surface = surfaceLayer.data;
          if (referenceLayer) p.reference = referenceLayer.data;
          if (!p.mask && Array.isArray(surfaceLayer.data.mask)) p.mask = surfaceLayer.data.mask;
          if (['dsm_dtm', 'dem_difference', 'terrain_change', 'cut_fill'].includes(method) && !p.reference) {
            addMessage('assistant', L === 'sw'
              ? 'Ulinganisho huu unahitaji grid ya pili iliyolingana, yenye CRS, transform, resolution na vertical datum inayofanana.'
              : 'This comparison needs a second grid aligned in CRS, transform, resolution and vertical datum.');
            return;
          }
          if (['stockpile_volume', 'excavation_volume'].includes(method) && !p.mask) {
            addMessage('assistant', L === 'sw'
              ? 'Ongeza mask ya boolean yenye ukubwa sawa na grid ili kuweka footprint ya stockpile/excavation.'
              : 'Add a same-sized boolean mask to the surface grid JSON to define the stockpile/excavation footprint.');
            return;
          }
          if (['stockpile_volume', 'excavation_volume'].includes(method) && !p.reference && !p.basePlane) {
            addMessage('assistant', L === 'sw'
              ? 'Taja base plane ya urefu na vertical datum yake, au pakia reference surface iliyolingana.'
              : 'Specify the base-plane elevation and vertical datum, or upload an aligned reference surface.');
            return;
          }
        }
        addMessage('assistant', L === 'sw' ? 'Ninachakata data halisi za drone/mgodi…' : 'Processing the supplied drone/mine data…');
        const token = localStorage.getItem(TOKEN_KEY);
        const response = await fetch(API.DRONE_ANALYSIS, {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify(p),
        });
        const result = await response.json();
        if (!response.ok || result.error) throw new Error(result.error || `Drone analysis failed (${response.status}).`);
        if (result.geometry?.features?.length) {
          dispatch({ type: 'ADD_LAYER', payload: { id: generateId(), name: result.label, type: 'geojson', data: result.geometry,
            styleBy: result.styleBy, featureCount: result.geometry.features.length, visible: true, createdAt: Date.now() } });
        }
        dispatch({ type: 'ADD_ANALYSIS', payload: { type: result.label, timestamp: Date.now(), ...result } });
        dispatch({ type: 'SET_RESULTS', payload: result });
        setLastPlan(plan);
        addMessage('assistant', formatResultMessage(result, L), { result: true, analysis: method });
      }
    } catch (e) {
      addMessage('assistant', tr(L, 'err_prefix') + e.message);
    }
  };

  const executeMultiStep = async (steps) => {
    const done = [];
    for (const step of steps || []) {
      const aoi = aoiFeature(state);
      if (!aoi?.geometry) { addMessage('assistant', tr(L, 'aoi_none')); return; }
      if (step.local) {
        await executeLocal(step);
        done.push(step.intent);
        continue;
      }
      const p = step.parameters || {};
      try {
        const { wantsCode, ...stepParams } = p;
        const result = await run(step.backend, aoi.geometry, {
          ...stepParams,
          year: p.year ?? 2024, year2: p.year2 ?? 2020, source: p.source || 'sentinel2',
          numClasses: p.numClasses ?? 5,
          ...(state.activeProject?.id ? { projectId: state.activeProject.id } : {}),
        });
        done.push(step.intent);
        setLastPlan(step);
        addMessage('assistant', `Step ${done.length}/${steps.length} — ` + formatResultMessage(result, L, { aoi: aoi.label }), { result: true, analysis: step.backend });
      } catch (e) {
        addMessage('assistant', tr(L, 'step_failed', { i: done.length + 1, intent: step.intent, err: e.message }));
        return;
      }
    }
    if (done.length) addMessage('assistant', tr(L, 'compound_done', { list: done.join(' → ') }));
  };

  const resolveTargetFeatures = (plan) => {
    // Named boundary layer > attribute filter > current AOI.
    const target = plan?.parameters?.targetLayer;
    const filt = plan?.parameters?.filter;
    let layers = state.layers.filter((l) => l.type === 'geojson' && l.data);
    if (target) {
      const hit = layers.find((l) => (l.name || '').toLowerCase().includes(String(target).toLowerCase()));
      if (hit) layers = [hit];
    }
    let feats = [];
    let label = '';
    for (const layer of layers) {
      const all = layer.data?.type === 'FeatureCollection' ? layer.data.features || [] : [layer.data];
      let sel = all.map((f, i) => ({ f, i, layer }));
      if (filt?.value) {
        sel = sel.filter(({ f }) => {
          const props = f?.properties || {};
          const want = String(filt.value).toLowerCase();
          if (filt.field && props[filt.field] != null) {
            return String(props[filt.field]).toLowerCase().includes(want);
          }
          return Object.entries(props).some(([k, v]) =>
            (!filt.field || k.toLowerCase() === String(filt.field).toLowerCase()) &&
            String(v).toLowerCase().includes(want));
        });
      }
      if (sel.length) {
        feats = sel.map(({ f }) => f);
        label = layer.name;
        break;
      }
    }
    if (!feats.length) {
      const aoi = getCurrentAOI(state);
      if (aoi?.geometry) {
        const g = aoi.geometry;
        feats = g.type === 'FeatureCollection' ? g.features : [g.type === 'Feature' ? g : { type: 'Feature', properties: {}, geometry: g }];
        label = aoi.label;
      }
    }
    return { feats, label };
  };

  const pollRunningExport = async (taskId, tries = 12) => {
    for (let i = 0; i < tries; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      try {
        const s = await exportStatus(taskId);
        if (s.status === 'completed') {
          addMessage('assistant', tr(L, 'export_ready', { filename: s.filename || taskId, format: 'GeoTIFF' }),
            s.downloadUrl ? { download: { url: s.downloadUrl, label: 'Download GeoTIFF' } } : {});
          return;
        }
        if (s.status === 'failed' || s.status === 'cancelled') {
          addMessage('assistant', tr(L, 'err_prefix') + (s.error || s.state || 'export failed'));
          return;
        }
      } catch { return; }
    }
  };

  const postDownload = (record, fallbackLabel) => {
    const url = downloadHref(record);
    if (!url) return;
    addMessage('assistant', tr(L, 'export_ready', { filename: record.filename || fallbackLabel, format: record.format || '' }),
      { download: { url, label: `Download ${record.filename || fallbackLabel}` } });
  };

  const executeExport = async (parsed) => {
    const kind = parsed.exportKind || parsed.plan?.exportKind || 'current';
    const spec = parsed.plan?.parameters || parsed.parameters || {};
    try {
      if (kind === 'boundary') {
        const { feats, label } = resolveTargetFeatures(parsed.plan || parsed);
        if (!feats.length) { addMessage('assistant', tr(L, 'export_boundary_none')); return; }
        const fmt = spec.format || 'geojson';
        const rec = await requestBoundaryExport({
          features: { type: 'FeatureCollection', features: feats.slice(0, 2000) },
          format: fmt, filename: (label || 'boundary').slice(0, 40),
        });
        postDownload(rec, label || 'boundary');
        return;
      }
      if (kind === 'qgis') {
        const res = state.results;
        if (!res || !isRasterResult(res)) {
          addMessage('assistant', tr(L, 'export_none'), {
            options: L === 'sw'
              ? ['onyesha mimea', 'ainisha ardhi katika madarasa 5']
              : ['show vegetation', 'classify land into 5 classes'],
          });
          return;
        }
        const fmts = compatibleFormats(res).map((f) => f.label).join(', ');
        addMessage('assistant',
          (L === 'sw' ? `Kwa QGIS tumia: ${fmts}.` : `For QGIS use: ${fmts}.`) +
          (L === 'sw' ? ' Ninahamisha GeoTIFF + CSV sasa.' : ' Exporting GeoTIFF + CSV now.'));
        const aoi = getCurrentAOI(state);
        for (const fmt of ['geotiff', 'csv']) {
          try {
            const rec = await requestExport({
              resultId: res.resultId || undefined,
              analysis: res.analysis?.id || res.type?.toLowerCase(),
              geometry: aoi?.geometry || undefined,
              format: fmt, filename: (res.label || res.type || 'result').slice(0, 40),
            });
            if (rec.status === 'running' && rec.eeTaskId) {
              addMessage('assistant', tr(L, 'export_running'));
              pollRunningExport(rec.eeTaskId);
            } else {
              postDownload(rec, fmt);
            }
          } catch (e) {
            addMessage('assistant', tr(L, 'err_prefix') + e.message);
          }
        }
        return;
      }
      // current / geotiff / shp / geojson / kml / kmz / csv / png
      const res = state.results;
      if (!res) { addMessage('assistant', tr(L, 'export_none')); return; }
      if (!isRasterResult(res) && !['csv'].includes(spec.format || kind)) {
        // Local measurement results: stats CSV via browser (honest, no EE).
        const { exportCSV } = await import('../../utils/fileUtils');
        exportCSV(res.stats || {}, res.type || 'result');
        addMessage('assistant', tr(L, 'export_ready', { filename: `${res.type || 'result'}.csv`, format: 'csv' }));
        return;
      }
      let fmt = spec.format || (kind === 'current' ? 'geotiff' : kind);
      if (fmt === 'current') fmt = 'geotiff';
      if (!isCategoricalResult(res) && ['shp', 'geojson', 'kml', 'kmz'].includes(fmt)) {
        addMessage('assistant', L === 'sw'
          ? 'Hiki ni matokeo endelevu (raster) — Shapefile/GeoJSON/KML haitumiki moja kwa moja. Tumia GeoTIFF kwa QGIS.'
          : 'This is a continuous raster — Shapefile/GeoJSON/KML do not apply directly. Use GeoTIFF for QGIS.',
        { options: ['export as GeoTIFF', 'export statistics CSV'] });
        return;
      }
      const aoi = getCurrentAOI(state);
      const rec = await requestExport({
        resultId: res.resultId || undefined,
        analysis: res.analysis?.id || res.type?.toLowerCase(),
        geometry: aoi?.geometry || undefined,
        format: fmt, scale: spec.scale || undefined, crs: spec.crs || undefined,
        filename: (res.label || res.type || 'result').slice(0, 40),
      });
      if (rec.status === 'running' && rec.eeTaskId) {
        addMessage('assistant', tr(L, 'export_running'));
        pollRunningExport(rec.eeTaskId);
      } else {
        postDownload(rec, fmt);
      }
    } catch (e) {
      addMessage('assistant', tr(L, 'err_prefix') + e.message);
    }
  };

  const executeZonal = async (parsed) => {
    const plan = parsed.plan || {};
    const p = plan.parameters || parsed.parameters || {};
    try {
      const { feats, label } = resolveTargetFeatures(plan.parameters ? parsed : { parameters: p });
      if (!feats.length) { addMessage('assistant', tr(L, 'zonal_none')); return; }
      addMessage('assistant', tr(L, 'zonal_plan', { analysis: plan.backend || parsed.analysis || 'ndvi' }));
      const { requestZonal: zonalPost } = await import('../../services/exportService');
      const zonal = await zonalPost({
        analysis: plan.backend || parsed.analysis || 'ndvi',
        features: { type: 'FeatureCollection', features: feats.slice(0, 50) },
        labelField: null, filter: p.filter || null,
        year: p.year ?? 2024, year2: p.year2 ?? 2020,
        source: p.source || 'sentinel2', numClasses: p.numClasses ?? 5,
        classNames: p.classNames, algorithm: p.algorithm,
        ...(state.activeProject?.id ? { projectId: state.activeProject.id } : {}),
      });
      setLastPlan(plan.backend ? plan : null);
      const lines = (zonal.rows || []).slice(0, 20).map((row) =>
        `${row.label}: ` + Object.entries(row).filter(([k]) => k !== 'label').map(([k, v]) => `${k}=${v}`).join(', '));
      addMessage('assistant',
        `${zonal.label || 'Zonal statistics'}\n\n${lines.join('\n')}` +
        (zonal.downloads?.length ? '\n\nCSV + GeoJSON saved for QGIS:' : '') +
        `\n\n${tr(L, 'ask_more')}`,
        { result: false });
      (zonal.downloads || []).forEach((d) => postDownload(d, 'zonal'));
    } catch (e) {
      addMessage('assistant', tr(L, 'err_prefix') + e.message);
    }
  };

  const executeAdmin = async (parsed) => {
    const adm = parsed.admin || parsed.plan?.admin || {};
    try {
      const { requestAdminBoundary: adminPost } = await import('../../services/exportService');
      const data = await adminPost({ name: adm.name, level: adm.level || 2 });
      const feats = data.featureCollection?.features || [];
      const { generateId: gid } = await import('../../utils/fileUtils');
      const layer = {
        id: gid(), name: data.label || adm.name, type: 'geojson',
        data: feats.length === 1 ? feats[0] : { type: 'FeatureCollection', features: feats },
        color: '#ff9800', fillColor: '#ff9800', visible: true, createdAt: Date.now(),
        boundary: true, source: 'admin', featureCount: feats.length,
        fields: [...new Set(feats.flatMap((f) => Object.keys(f.properties || {})))].slice(0, 20),
      };
      dispatch({ type: 'ADD_LAYER', payload: layer });
      dispatch({ type: 'SET_ACTIVE_AOI', payload: layer.id });
      addMessage('assistant',
        tr(L, 'boundary_added', { name: layer.name, count: feats.length }) +
        (data.candidates?.length > 1 ? '\nMatches: ' + data.candidates.map((c) => c.name).join(', ') : ''));
    } catch (e) {
      addMessage('assistant', tr(L, 'err_prefix') + e.message);
    }
  };

  const handleOption = (option) => {
    setInput(option);
    setTimeout(() => handleSend(), 100);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Toggle */}
      <Paper sx={{ position: 'absolute', bottom: 10, right: open ? 380 : 10, zIndex: 1000, transition: 'right 0.3s' }}>
        <IconButton onClick={() => { setOpen(!open); if (!open) inputRef.current?.focus(); }}
          color={open ? 'primary' : 'default'} sx={{ bgcolor: 'white', boxShadow: 2 }}>
          <SmartToy />
        </IconButton>
      </Paper>

      {open && (
        <Paper sx={{
          position: 'absolute', bottom: 10, right: 10, zIndex: 1000,
          width: 370, height: 520, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          {/* Header */}
           <Box sx={{ p: 1.2, bgcolor: '#1a237e', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <SmartToy fontSize="small" />
              <Typography variant="subtitle2" sx={{ fontSize: 13 }}>
                {tr(L, 'title')}
              </Typography>
              {llmError && (
                <Typography variant="caption" sx={{ color: '#ffab40', lineHeight: 1.2 }}>
                  {llmError}
                </Typography>
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
              <Typography
                variant="caption"
                onClick={() => switchLang('en')}
                sx={{ cursor: 'pointer', fontWeight: L === 'en' ? 700 : 400,
                  color: L === 'en' ? 'white' : 'rgba(255,255,255,0.6)', px: 0.5 }}
              >
                EN
              </Typography>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.5)' }}>|</Typography>
              <Typography
                variant="caption"
                onClick={() => switchLang('sw')}
                sx={{ cursor: 'pointer', fontWeight: L === 'sw' ? 700 : 400,
                  color: L === 'sw' ? 'white' : 'rgba(255,255,255,0.6)', px: 0.5 }}
              >
                SW
              </Typography>
              <IconButton size="small" sx={{ color: 'white' }} onClick={() => setOpen(false)}>
                <Close fontSize="small" />
              </IconButton>
            </Box>
          </Box>

          {/* Chat */}
          <Box ref={chatRef} sx={{ flex: 1, overflow: 'auto', p: 1.5, bgcolor: '#f5f5f5' }}>
            {messages.map((msg, i) => (
              <Box key={i} sx={{ mb: 1.5, display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                <Paper sx={{
                  p: 1.2, maxWidth: '88%',
                  bgcolor: msg.role === 'user' ? '#1a237e' : msg.error ? '#ffebee' : msg.result ? '#e8f5e9' : 'white',
                  color: msg.role === 'user' ? 'white' : 'text.primary',
                  borderRadius: msg.role === 'user' ? '14px 14px 4px 14px' : '4px 14px 14px 14px',
                }}>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontSize: 12.5, lineHeight: 1.6 }}>
                    {msg.text}
                  </Typography>
                  {msg.download?.url && (
                    <Button size="small" variant="contained" startIcon={<Download fontSize="small" />}
                      href={msg.download.url} target={msg.download.url.startsWith('http') ? '_blank' : undefined}
                      sx={{ mt: 1, textTransform: 'none', fontSize: 11 }}>
                      {msg.download.label || 'Download'}
                    </Button>
                  )}
                </Paper>
              </Box>
            ))}
            {running && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, ml: 2 }}>
                <CircularProgress size={14} />
                <Typography variant="caption" color="text.secondary">{progress}</Typography>
              </Box>
            )}
          </Box>

          {/* Quick options */}
          {messages[messages.length-1]?.options?.length > 0 && (
            <Box sx={{ px: 1.5, pb: 0.5, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {messages[messages.length-1].options.map(opt => (
                <Button key={opt} size="small" variant="outlined" onClick={() => handleOption(opt)}
                  sx={{ textTransform: 'none', fontSize: 11, borderRadius: 4 }}>{opt}</Button>
              ))}
            </Box>
          )}

          {/* Input */}
          <Box sx={{ p: 1, borderTop: '1px solid #e0e0e0', bgcolor: 'white' }}>
            <Box sx={{ display: 'flex', gap: 0.5 }}>
              <TextField inputRef={inputRef} fullWidth size="small"
                placeholder={tr(L, 'placeholder')}
                value={input} onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown} disabled={running}
                sx={{ '& .MuiOutlinedInput-root': { borderRadius: 3, fontSize: 13 } }} />
              <IconButton color="primary" onClick={handleSend} disabled={!input.trim() || running} size="small">
                {running ? <CircularProgress size={18} /> : <Send fontSize="small" />}
              </IconButton>
            </Box>
          </Box>
        </Paper>
      )}
    </>
  );
}
