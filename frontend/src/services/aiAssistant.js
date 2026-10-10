/**
 * Conversational AI Assistant — thin dialogue layer over the GEOAI PLANNER.
 *
 * Same public API as before: processMessage(text, previousAnalysis).
 * Intent/parameters now come from geoaiPlanner (central registry), so adding
 * a tool never means adding another `if (prompt.includes(...))` here.
 * previousAnalysis may be a backend-id string (legacy) or a plan object.
 */
import { planRequest } from './geoaiPlanner';
import { tr } from './assistantLang';

const CONVERSATION = {
  greetings: ['hi', 'hello', 'hey', 'habari', 'mambo', 'vipi', 'salama', 'niaje', 'shikamoo', 'hujambo', 'good morning', 'good afternoon', 'good evening', 'habari yako'],
  thanks: ['thanks', 'thank you', 'asante', 'ahsante', 'shukrani', 'nashukuru'],
  help: ['help', 'menu', 'options', 'commands', 'saidia', 'nisaidie'],
  identity: ['who are you', 'your name', 'what are you', 'about yourself', 'jina lako', 'wewe ni nani', 'nani wewe', 'you are', 'yourself'],
  farewell: ['bye', 'goodbye', 'good night', 'see you', 'kwaheri', 'tutaonana', 'baadaye', 'later'],
  // "I have drawn" confirmations — NOT thanks. User drew AOI, wants to run.
  aoiDone: ['done', 'ok', 'okay', 'sawa', 'ready', 'nimechora', 'nimeshachora', 'nimemaliza', 'nipo tayari', 'iko tayari', 'done!'],
};

function isSwahili(text) {
  return /habari|mambo|asante|tafadhali|nionyeshe|onyesha|ainisha|tafadhali|karibu|ndiyo|hapana|jina|nani|wewe|mimi|kwaheri|tutaonana|eneo|ardhi|maji|mvua|mimea|misitu|mazao|mafuriko|ukame|mteremko|joto|madini|shamba|shambani|nini|gani|kiasi|vipi/.test(text);
}

/**
 * Main parser — dialogue + planner routing.
 * Returns superset of the legacy shape:
 * { type, analysis, year, year2, numClasses, reply, confidence, ...plan }
 */
