/* Clock — four frontier models from four companies, deliberating in your browser.
 *
 * This file is the whole product. It holds the orchestration that a human used to do by
 * hand between rounds: it asks each model alone, collects what they said, composes the
 * next round's prompt for every seat out of the others' answers, and asks a synthesizer
 * to build the combined result. Nothing leaves this tab except requests to OpenRouter.
 *
 * Two invariants are load-bearing and worth naming:
 *   1. In round one no seat can see another seat's answer. It is enforced by what goes
 *      into the request, not by asking the models nicely.
 *   2. A reply cut off at the token ceiling is a failure, not a short answer, and never
 *      enters that seat's memory of the conversation.
 */
'use strict';

const API = 'https://openrouter.ai/api/v1/chat/completions';
const LS_KEY = 'clock.openrouter.key';
const LS_TEAM = 'clock.team';
const MAX_TOKENS = 8000;

const SEATS = [
  { id: 'opus',   model: 'anthropic/claude-opus-5',        short: 'Claude', vendor: 'Anthropic', label: 'Claude (Anthropic)' },
  { id: 'sol',    model: 'openai/gpt-5.6-sol',             short: 'GPT',    vendor: 'OpenAI',    label: 'GPT (OpenAI)' },
  { id: 'gemini', model: 'google/gemini-3.1-pro-preview',  short: 'Gemini', vendor: 'Google',    label: 'Gemini (Google)' },
  { id: 'grok',   model: 'x-ai/grok-4.6',                  short: 'Grok',   vendor: 'xAI',       label: 'Grok (xAI)' },
];
const SEAT = Object.fromEntries(SEATS.map(s => [s.id, s]));
const SYNTHESIZER = 'sol';   // deliberately not the model that wrote this page

const STAGES = [
  { key: 'independent', name: 'Independent', verb: 'Asking the room',
    note: 'Asked cold. No participant is told that anyone else is answering, or who — not just ' +
          "kept from the others' text, but unaware there is a room at all, so nobody can posture, " +
          'defer, or leave a gap for someone else to fill.' },
  { key: 'critique', name: 'Critique', verb: 'Comparing perspectives',
    note: 'Each model now reads the other three and responds. Web search stays on, so a shaky ' +
          'number can be checked rather than deferred to.' },
  { key: 'reconsider', name: 'Reconsider', verb: 'Challenging assumptions',
    note: 'Where everyone stands after being argued with, what moved them, and what they still ' +
          'hold. Direct questions to a named participant are allowed here.' },
  { key: 'exchange', name: 'Exchange', verb: 'Answering each other',
    note: 'Questions put by name get answered, and each model says the one thing it wants the ' +
          'room to keep.' },
];
const MODES = { deliberate: ['independent', 'critique', 'reconsider', 'exchange'], quick: ['independent'] };

// Round one is blind, and blind means the model is never told that anyone else is
// answering, or who. Merely knowing the room is enough to change what a model says: it
// postures, it defers to whoever it assumes is stronger on a topic, it leaves gaps for
// someone else to fill. The others are introduced in round two, together with their answers.
const systemBlind = date =>
`Today is ${date}.

Answer in your own voice, as prose. No headings, no bullet lists, no section labels, no \
restating the question back.

Say what you actually think, and say plainly when you don't know or when the evidence is \
thin. You have web search: use it to check a fact rather than asserting it from memory. Be \
concise — a few tight paragraphs at most.`;

// From round two on, the room exists and the model is told who is in it.
const systemRoom = (label, date) =>
`You are ${label}, one of four AI models from four different companies sitting in one room and \
thinking together. The room is Claude (Anthropic), GPT (OpenAI), Gemini (Google) and Grok (xAI). \
Today is ${date}.

Talk like a person in a good conversation. Prose, your own voice, no headings, no bullet lists, \
no section labels. Address the others directly by name when you are responding to them.

You are not here to be agreeable. Say what you actually think, disagree plainly when you \
disagree, and say plainly when you don't know or when you were wrong. You have web search: use \
it to check a claim rather than deferring to whoever sounded most confident. Never invent \
agreement that isn't there, and never manufacture disagreement that isn't there either. Be \
concise — a few tight paragraphs at most.`;

