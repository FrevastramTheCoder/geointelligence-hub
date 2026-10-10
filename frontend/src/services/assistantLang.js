/**
 * Assistant language pack (English / Kiswahili).
 * Toggle persisted in localStorage; planner + UI read it — no redesign.
 */

const KEY = 'gisai_lang';

export function getAssistantLang() {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'sw' ? 'sw' : 'en';
  } catch {
    return 'en';
  }
}

export function setAssistantLang(lang) {
  try {
    localStorage.setItem(KEY, lang === 'sw' ? 'sw' : 'en');
  } catch { /* ignore */ }
}

// Swahili blurbs per registry intent (English blurb stays in the registry).
export const BLURB_SW = {
  ndvi: 'Kielezo cha NDVI cha afya ya mimea (Sentinel-2/Landsat)',
  evi: 'Kielezo cha EVI cha mimea (hakipotoswi na udongo/anga)',
  savi: 'Kielezo cha SAVI cha mimea (kimerekebishwa kwa udongo)',
  ndwi: 'Kielezo cha NDWI cha maji / unyevu',
  ndbi: 'Kielezo cha NDBI cha maeneo yaliyojengwa / mijini',
  urban_growth: 'Ukuaji wa mijini kwa tofauti ya NDBI kati ya miaka miwili',
  elevation: 'Mwinuko kutoka SRTM DEM',
  slope: 'Mteremko kutoka SRTM DEM',
  landcover: 'Uainishaji wa matumizi ya ardhi (chaguo-msingi Random Forest, madarasa 5)',
  vegetation: 'Uainishaji wa mimea kwa vizingiti vya NDVI na madarasa yako',
  dynamicworld: 'Dynamic World madarasa 9 (m 10)',
  worldcover_v200: 'ESA WorldCover madarasa 11 (m 10)',
  modis_lc: 'MODIS MCD12Q1 madarasa 17 (m 500)',
  modis_cmg: 'MODIS MCD12C1 CMG matumizi ya ardhi',
  copernicus_lc: 'Copernicus Global Land Cover (m 100)',
  glc_fcs30: 'GLC_FCS30D (m 30)',
  nlcd: 'NLCD 2021 (Marekani pekee, m 30)',
  corine: 'CORINE 2018 (Ulaya pekee, m 100)',
  change: 'Tofauti ya NDVI kati ya miaka miwili',
  buildings: 'Hesabu ya majengo + msongamano (Open Buildings)',
  flood_risk: 'HATARI ya mafuriko kutokana na mwinuko/mteremko (makisio, si kielelezo cha uhandisi)',
  flood_mapping: 'ENEO la mafuriko kutoka Sentinel-1 SAR (maji yaliyoonekana)',
  lst: 'Joto la uso wa ardhi (MODIS, °C)',
  rainfall: 'Jumla ya mvua kutoka CHIRPS',
  erosion: 'Makadirio ya mmomonyoko (RUSLE-lite, t/ha/mwaka)',
  drought: 'Ukame kwa hitilafu ya NDVI (+ muktadha wa mvua)',
  timeseries: 'Mfululizo wa muda wa kila mwaka + mwelekeo',
  mndwi: 'Kielezo cha MNDWI cha maji (kizuri mijini)',
  awei: 'Kielezo cha AWEI cha kutoa maji',
  msavi: 'Kielezo cha MSAVI cha mimea',
  ndre: 'Kielezo cha NDRE (red-edge, Sentinel-2)',
  gndvi: 'Kielezo cha GNDVI cha mimea',
  dvi: 'Kielezo cha DVI cha mimea',
  rvi: 'Kielezo cha RVI (NIR/Red)',
  arvi: 'Kielezo cha ARVI (kinachostahimili anga)',
  bsi: 'Kielezo cha BSI cha udongo mtupu',
  ui: 'Kielezo cha UI cha mijini',
  ibi: 'Kielezo cha IBI cha maeneo yaliyojengwa',
  ebbi: 'Kielezo cha EBBI (Landsat thermal)',
  truecolor: 'Picha ya rangi halisi isiyo na mawingu',
  falsecolor: 'Picha ya rangi bandia (NIR)',
  composite: 'Picha mchanganyiko isiyo na mawingu (median)',
  aspect: 'Mwelekeo wa mteremko kutoka SRTM',
  hillshade: 'Kivuli cha mwinuko kutoka SRTM',
  slope_classes: 'Uainishaji wa mteremko kwa madarasa/vizingiti vyako',
  lst_change: 'Mabadiliko ya joto kati ya miaka miwili (MODIS)',
  uhi: 'Kisiwa cha joto mijini (joto la mjini dhidi ya mashambani)',
  uftvi: 'Kielezo cha UTFVI cha joto mijini',
  sprawl: 'Mtawanyiko wa mijini: upanuzi, kasi, katikati dhidi ya kurukaruka',
  lulc_change: 'Mabadiliko ya LULC darasa-kwa-darasa + jedwali la mpito',
  deforestation: 'Upotevu wa misitu (Hansen Global Forest Change)',
  et: 'Uvukizi kutoka MODIS MOD16',
  airquality: 'Uchafuzi wa hewa kutoka Sentinel-5P (NO2, SO2, CO, O3) / MODIS AOD',
  no2: 'NO2 (Sentinel-5P)',
  so2: 'SO2 (Sentinel-5P)',
  co: 'CO (Sentinel-5P)',
  aod: 'AOD (MODIS)',
  pm25: 'PM2.5 — hakuna seti ya data iliyosanidiwa (ujumbe wa mwongozo)',
  salinity: 'Kiashiria cha chumvi udongoni + madarasa',
  moisture: 'Unyevu wa udongo (NDMI)',
  landslide: 'Hatari ya maporomoko (vizani wazi)',
  hydrology: 'Mtandao wa mito + mkusanyiko (MERIT Hydro)',
  mineral: 'Kiashiria cha madini (wiano wa bendi)',
  suitability: 'Ufaafu kwa vizani wazi',
  trend: 'Mwelekeo: rejeshia + Mann-Kendall',
  area: 'Eneo la poligoni (ndani ya kivinjari)',
  distance: 'Umbali kati ya vituo (ndani ya kivinjari)',
  buffer: 'Duruu kuzunguka eneo (ndani ya kivinjari)',
};

