import { API, TOKEN_KEY } from '../config/api';

function headers() {
  const h = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

export async function initGEE() {
  const res = await fetch(API.HEALTH, { headers: headers() });
  if (res.ok) return true;
  throw new Error('Server not running');
}

export async function runAnalysis(type, geometry, extra = {}) {
  const year = extra.year ?? extra.year2 ?? 2024;
  const year2 = extra.year2 ?? extra.year1 ?? 2020;
  const body = {
    analysis: type,
    geometry,
    year,
    year2,
    numClasses: extra.numClasses ?? 5,
    source: extra.source || 'sentinel2',
    maxCloud: extra.maxCloud ?? 30,
    ...(extra.projectId ? { projectId: extra.projectId } : {}),
    // GEOAI planner parameters (backend validates each; nulls omitted)
    ...Object.fromEntries(Object.entries({
      classNames: extra.classNames, algorithm: extra.algorithm, method: extra.method,
      variable: extra.variable, dataset: extra.dataset, index: extra.index, mode: extra.mode,
      thresholds: extra.thresholds, period: extra.period, month: extra.month,
      season: extra.season, months: extra.months, indicator: extra.indicator,
      pollutant: extra.pollutant, ratio: extra.ratio, preset: extra.preset, use: extra.use,
      weights: extra.weights, test: extra.test, tune: extra.tune, statsOp: extra.statsOp,
      trainingSamples: extra.trainingSamples, validationSamples: extra.validationSamples,
      classProperty: extra.classProperty, featureSelection: extra.featureSelection,
      modelConfig: extra.modelConfig,
      balanceClasses: extra.balanceClasses,
      comparisonYears: extra.comparisonYears,
      suitabilityMethod: extra.suitabilityMethod, pairwiseMatrix: extra.pairwiseMatrix,
      criteria: extra.criteria, constraints: extra.constraints,
      sensitivity: extra.sensitivity, scenarios: extra.scenarios,
    }).filter(([, v]) => v !== undefined && v !== null)),
  };
  const res = await fetch(API.ANALYSE, {
    method: 'POST', headers: headers(), body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    const err = new Error(data.error || 'Analysis failed');
    if (data.code) err.code = data.code;
    if (data.status) err.status = data.status;
    throw err;
  }
  return data;
}

export function isReady() { return true; }
export function getToken() { return localStorage.getItem(TOKEN_KEY); }