const PROMPTS = {
  independent: q => q,
  critique: others =>
    `Something you were not told: three other AI models, from three other companies, were asked ` +
    `that same question at the same moment, each of them alone and unaware of the rest — as were ` +
    `you. Here is what each of them said:\n\n${others}\n\nRespond to them. Where do you agree, where do you think one of ` +
    `them is wrong or is missing something that matters, and what did someone surface that you ` +
    `didn't? Go check the specific factual claims that look shaky rather than smoothing them ` +
    `over. Name names.`,
  reconsider: others =>
    `Here is how everyone responded to everyone:\n\n${others}\n\nWhere do you stand now? Say ` +
    `what you've changed your mind about and why, what you still hold to and why the objections ` +
    `didn't move you, and what you think is genuinely still unresolved. If you want an answer ` +
    `from someone specific, ask them directly by name — they will see it.`,
  exchange: others =>
    `Here is the last round:\n\n${others}\n\nAnswer any question that was put to you by name, ` +
    `and say the one thing you most want the room to take away. Short.`,
};

const synthPrompt = (question, all) =>
  `You are the synthesizer for this run. Four models — Claude, GPT, Gemini and Grok — were ` +
  `asked: "${question}"\n\nHere is the entire conversation, in order:\n\n${all}\n\nWrite the ` +
  `strongest combined answer the room can support. Do not take a majority vote and do not ` +
  `average anyone into blandness. Say what they agreed on, what they disagreed on and why, what ` +
  `evidence would settle it, what one of them saw that the others missed, where confidence is ` +
  `high and where it isn't. If a claim was made and nobody checked it, say so rather than ` +
  `passing it on. Prose, no headings. Then, as the very last line and nothing after it, write: ` +
  `CONFIDENCE: <0.0-1.0>`;

// ---------------------------------------------------------------- state ----
const $ = id => document.getElementById(id);
const state = {
  key: '',
  remembered: false,
  mode: 'deliberate',
  team: SEATS.map(s => s.id),
  run: null,
  controller: null,
};

// ------------------------------------------------------------ transport ----
/**
 * One streaming request to one vendor. Resolves to {text, meta}; never rejects.
 * onDelta receives each token as it arrives so the page can paint while it thinks.
 */