const STR = {
  en: {
    empty: 'Type something! Try "show vegetation" or "classify land into 5 classes"',
    discovery_intro: 'I can run these (all real GEE/local tools):',
    discovery_hint: 'Draw an AOI, then e.g. "show vegetation" or "classify land into 5 classes".',
    unknown: 'I couldn\'t determine the analysis you want.\nTry:\n- show vegetation (NDVI)\n- show water bodies\n- show built-up areas\n- classify land into 5 classes\n- show slope\n- flood mapping vs flood risk\n- rainfall from 2015 to 2025\n- what can you analyze?',
    clarify_classes: 'What would you like to classify into {n} classes? Try "classify land into {n} classes" or "classify vegetation into forest, shrubs, grassland and cropland".',
    clarify_code_which: 'Which analysis should I write code for? E.g. "GEE code for NDVI" or "generate code for land cover classification".',
    clarify_code_unknown: 'I could not tell which analysis to write code for. Try "GEE code for NDVI".',
    clarify_pick: 'Did you mean "{a}" or "{b}"?',
    code_for: 'Generating GEE code for {x} (same datasets/method the app would run).',
    code_for_last: 'Generating GEE code for your last analysis ({x}).',
    aoi_needed: 'Please draw an area on the map first — then I can run {tool} on it.',
    method: 'Method: {x}.',
    classes: 'Classes ({n}): {list}.',
    period_range: 'Period: {a} → {b}.',
    period_year: 'Year: {y}.',
    year_default: 'No year specified — using configured default year: {y}.',
    running_aoi: 'Running on the current AOI.',
    follow_classes: 'Updating {intent} to {n} classes{names} with {algo}.',
    follow_algo: 'Switching {intent} to {algo}.',
    follow_builtin: 'Extracting built-up from the current AOI with NDBI (from your classification context).',
    follow_repeat: 'Re-running {intent} with the same parameters.',
    multi: 'I split that into {n} steps: {list}. Running them in order on the current AOI.',
    // UI
    title: 'GIS AI Assistant',
    placeholder: 'Ask about this area...',
    welcome: 'Habari! I\'m your GIS AI. Draw a polygon, then ask me anything.\n\nI can do: NDVI, NDWI, Land Cover, Vegetation, Buildings, Flood Risk, Change Detection...',
    ask_more: 'Ask me anything else!',
    legend: 'Legend',
    statistics: 'Statistics',
    processing: 'Processing...',
    running: 'Running analysis...',
    aoi_none: 'No Area of Interest. Draw a polygon or place a marker on the map first.',
    draw_two: 'Draw two shapes on the map first — I measure between their centroids.',
    err_prefix: 'Error: ',
    llm_error: 'LLM server error: ',
    code_note: 'Paste into https://code.earthengine.google.com — set `aoi` to your polygon. Python port uses the same calls via `ee`.',
    compound_done: 'Compound analysis done: {list}. Each step added its own map layer above.',
    step_failed: 'Step {i} ({intent}) failed: {err}',
    clarify_admin: 'Which administrative area? E.g. "Mbozi district" or "Vwawa ward". I search GAUL boundaries via Earth Engine.',
    admin_lookup: 'Looking up "{name}" (admin level {level}) in GAUL…',
    zonal_plan: 'Zonal statistics of {analysis} per boundary feature. Select the layer or upload the boundary first if needed.',
    export_ready: 'Export ready: {filename} ({format}). Open it in QGIS.',
    export_running: 'Export submitted (large region) — status: RUNNING. I will post the download link when it completes.',
    export_none: 'Nothing to export yet. Run an analysis first, then say "export this".',
    export_boundary_none: 'No boundary to export. Upload or draw one first.',
    boundary_added: 'Boundary "{name}" added ({count} features) and set as the analysis AOI.',
    zonal_none: 'No boundary features found. Upload a multi-feature boundary (e.g. wards) first.',
    aoi_target_ask: 'Setting "{target}" as the analysis boundary. What should I run on it?',
    aoi_target_ok: '"{name}" is now the analysis AOI. Tell me the analysis (e.g. "classify land into 5 classes").',
    aoi_target_missing: 'I could not find a layer matching "{target}". Upload it first or check the Layers tab.',
    follow_compare: 'Comparing {what} ({a} → {b}) on the current AOI.',
    follow_classify_it: 'Classifying it into {n} classes on the current AOI.',
    follow_changed: 'Checking what changed in {what} ({a} → {b}).',
    clarify_changed: 'What should I compare? Run an analysis first (e.g. "show vegetation"), then ask "what has changed?".',
    clarify_series_var: 'Time series works for NDVI, rainfall, LST, ET or NO2 — which variable should I track?',
  },
  sw: {
    empty: 'Andika kitu! Jaribu "onyesha mimea" au "ainisha ardhi katika madarasa 5"',
    discovery_intro: 'Naweza kuendesha zana hizi halisi (zote za GEE/ndani):',
    discovery_hint: 'Chora eneo (AOI), halafu sema "onyesha mimea" au "ainisha ardhi katika madarasa 5".',
    unknown: 'Sikuelewa unachotaka kuchambua.\nJaribu:\n- onyesha mimea (NDVI)\n- onyesha maji\n- onyesha maeneo yaliyojengwa\n- ainisha ardhi katika madarasa 5\n- onyesha mteremko\n- ramani ya mafuriko dhidi ya hatari ya mafuriko\n- mvua kutoka 2015 hadi 2025\n- unaweza kuchambua nini?',
    clarify_classes: 'Unataka kuainisha nini katika madarasa {n}? Jaribu "ainisha ardhi katika madarasa {n}" au "ainisha mimea katika misitu, vichaka, nyasi na mazao".',
    clarify_code_which: 'Ni uchambuzi gani nikuandikie msimbo? Mfano "msimbo wa GEE wa NDVI" au "niandikie msimbo wa uainishaji wa ardhi".',
    clarify_code_unknown: 'Sikujua uchambuzi gani wa kuandikia msimbo. Jaribu "msimbo wa GEE wa NDVI".',
    clarify_pick: 'Ulikuwa na maana "{a}" au "{b}"?',
    code_for: 'Ninatengeneza msimbo wa GEE wa {x} (seti na mbinu zile zile programu ingetumia).',
    code_for_last: 'Ninatengeneza msimbo wa GEE wa uchambuzi wako wa mwisho ({x}).',
    aoi_needed: 'Tafadhali chora eneo kwenye ramani kwanza — ndipo nitaendesha {tool}.',
    method: 'Mbinu: {x}.',
    classes: 'Madarasa ({n}): {list}.',
    period_range: 'Kipindi: {a} → {b}.',
    period_year: 'Mwaka: {y}.',
    year_default: 'Hukutaja mwaka — ninatumia mwaka chaguo-msingi uliosanidiwa: {y}.',
    running_aoi: 'Inaendeshwa kwenye eneo lako la sasa (AOI).',
    follow_classes: 'Ninabadilisha {intent} kuwa madarasa {n}{names} kwa {algo}.',
    follow_algo: 'Ninabadilisha {intent} kutumia {algo}.',
    follow_builtin: 'Ninatoa maeneo yaliyojengwa kwenye AOI kwa NDBI (kutoka muktadha wa uainishaji wako).',
    follow_repeat: 'Ninarudia {intent} kwa vigezo vile vile.',
    multi: 'Nimegawanya katika hatua {n}: {list}. Ninaziendesha kwa mpangilio kwenye AOI ya sasa.',
    // UI
    title: 'Msaidizi wa GIS AI',
    placeholder: 'Uliza kuhusu eneo hili...',
    welcome: 'Habari! Mimi ni Msaidizi wako wa GIS AI. Chora poligoni, kisha uniulize chochote.\n\nNaweza: NDVI, NDWI, Matumizi ya Ardhi, Mimea, Majengo, Hatari ya Mafuriko, Mabadiliko...',
    ask_more: 'Niulize lolote lingine!',
    legend: 'Alama',
    statistics: 'Takwimu',
    processing: 'Inachakata...',
    running: 'Inachambua...',
    aoi_none: 'Hakuna Eneo. Chora poligoni au weka alama kwenye ramani kwanza.',
    draw_two: 'Chora maumbo mawili kwenye ramani kwanza — napima kati ya vituo vyake.',
    err_prefix: 'Hitilafu: ',
    llm_error: 'Hitilafu ya seva ya LLM: ',
    code_note: 'Bandika kwenye https://code.earthengine.google.com — weka `aoi` kuwa poligoni yako. Toleo la Python linatumia miito ile ile kupitia `ee`.',
    compound_done: 'Uchambuzi mchanganyiko umekamilika: {list}. Kila hatua imeongeza safu yake ramani hapo juu.',
    step_failed: 'Hatua {i} ({intent}) imeshindwa: {err}',
    clarify_admin: 'Eneo gani la kiutawala? Mfano "wilaya ya Mbozi" au "kata ya Vwawa". Natafuta mipaka ya GAUL kupitia Earth Engine.',
    admin_lookup: 'Ninatafuta "{name}" (ngazi {level}) kwenye GAUL…',
    zonal_plan: 'Takwimu za kanda za {analysis} kwa kila kipengele cha mpaka.',
    export_ready: 'Hamisha tayari: {filename} ({format}). Fungua kwenye QGIS.',
    export_running: 'Hamisha imetumwa (eneo kubwa) — hali: RUNNING. Nitakutumia kiungo kitakapokamilika.',
    export_none: 'Hakuna cha kuhamisha bado. Endesha uchambuzi kwanza, kisha sema "hamisha".',
    export_boundary_none: 'Hakuna mpaka wa kuhamisha. Pakia au chora mmoja kwanza.',
    boundary_added: 'Mpaka "{name}" umeongezwa (vipengele {count}) na kuwekwa kama AOI ya uchambuzi.',
    zonal_none: 'Hakuna vipengele vya mpaka. Pakia mpaka wenye vipengele vingi (mfano kata) kwanza.',
    follow_compare: 'Ninalinganisha {what} ({a} → {b}) kwenye AOI ya sasa.',
    follow_classify_it: 'Ninai ainisha katika madarasa {n} kwenye AOI ya sasa.',
    follow_changed: 'Ninaangalia kilichobadilika kwenye {what} ({a} → {b}).',
    clarify_changed: 'Nilinganishe nini? Endesha uchambuzi kwanza (mfano "onyesha mimea"), kisha uliza "nini kimebadilika?".',
    clarify_series_var: 'Mfululizo wa muda unafanya kazi kwa NDVI, mvua, LST, ET au NO2 — nifuatilie kipimo gani?',
  },
};

export function tr(lang, key, vars = {}) {
  const table = STR[lang === 'sw' ? 'sw' : 'en'];
  let s = table[key] ?? STR.en[key] ?? key;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

export function blurbFor(intent, lang, fallback) {
  if (lang === 'sw' && BLURB_SW[intent]) return BLURB_SW[intent];
  return fallback;
}