export function processMessage(text, previousAnalysis = null, opts = {}) {
  const L = opts.lang === 'sw' ? 'sw' : 'en';
  const lower = (text || '').toLowerCase().trim();
  if (!lower) return { type: 'empty', reply: tr(L, 'empty') };

  if (CONVERSATION.greetings.some((g) => lower === g || lower.startsWith(g + ' '))) {
    return {
      type: 'chat',
      reply: L === 'sw'
        ? 'Habari! Mimi ni Msaidizi wako wa GIS AI. Chora poligoni kwenye ramani, kisha uniulize chochote:\n\n• "Onyesha mimea"\n• "Maji yako wapi?"\n• "Ainisha ardhi katika madarasa 5"\n• "Onyesha hatari ya mafuriko dhidi ya ramani ya mafuriko"\n• "Mvua kutoka 2015 hadi 2025"'
        : 'Hello! I am your GIS AI Assistant. Draw a polygon on the map, then ask me anything:\n\n• "Show me vegetation"\n• "Where is the water?"\n• "Classify land into 5 classes"\n• "Show flood risk vs flood mapping"\n• "Rainfall from 2015 to 2025"',
    };
  }
  if (CONVERSATION.thanks.some((t) => lower === t || lower.startsWith(t + ' ') || lower.endsWith(' ' + t) || lower.includes(' ' + t + ' '))) {
    return { type: 'chat', reply: (L === 'sw' || isSwahili(lower)) ? 'Karibu sana! Niulize lolote lingine kuhusu eneo lako — niko hapa kukusaidia.' : "You're welcome! Ask me anything else about your area of interest — I'm here to help." };
  }
  // AOI-ready confirmation: user just finished drawing. If a previous plan
  // exists, re-run it by command; otherwise ask what to run.
  if (CONVERSATION.aoiDone.some((t) => lower === t || lower === t + '!' || lower === t + '.')) {
    if (previousAnalysis && typeof previousAnalysis === 'object' && (previousAnalysis.backend || previousAnalysis.intent)) {
      const p = previousAnalysis;
      return { type: 'analysis', analysis: p.backend || p.intent,
        year: p.parameters?.year ?? null, year2: p.parameters?.year2 ?? null,
        numClasses: p.parameters?.numClasses ?? null,
        reply: (L === 'sw' || isSwahili(lower))
          ? `Sawa! Ninaendesha ${p.backend || p.intent} kwenye eneo ulilochora sasa.`
          : `Got it! Running ${p.backend || p.intent} on your drawn area now.`,
        confidence: 0.9, parameters: p.parameters || {}, plan: p };
    }
    return { type: 'chat', reply: (L === 'sw' || isSwahili(lower))
      ? 'Vizuri! Eneo liko tayari. Sasa sema nifanye nini — mfano "onyesha mimea" au "ainisha ardhi katika madarasa 5".'
      : 'Great — your area is ready. Now tell me what to run — e.g. "show vegetation" or "classify land into 5 classes".' };
  }
  if (CONVERSATION.identity.some((t) => lower.includes(t))) {
    const sw = L === 'sw' || isSwahili(lower);
    return { type: 'chat', reply: sw
      ? 'Mimi ni Msaidizi wa GIS AI wa GeoIntelligence Hub — rafiki yako wa kuchambua ramani na setilaiti. Ninaelewa Kiswahili na Kiingereza. Chora eneo kwenye ramani, kisha niambie unachotaka: mimea, maji, ardhi, mvua, mafuriko — nitachambua na kukupa ramani, alama na takwimu. Unaweza kuniuliza "unaweza kuchambua nini?" kuona yote!'
      : "I'm the GeoIntelligence Hub GIS AI Assistant — your friendly map-and-satellite analyst. I speak English and Kiswahili. Draw an area on the map and tell me what you want: vegetation, water, land cover, rainfall, floods — I'll analyze it and give you a map, legend and statistics. Ask me \"what can you analyze?\" to see everything!" };
  }
  if (CONVERSATION.farewell.some((t) => lower === t || lower.startsWith(t + ' ') || lower.endsWith(' ' + t))) {
    return { type: 'chat', reply: (L === 'sw' || isSwahili(lower)) ? 'Kwaheri! Kazi yako imehifadhiwa kwenye miradi. Rudi tena unapohitaji kuchambua eneo lingine.' : 'Goodbye! Your work is saved under Projects. Come back anytime you need to analyze another area.' };
  }
  if (CONVERSATION.help.some((h) => lower === h || lower.startsWith('what can you'))) {
    // fall through to planner discovery (lists only implemented tools)
  } else if (CONVERSATION.help.some((h) => lower.includes(h)) && lower.length < 30) {
    return {
      type: 'chat',
      reply: L === 'sw'
        ? 'Chora umbo, kisha sema:\n\n• "Onyesha mimea" (NDVI)\n• "Onyesha maji"\n• "Onyesha maeneo yaliyojengwa"\n• "Ainisha ardhi katika madarasa 5"\n• "Onyesha mteremko"\n• "Ramani ya mafuriko" au "hatari ya mafuriko"\n• "Mvua kutoka 2015 hadi 2025"\n• "Unaweza kuchambua nini?"'
        : 'Draw a shape, then ask e.g.:\n\n• "Show vegetation" (NDVI)\n• "Show water bodies"\n• "Show built-up areas"\n• "Classify land into 5 classes"\n• "Show slope"\n• "Flood mapping" or "flood risk"\n• "Rainfall from 2015 to 2025"\n• "What can you analyze?"',
    };
  }

  // Normalize legacy previousAnalysis (string backend id) into a plan-like ctx
  let prev = null;
  if (previousAnalysis && typeof previousAnalysis === 'object') {
    prev = previousAnalysis;
  } else if (typeof previousAnalysis === 'string' && previousAnalysis) {
    prev = { intent: previousAnalysis, backend: previousAnalysis, parameters: {} };
  }

  // AOI presence is resolved by the caller via plan ctx; here assume unknown
  // and let the executor re-check (it has layer state). Pass hasAOI=true so
  // the planner returns full params; executor enforces the AOI gate.
  const layerNames = Array.isArray(opts.layerNames) ? opts.layerNames : [];
  const plan = planRequest(text, { hasAOI: true, prev, lang: L, layerNames });

  if (plan.intent === 'empty') return { type: 'empty', reply: plan.reply };
  if (plan.intent === 'discovery') return { type: 'chat', reply: plan.reply, plan };
  if (plan.intent === 'knowledge') return { type: 'knowledge', reply: plan.reply, plan, methodId: plan.methodId, methodologyStatus: plan.methodologyStatus };
  if (plan.intent === 'unknown') return { type: 'unknown', reply: plan.reply, plan };
  if (plan.intent === 'clarify') return { type: 'clarify', reply: plan.reply, options: plan.options || [], plan };
  if (plan.intent === 'multi_step') {
    return { type: 'multi_step', reply: plan.reply, steps: plan.steps, plan,
      analysis: plan.steps[0]?.backend, year: plan.steps[0]?.parameters?.year };
  }
  if (plan.intent === 'code') {
    return { type: 'code', reply: plan.reply, plan, analysis: plan.backend,
      parameters: plan.parameters };
  }
  if (plan.exportKind) {
    return { type: 'export', reply: plan.reply, plan, exportKind: plan.exportKind,
      parameters: plan.parameters };
  }
  if (plan.admin) {
    return { type: 'admin', reply: plan.reply, plan, admin: plan.admin,
      parameters: plan.parameters };
  }
  if (plan.intent === 'zonal') {
    return { type: 'zonal', reply: plan.reply, plan, analysis: plan.backend,
      parameters: plan.parameters };
  }
  // Local measurement tools keep legacy ids so old UI labels still work
  if (plan.local) {
    return { type: 'analysis', analysis: plan.intent, local: plan.local,
      year: plan.parameters?.year ?? null, year2: plan.parameters?.year2 ?? null,
      numClasses: plan.parameters?.numClasses ?? null, reply: plan.reply,
      confidence: plan.confidence, parameters: plan.parameters, plan };
  }
  return { type: 'analysis', analysis: plan.backend,
    year: plan.parameters?.year ?? null, year2: plan.parameters?.year2 ?? null,
    numClasses: plan.parameters?.numClasses ?? null, reply: plan.reply,
    confidence: plan.confidence, parameters: plan.parameters, plan };
}