async function streamOne(model, messages, onDelta, signal) {
  const t0 = performance.now();
  const meta = { model, ok: false, usage: null, finish: null, provider: null, citations: [] };
  let text = '';
  try {
    const res = await fetch(API, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.key}` },
      body: JSON.stringify({
        model, messages, max_tokens: MAX_TOKENS, stream: true,
        usage: { include: true },
        plugins: [{ id: 'web', max_results: 6 }],
      }),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = JSON.parse(await res.text());
        detail = (j.error && (j.error.message || j.error.code)) || detail;
      } catch (_) { /* body was not JSON; the status is all we have */ }
      meta.error = detail;
      return { text, meta: finish(meta, t0, text) };
    }

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      // SSE frames are newline-delimited; the last fragment may be a partial line.
      let nl;
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line || line.startsWith(':')) continue;          // keepalive comment
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        if (payload === '[DONE]') continue;
        let chunk;
        try { chunk = JSON.parse(payload); } catch (_) { continue; }
        if (chunk.error) { meta.error = chunk.error.message || 'stream error'; continue; }
        const ch = (chunk.choices || [])[0];
        if (ch) {
          const d = ch.delta || {};
          if (d.content) { text += d.content; onDelta(d.content); }
          if (ch.finish_reason) meta.finish = ch.finish_reason;
          const ann = d.annotations || (ch.message && ch.message.annotations) || [];
          for (const a of ann) {
            if (a.type === 'url_citation' && a.url_citation && a.url_citation.url) {
              meta.citations.push(a.url_citation.url);
            }
          }
        }
        if (chunk.usage) meta.usage = chunk.usage;
        if (chunk.provider) meta.provider = chunk.provider;
        if (chunk.model) meta.served = chunk.model;
      }
    }
  } catch (e) {
    meta.error = e.name === 'AbortError' ? 'stopped' : `${e.name}: ${e.message}`;
    meta.aborted = e.name === 'AbortError';
  }
  return { text, meta: finish(meta, t0, text) };
}

function finish(meta, t0, text) {
  meta.latency = Math.round((performance.now() - t0) / 100) / 10;
  // A reply cut off at the ceiling is a partial failure. Silence — and half a thought —
  // must never read as a clean answer.
  meta.ok = text.trim().length > 0 && meta.finish !== 'length' && !meta.error;
  if (text.trim() && meta.finish === 'length') meta.error = 'cut off at the token limit';
  return meta;
}

// ------------------------------------------------------------ rendering ----
function esc(s) {
  return s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
function fmt(t) {
  let h = esc(t);
  h = h.replace(/\[\[(\d+)\]\]\((\S+?)\)/g,
    (_, n, u) => `<sup class="cite"><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${n}</a></sup>`);
  h = h.replace(/\(\[([^\]]+)\]\((\S+?)\)\)/g,
    (_, l, u) => `<sup class="cite"><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(l.replace(/^www\./, '').split('.')[0])}</a></sup>`);
  h = h.replace(/\[([^\]]+)\]\((\S+?)\)/g,
    (_, l, u) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${l}</a>`);
  h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  return h.split(/\n{2,}/).filter(p => p.trim()).map(p => `<p>${p.replace(/\n/g, ' ')}</p>`).join('');
}
const num = n => (n == null ? '—' : n.toLocaleString('en-US'));

function metaLine(m) {
  const bits = [];
  if (m.latency) bits.push(`${m.latency}s`);
  if (m.usage && m.usage.total_tokens) bits.push(`${num(m.usage.total_tokens)} tok`);
  const c = m.citations.length;
  bits.push(c ? `${c} source${c === 1 ? '' : 's'}` : 'no sources');
  if (m.usage && typeof m.usage.cost === 'number') bits.push(`$${m.usage.cost.toFixed(3)}`);
  return bits.join('  ·  ');
}

function stageEl(stage, idx) {
  const sec = document.createElement('section');
  sec.className = 'round';
  sec.innerHTML =
    `<div class="round-head"><span class="round-num">${String(idx).padStart(2, '0')}</span>` +
    `<h3 class="round-name">${stage.name}</h3><span class="round-rule"></span></div>` +
    `<p class="round-note">${stage.note}</p>`;
  $('rounds').appendChild(sec);
  return sec;
}

function turnEl(parent, seat) {
  const a = document.createElement('article');
  a.className = `turn live seat-${seat.id}`;
  a.innerHTML =
    `<div class="turn-head"><span class="turn-who">${seat.label}</span>` +
    `<span class="turn-meta"></span></div><div class="turn-body"></div>`;
  parent.appendChild(a);
  return { root: a, body: a.querySelector('.turn-body'), meta: a.querySelector('.turn-meta') };
}

function paintProgress(keys, activeIdx) {
  const p = $('progress');
  p.textContent = '';
  const all = keys.map(k => STAGES.find(s => s.key === k)).concat([{ name: 'Synthesis' }]);
  all.forEach((s, i) => {
    const el = document.createElement('span');
    el.className = 'pstage';
    el.dataset.state = i < activeIdx ? 'done' : i === activeIdx ? 'active' : 'todo';
    el.innerHTML = `<span class="tick"></span>${s.name}`;
    p.appendChild(el);
  });
}

function notice(msg, parent) {
  const d = document.createElement('div');
  d.className = 'notice';
  d.innerHTML = msg;
  (parent || $('rounds')).appendChild(d);
}

function paintLedger() {
  const r = state.run;
  const per = {}, tot = { turns: 0, tokens: 0, cost: 0, cites: 0 };
  for (const rd of r.rounds) for (const t of rd.turns) {
    if (!t.meta.ok) continue;
    const p = per[t.seat] || (per[t.seat] = { tokens: 0, cost: 0, cites: 0, turns: 0 });
    const u = t.meta.usage || {};
    p.turns++; tot.turns++;
    p.tokens += u.total_tokens || 0; tot.tokens += u.total_tokens || 0;
    p.cost += u.cost || 0;           tot.cost += u.cost || 0;
    p.cites += t.meta.citations.length; tot.cites += t.meta.citations.length;
  }
  if (r.synthMeta && r.synthMeta.usage) {
    tot.tokens += r.synthMeta.usage.total_tokens || 0;
    tot.cost += r.synthMeta.usage.cost || 0;
    tot.turns++;
  }
  r.totals = tot; r.perSeat = per;
  const box = $('ledger');
  box.hidden = false;
  box.innerHTML =
    `<span><b>${tot.turns}</b> turns</span><span><b>${num(tot.tokens)}</b> tokens</span>` +
    `<span><b>${tot.cites}</b> sources</span><span><b>$${tot.cost.toFixed(2)}</b> billed by OpenRouter</span>` +
    SEATS.filter(s => per[s.id]).map(s =>
      `<span>${s.short} <b>$${per[s.id].cost.toFixed(2)}</b></span>`).join('');
}

// ---------------------------------------------------------- the room ------
function othersBlock(round, exclude) {
  return round.turns
    .filter(t => t.seat !== exclude && t.meta.ok && t.text.trim())
    .map(t => `--- ${SEAT[t.seat].label} said ---\n${t.text.trim()}`)
    .join('\n\n');
}

async function runStage(stage, idx, question, prevRound) {
  const sec = stageEl(stage, idx + 1);
  $('stage-now').textContent = stage.verb + '…';
  const seats = state.team.map(id => SEAT[id]);
  const round = { key: stage.key, name: stage.name, note: stage.note, turns: [] };

  // Every seat is launched before any of them returns. In the independent stage that is
  // also what makes independence real: there is nothing of anyone else's to include.
  const jobs = seats.map(seat => {
    const ui = turnEl(sec, seat);
    const mem = state.run.memory[seat.id] ||
      (state.run.memory[seat.id] = [{ role: 'system', content: systemBlind(state.run.date) }]);
    // The room only exists from the critique round on; until then this seat has never heard of it.
    if (stage.key !== 'independent') {
      mem[0] = { role: 'system', content: systemRoom(seat.label, state.run.date) };
    }
    const content = stage.key === 'independent'
      ? PROMPTS.independent(question)
      : PROMPTS[stage.key](othersBlock(prevRound, seat.id));
    const send = mem.concat([{ role: 'user', content }]);

    return streamOne(seat.model, send, chunk => {
      ui.body.textContent += chunk;
      ui.body.scrollIntoView({ block: 'nearest' });
    }, state.controller.signal).then(({ text, meta }) => {
      ui.root.classList.remove('live');
      ui.body.innerHTML = fmt(text);
      ui.meta.textContent = metaLine(meta);
      if (meta.ok) {
        state.run.memory[seat.id] = send.concat([{ role: 'assistant', content: text }]);
      } else {
        ui.root.classList.add('failed');
        const why = meta.aborted ? 'stopped' : (meta.error || 'no answer');
        ui.meta.innerHTML = `<span class="turn-status">${esc(seat.short)} did not finish this round — ${esc(why)}</span>`;
        if (!text.trim()) ui.body.innerHTML = '';
      }
      round.turns.push({ seat: seat.id, text, meta });
    });
  });

  await Promise.all(jobs);
  round.turns.sort((a, b) => state.team.indexOf(a.seat) - state.team.indexOf(b.seat));
  state.run.rounds.push(round);

  const ok = round.turns.filter(t => t.meta.ok).length;
  if (ok < seats.length && !state.run.stopped) {
    const missing = round.turns.filter(t => !t.meta.ok).map(t => SEAT[t.seat].short);
    notice(`<b>${missing.join(' and ')} ${missing.length > 1 ? 'were' : 'was'} unavailable for this round.</b> ` +
           `Clock carried on with ${ok} participant${ok === 1 ? '' : 's'}.`, sec);
  }
  return round;
}

async function runSynthesis(question) {
  $('stage-now').textContent = 'Building the synthesis…';
  const blocks = [];
  for (const rd of state.run.rounds) {
    blocks.push(`===== ROUND: ${rd.name} =====`);
    for (const t of rd.turns) {
      if (t.meta.ok && t.text.trim()) blocks.push(`--- ${SEAT[t.seat].label} ---\n${t.text.trim()}`);
    }
  }
  const who = SEAT[state.team.includes(SYNTHESIZER) ? SYNTHESIZER : state.team[0]];
  $('synth-box').hidden = false;
  $('synth-by').textContent =
    `Synthesized by ${who.label} — deliberately not the model that wrote this page. The role is a flag, not a fixture.`;
  const body = $('synth-body');
  body.textContent = '';
  $('synth-box').classList.add('live');

  // Fresh context on purpose: the synthesizer reads the record, it does not carry its own side.
  const { text, meta } = await streamOne(who.model,
    [{ role: 'user', content: synthPrompt(question, blocks.join('\n\n')) }],
    c => { body.textContent += c; }, state.controller.signal);

  $('synth-box').classList.remove('live');
  const conf = (text.match(/CONFIDENCE:\s*([\d.]+)/) || [])[1];
  const clean = text.replace(/\n*CONFIDENCE:\s*[\d.]+\s*$/, '');
  body.innerHTML = clean.trim() ? fmt(clean) : `<p class="turn-status">The synthesizer did not finish — ${esc(meta.error || 'no answer')}</p>`;
  if (conf) {
    const v = Math.max(0, Math.min(1, parseFloat(conf)));
    $('conf-box').hidden = false;
    $('conf-fill').style.width = `${v * 100}%`;
    $('conf-num').textContent = v.toFixed(2);
  }
  state.run.synthesis = clean.trim();
  state.run.synthesizedBy = who.label;
  state.run.confidence = conf || null;
  state.run.synthMeta = meta;
}

async function run() {
  const question = $('question').value.trim();
  if (!question) { $('question').focus(); return; }
  if (!state.key) { openKey('Add your key and Clock will get started.'); return; }
  if (!state.team.length) { return; }

  state.controller = new AbortController();
  state.run = {
    question,
    date: new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }),
    mode: state.mode, team: state.team.slice(),
    rounds: [], memory: {}, synthesis: '', synthesizedBy: '', stopped: false,
  };

  $('ask-view').hidden = true;
  $('run-view').hidden = false;
  $('run-question').textContent = question;
  $('rounds').textContent = '';
  $('synth-box').hidden = true;
  $('conf-box').hidden = true;
  $('ledger').hidden = true;
  $('download').disabled = true;
  $('stop').disabled = false;

  const keys = MODES[state.mode];
  let prev = null;
  try {
    for (let i = 0; i < keys.length; i++) {
      paintProgress(keys, i);
      const stage = STAGES.find(s => s.key === keys[i]);
      prev = await runStage(stage, i, question, prev);
      if (state.run.stopped) break;
      if (!prev.turns.some(t => t.meta.ok)) {
        notice('<b>Every seat failed this round.</b> Clock stopped here rather than synthesizing nothing.');
        state.run.stopped = true;
        break;
      }
    }
    if (!state.run.stopped) {
      paintProgress(keys, keys.length);
      await runSynthesis(question);
    }
  } finally {
    paintProgress(keys, state.run.stopped ? -1 : keys.length + 1);
    $('stage-now').textContent = state.run.stopped ? 'stopped' : 'done';
    $('stop').disabled = true;
    if (state.run.rounds.length) { paintLedger(); $('download').disabled = false; }
  }
}

// ------------------------------------------------------------- download ---
/** Build a standalone copy of this run. Same stylesheet, no network, saved by the browser. */
function buildDownload() {
  const r = state.run;
  let css = '';
  for (const sheet of document.styleSheets) {
    try { for (const rule of sheet.cssRules) css += rule.cssText + '\n'; }
    catch (_) { /* a stylesheet we cannot read is one we did not ship */ }
  }
  const head =
    `<!doctype html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>Clock — ${esc(r.question).slice(0, 70)}</title><style>${css}` +
    `.turn.live .turn-body::after{display:none}@media print{.turn,.tp{break-inside:avoid}}` +
    `</style></head><body><div class="shell">`;

  const parts = [head];
  parts.push(`<header class="mast"><div class="mast-top"><div class="wordmark"><b>Clock.</b> &nbsp;the room</div>` +
    `<div class="stamp">${esc(r.date)}</div></div>` +
    `<p class="kicker">One question · ${r.team.length} vendors · ${r.rounds.length} round${r.rounds.length === 1 ? '' : 's'}</p>` +
    `<h1>${esc(r.question)}</h1>` +
    `<p class="standfirst">Each model answered alone first, with no sight of the others, then read ` +
    `each other and argued. Nothing below was edited or reordered. The disagreements are the point.</p>` +
    `<div class="seats">${r.team.map(id =>
      `<span class="seat-chip seat-${id}"><span class="dot"></span><span class="who">${SEAT[id].short}</span>` +
      `<span class="vendor">${SEAT[id].vendor}</span></span>`).join('')}</div></header><main>`);

  r.rounds.forEach((rd, i) => {
    parts.push(`<section class="round"><div class="round-head"><span class="round-num">${String(i + 1).padStart(2, '0')}</span>` +
      `<h3 class="round-name">${esc(rd.name)}</h3><span class="round-rule"></span></div>` +
      `<p class="round-note">${esc(rd.note)}</p>`);
    for (const t of rd.turns) {
      if (!t.meta.ok) {
        parts.push(`<article class="turn failed seat-${t.seat}"><div class="turn-head">` +
          `<span class="turn-who">${esc(SEAT[t.seat].label)}</span><span class="turn-meta">` +
          `did not finish this round — ${esc(t.meta.error || 'no answer')}</span></div></article>`);
        continue;
      }
      parts.push(`<article class="turn seat-${t.seat}"><div class="turn-head">` +
        `<span class="turn-who">${esc(SEAT[t.seat].label)}</span>` +
        `<span class="turn-meta">${esc(metaLine(t.meta))}</span></div>` +
        `<div class="turn-body">${fmt(t.text)}</div></article>`);
    }
    parts.push('</section>');
  });

  if (r.synthesis) {
    parts.push(`<div class="synth"><div class="by">Synthesized by ${esc(r.synthesizedBy)}</div>` +
      `<h2>The strongest answer the room can support</h2>` +
      `<div class="synth-body">${fmt(r.synthesis)}</div>`);
    if (r.confidence) {
      const v = Math.max(0, Math.min(1, parseFloat(r.confidence)));
      parts.push(`<div class="conf"><span class="conf-label">Stated confidence</span>` +
        `<span class="conf-bar"><span class="conf-fill" style="width:${v * 100}%"></span></span>` +
        `<span class="conf-num">${v.toFixed(2)}</span></div>`);
    }
    parts.push('</div>');
  }

  const t = r.totals || { turns: 0, tokens: 0, cites: 0, cost: 0 };
  parts.push(`</main><footer><span>Produced by Clock in a browser tab. ${t.turns} turns, ` +
    `${num(t.tokens)} tokens, ${t.cites} web sources, $${t.cost.toFixed(2)} billed by OpenRouter. ` +
    `Every turn is a real API call to the named vendor; any factual claims are the models' own.` +
    `</span><span><code>${esc(r.date)}</code></span></footer></div></body></html>`);
  return parts.join('\n');
}

function download() {
  const blob = new Blob([buildDownload()], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const slug = state.run.question.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48);
  a.href = url;
  a.download = `clock-${slug || 'run'}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ----------------------------------------------------------------- key ----
/** The header button is the only place a user can tell whether Clock has a key. */
function paintKey() {
  $('key-dot').classList.toggle('set', !!state.key);
  $('key-btn-label').textContent = state.key ? 'Key set' : 'Add key';
  $('tagline').textContent = state.key ? 'a room of four minds' : 'bring your own OpenRouter key';
}

function keyState() {
  $('key-state').textContent = state.key
    ? (state.remembered ? 'A key is saved in this browser.' : 'A key is set for this tab only.')
    : 'No key set.';
}
function openKey(msg) {
  $('key').value = state.key;
  $('remember').checked = state.remembered;
  keyState();
  if (msg) $('key-state').textContent = msg;
  $('key-dialog').showModal();
}
function loadKey() {
  try {
    const k = localStorage.getItem(LS_KEY);
    if (k) { state.key = k; state.remembered = true; }
  } catch (_) { /* private mode, or storage blocked — memory-only is a fine fallback */ }
}

// --------------------------------------------------------------- wiring ---
function buildTeam() {
  const box = $('team');
  box.textContent = '';
  for (const s of SEATS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `member seat-${s.id}`;
    b.setAttribute('aria-pressed', String(state.team.includes(s.id)));
    b.innerHTML = `<span class="dot"></span><span>${s.short}</span><span class="vendor">${s.vendor}</span>`;
    b.addEventListener('click', () => {
      const on = state.team.includes(s.id);
      if (on && state.team.length === 1) return;          // somebody has to be in the room
      state.team = on ? state.team.filter(x => x !== s.id)
                      : SEATS.map(x => x.id).filter(x => x === s.id || state.team.includes(x));
      b.setAttribute('aria-pressed', String(!on));
      try { localStorage.setItem(LS_TEAM, JSON.stringify(state.team)); } catch (_) {}
    });
    box.appendChild(b);
  }
  const note = document.createElement('span');
  note.className = 'team-note';
  note.textContent = 'click to seat or unseat';
  box.appendChild(note);
}

function init() {
  loadKey();
  try {
    const t = JSON.parse(localStorage.getItem(LS_TEAM) || 'null');
    if (Array.isArray(t) && t.length && t.every(id => SEAT[id])) state.team = t;
  } catch (_) {}
  buildTeam();

  document.querySelectorAll('.seg-b').forEach(btn => {
    btn.addEventListener('click', () => {
      state.mode = btn.dataset.mode;
      document.querySelectorAll('.seg-b').forEach(b =>
        b.setAttribute('aria-checked', String(b === btn)));
    });
  });

  $('run').addEventListener('click', run);
  $('question').addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') run();
  });
  $('open-key').addEventListener('click', () => openKey());
  $('open-privacy').addEventListener('click', () => $('privacy-dialog').showModal());
  $('download').addEventListener('click', download);
  $('stop').addEventListener('click', () => {
    if (state.run) state.run.stopped = true;
    if (state.controller) state.controller.abort();
    $('stop').disabled = true;
  });
  $('restart').addEventListener('click', () => {
    if (state.controller) state.controller.abort();
    $('run-view').hidden = true;
    $('ask-view').hidden = false;
    $('question').focus();
  });

  $('key-dialog').addEventListener('close', () => {
    const v = $('key-dialog').returnValue;
    if (v === 'save') {
      state.key = $('key').value.trim();
      state.remembered = $('remember').checked;
      try {
        if (state.remembered && state.key) localStorage.setItem(LS_KEY, state.key);
        else localStorage.removeItem(LS_KEY);
      } catch (_) {}
    } else if (v === 'clear') {
      state.key = '';
      state.remembered = false;
      try { localStorage.removeItem(LS_KEY); } catch (_) {}
    }
    paintKey();
  });

  paintKey();
}

document.addEventListener('DOMContentLoaded', init);
