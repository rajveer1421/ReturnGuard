/* ReturnGuard UI: hash router, forms, live pipeline view, dashboard, evaluation, hero animation. */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ANGLES = ['front', 'back', 'side'];
const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (x, d = 1) => (x == null || isNaN(x)) ? '—' : (x * 100).toFixed(d) + '%';
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
};

const VERDICT = {
  ACCEPT: 'Accepted', HUMAN_REVIEW: 'Human review', REJECT: 'Rejected',
  RETAKE_REQUIRED: 'Retake photos', ERROR: 'Error', PROCESSING: 'Processing',
};
const FRAUD_LABEL = {
  substitution: 'Product substitution', label_removed: 'Label removed / unit swap', wardrobing: 'Wardrobing (worn and returned)',
  false_damage_claim: 'False damage claim', damage_after_delivery: 'Damaged after delivery',
};
const NODES = [
  ['intake', 'Intake', 'Background removal, quality gate, features'],
  ['policy', 'Policy agent', 'Return window and category rules'],
  ['history', 'Customer history agent', 'Prior returns set the cut-offs'],
  ['screen', 'Visual screen', 'Object-only DINOv2 + colour, no LLM'],
  ['triage', 'Triage router', 'Fast path, or call an agent?'],
  ['identity', 'Identity agent', 'Blind label read, compared in code', true],
  ['inspector', 'Visual inspector', 'Six photos, independent verdict', true],
  ['decide', 'Decision agent', 'Evidence-weighted risk score'],
];

/* ── API ─────────────────────────────────────────────────────────────── */
async function api(url, opts) {
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
  if (!res.ok || data.success === false) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* ── toast / busy ────────────────────────────────────────────────────── */
let toastTimer;
function toast(msg, type = '') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 4500);
}
function busy(on, title = '', sub = '') {
  $('#busy').classList.toggle('show', on);
  if (on) { $('#busy-title').textContent = title; $('#busy-sub').textContent = sub; }
}

/* ── theme ───────────────────────────────────────────────────────────── */
function initTheme() {
  const apply = t => {
    document.documentElement.setAttribute('data-theme', t);
    $('.i-sun').classList.toggle('hidden', t === 'light');
    $('.i-moon').classList.toggle('hidden', t !== 'light');
  };
  apply(document.documentElement.getAttribute('data-theme') || 'dark');
  $('#theme-toggle').addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    apply(next);
    store.set('rg-theme', next);
  });
}

/* ── router ──────────────────────────────────────────────────────────── */
const PAGES = ['home', 'deliver', 'return', 'result', 'dashboard', 'evaluation', 'architecture', 'about', 'account'];
let pollTimer = null;
let lastPage = null;

function route() {
  const [page, arg] = location.hash.replace(/^#/, '').split('/');
  const name = PAGES.includes(page) ? page : 'home';
  // after signing in, go back to the page that asked for it
  if (name === 'account' && ['deliver', 'return', 'dashboard'].includes(lastPage)) store.set('rg-after-signin', `#${lastPage}`);
  lastPage = name;
  $$('.page').forEach(p => p.classList.toggle('active', p.id === `page-${name}`));
  $$('[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === (name === 'result' ? 'return' : name)));
  $('#mobile-nav').classList.remove('open');
  window.scrollTo(0, 0);
  clearTimeout(pollTimer);
  scene.setVisible(name === 'home');
  if (name === 'dashboard') loadDashboard();
  if (name === 'evaluation') loadEvaluation();
  if (name === 'return') prefillReturn();
  if (name === 'deliver' || name === 'return') refreshMe();
  if (name === 'account') loadAccount();
  if (name === 'result' && /^\d+$/.test(arg || '')) openResult(Number(arg));
}

/* ── uploads & samples ───────────────────────────────────────────────── */
function setPreview(zone, file) {
  if (!file || !file.type.startsWith('image/')) return;
  zone.querySelector('img.preview')?.remove();
  zone.querySelector('.u-tag')?.remove();
  const img = document.createElement('img');
  img.className = 'preview';
  img.alt = '';
  img.src = URL.createObjectURL(file);
  zone.prepend(img);
  const tag = document.createElement('span');
  tag.className = 'u-tag';
  tag.textContent = zone.querySelector('.u-label').textContent;
  zone.append(tag);
  zone.classList.add('has-file');
}
function clearPreviews(form) {
  $$('.upload', form).forEach(z => { z.classList.remove('has-file'); z.querySelector('img.preview')?.remove(); z.querySelector('.u-tag')?.remove(); });
}
function initUploads() {
  $$('.upload').forEach(zone => {
    const input = $('input', zone);
    input.addEventListener('change', () => setPreview(zone, input.files[0]));
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('drag');
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const dt = new DataTransfer();
      dt.items.add(f);
      input.files = dt.files;
      setPreview(zone, f);
    });
  });
}
async function loadSample(set, formId) {
  const form = document.getElementById(formId);
  try {
    for (const a of ANGLES) {
      const blob = await (await fetch(`/static/samples/${set}_${a}.jpg`)).blob();
      const file = new File([blob], `${set}_${a}.jpg`, { type: 'image/jpeg' });
      const input = $(`input[name="${a}_image"]`, form);
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      setPreview(input.closest('.upload'), file);
    }
    if (formId === 'delivery-form') {
      $('#d-product').value = 'Portronics SoundDrum 1 speaker (blue)';
      $('#d-category').value = 'electronics';
    }
    toast('Sample photos loaded. Submit when ready.', 'success');
  } catch (e) {
    toast('Could not load the sample photos.', 'error');
  }
}
function initSamples() {
  $$('[data-load]').forEach(b => b.addEventListener('click', e => { e.preventDefault(); loadSample(b.dataset.load, b.dataset.form); }));
  $$('[data-sample]').forEach(a => a.addEventListener('click', () => setTimeout(() => loadSample(a.dataset.sample, 'delivery-form'), 60)));
}

/* ── delivery ────────────────────────────────────────────────────────── */
function initDelivery() {
  const form = $('#delivery-form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (ANGLES.some(a => !$(`input[name="${a}_image"]`, form).files.length)) return toast('Add all three photos (front, back, side).', 'error');
    busy(true, 'Registering delivery', 'Removing backgrounds, computing embeddings, and reading labels with the identity agent…');
    try {
      const data = await api('/api/deliveries', { method: 'POST', body: new FormData(form) });
      store.set('rg-last-order', data.order.order_id);
      renderDelivery(data.order, data.images);
      clearPreviews(form);
      form.reset();
      refreshMe();
      toast(`Delivery registered as order #${data.order.order_id}`, 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      busy(false);
    }
  });
}
function renderDelivery(o, images) {
  const fp = o.fingerprint;
  const ids = fp?.identifiers?.length
    ? fp.identifiers.map(i => `<span class="chip ${['serial_number', 'batch_number', 'barcode'].includes(i.kind) ? 'unit' : ''}" title="${esc(i.kind)} · ${esc(i.location)}">${esc(i.text)}</span>`).join('')
    : '<span class="dim">None visible</span>';
  const list = arr => arr?.length ? arr.map(x => esc(typeof x === 'string' ? x : `${x.description} (${x.view})`)).join('; ') : '<span class="dim">None</span>';
  $('#delivery-result').innerHTML = `
    <div class="card-title">Delivery fingerprint saved</div>
    <div class="order-badge"><span class="num mono">#${o.order_id}</span><span class="muted">order ID · ${esc(o.category)}</span></div>
    ${fp ? `<p>${esc(fp.product_description)}</p>` : `<p class="muted">Gemini could not read the labels for this delivery, so the label check will be skipped for this order. Reason: ${esc(o.fingerprint_error || 'unavailable')}</p>`}
    <dl class="kv">
      <dt>Identifiers</dt><dd><div class="chips">${ids}</div></dd>
      <dt>Marks</dt><dd>${list(fp?.distinctive_marks)}</dd>
      <dt>Accessories</dt><dd>${list(fp?.accessories)}</dd>
      <dt>Tags</dt><dd>${list(fp?.tags_attached)}</dd>
    </dl>
    <div class="thumbs">${ANGLES.map(a => `<div class="thumb"><span>${a}</span><img src="${images[a].cutout}" alt="${a} cut-out"></div>`).join('')}</div>
    <a class="btn btn-primary" style="width:100%;margin-top:16px" href="#return">Process a return for #${o.order_id} →</a>`;
}

/* ── return ──────────────────────────────────────────────────────────── */
function prefillReturn() {
  const last = store.get('rg-last-order');
  if (last && !$('#r-order').value) $('#r-order').value = last;
}
function initReturn() {
  const form = $('#return-form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!/^#?\d+$/.test($('#r-order').value.trim())) return toast('Enter the numeric order ID from the delivery.', 'error');
    if (ANGLES.some(a => !$(`input[name="${a}_image"]`, form).files.length)) return toast('Add all three photos (front, back, side).', 'error');
    busy(true, 'Uploading return photos', '');
    try {
      const data = await api('/api/returns', { method: 'POST', body: new FormData(form) });
      clearPreviews(form);
      $$('input[type=file]', form).forEach(i => { i.value = ''; });
      location.hash = `#result/${data.return_id}`;
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      busy(false);
    }
  });
}

/* ── result (live) ───────────────────────────────────────────────────── */
const LEVEL_BADGE = { good: 'b-ok', ok: 'b-ok', warn: 'b-warn', bad: 'b-bad', info: 'b-dim' };
const LEVEL_ICON = { good: '✓', ok: '✓', warn: '!', bad: '✕', info: 'i' };

async function openResult(id) {
  ['#res-verdict', '#res-identity', '#res-inspection', '#res-llm', '#res-views'].forEach(s => { $(s).innerHTML = ''; });
  $('#res-checks').innerHTML = '<p class="dim">Waiting for the agents…</p>';
  $('#res-gemini').innerHTML = '<p class="dim">Waiting for the agents…</p>';
  $('#res-evidence').innerHTML = '';
  $('#res-report').classList.add('hidden');
  $('#res-title').textContent = 'Verifying return…';
  const tick = async () => {
    try {
      const data = await api(`/api/returns/${id}`);
      renderResult(data);
      if (data.ret.status === 'PROCESSING' && location.hash === `#result/${id}`) pollTimer = setTimeout(tick, 1100);
    } catch (err) {
      $('#res-title').textContent = 'Return not found';
      $('#res-sub').textContent = err.message;
    }
  };
  tick();
}

function renderPipeline(ret) {
  const done = new Set(ret.status === 'PROCESSING' ? ret.progress : (ret.result?.route || ret.progress));
  const times = Object.fromEntries((ret.result?.trace || []).map(t => [t.node, t.ms]));
  const finished = ret.status !== 'PROCESSING';
  const firstPending = NODES.find(([k]) => !done.has(k) && !['identity', 'inspector', 'decide'].includes(k));
  $('#res-pipeline').innerHTML = NODES.map(([k, name, desc, llm]) => {
    let cls = '', st = 'waiting';
    if (done.has(k)) { cls = 'done'; st = times[k] != null ? `${(times[k] / 1000).toFixed(1)} s` : 'done'; }
    else if (finished) { cls = 'skipped'; st = 'not needed'; }
    else if ((firstPending && firstPending[0] === k) || (!firstPending && done.has('triage') && k === 'decide')) { cls = 'running'; st = 'running'; }
    return `<div class="pnode ${cls} ${llm ? 'llm' : ''}"><span class="ic"></span><span class="nm">${name}<small>${desc}</small></span><span class="st">${st}</span></div>`;
  }).join('');
}

function gauge(risk, band) {
  const r = Math.max(0, Math.min(100, risk ?? 0)) / 100;
  const a = Math.PI * (1 - r);
  const x = 100 + 80 * Math.cos(a), y = 100 - 80 * Math.sin(a);
  const color = risk == null ? 'var(--text-3)' : risk < 50 ? 'var(--ok)' : risk < 90 ? 'var(--warn)' : 'var(--bad)';
  return `<div class="gauge"><svg viewBox="0 0 200 110" aria-hidden="true">
      <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--surface-3)" stroke-width="14" stroke-linecap="round"/>
      ${r > 0 ? `<path d="M20 100 A80 80 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}" fill="none" stroke="${color}" stroke-width="14" stroke-linecap="round"/>` : ''}
    </svg><div class="gv mono" style="color:${color}">${risk ?? '—'}</div><div class="gk">${band ? esc(band.label) + ' · ' : ''}risk score out of 100</div></div>`;
}

function checkRow(c) {
  return `<div class="check"><span class="ck ${LEVEL_BADGE[c.level] || 'b-dim'}">${LEVEL_ICON[c.level] || 'i'}</span>
    <div><div class="ck-top"><b>${esc(c.name)}</b>${c.value ? `<span class="ck-val mono">${esc(c.value)}</span>` : ''}</div>
    <div class="ck-verdict">${esc(c.verdict)}</div>${c.detail ? `<div class="ck-detail">${esc(c.detail)}</div>` : ''}</div></div>`;
}

function geminiCard(g, returnId) {
  const status = { ran: 'Ran', unavailable: 'Unavailable', not_needed: 'Not needed' }[g.status] || g.status;
  return `<div class="check"><span class="ck ${LEVEL_BADGE[g.level] || 'b-dim'}">${g.status === 'ran' ? (LEVEL_ICON[g.level] || 'i') : '–'}</span>
    <div><div class="ck-top"><b>${esc(g.agent)}</b><span class="badge ${g.status === 'ran' ? 'b-ok' : g.status === 'unavailable' ? 'b-warn' : 'b-dim'}">${status}</span></div>
    ${g.status === 'ran' ? `<div class="ck-verdict">${esc(g.verdict)}</div>` : ''}
    ${g.detail ? `<div class="ck-detail">${esc(g.detail)}</div>` : ''}
    ${g.bullets?.length ? `<ul class="list" style="margin-top:6px">${g.bullets.map(b => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}
    ${g.note ? `<div class="ck-detail"><em>${esc(g.note)}</em></div>` : ''}
    ${g.can_request ? `<button class="btn btn-ghost btn-sm" style="margin-top:10px" data-second-opinion="${returnId}">Ask Gemini for a second opinion</button>` : ''}
    </div></div>`;
}

function renderResult({ ret, order, explained: x, delivery_images: dImg, return_images: rImg }) {
  $('#res-eyebrow').textContent = `Return #${ret.return_id} · Order #${ret.order_id}`;
  $('#res-sub').textContent = `${order.product_name || order.category} · customer ${order.customer_id} · reason: ${ret.reason.replace(/_/g, ' ')}`;
  renderPipeline(ret);

  if (ret.status === 'PROCESSING') {
    $('#res-title').textContent = 'Verifying return…';
    $('#res-verdict').innerHTML = `<div class="verdict"><div><div class="vlabel" style="color:var(--accent)">Analysing</div><div class="vhead">Agents are working through the evidence. This page updates live.</div></div><div class="spinner" style="margin:0"></div></div>`;
    return;
  }
  if (ret.status === 'ERROR') {
    $('#res-title').textContent = 'Pipeline error';
    $('#res-verdict').innerHTML = `<div class="verdict ERROR"><div><div class="vlabel">Error</div><div class="vhead">${esc(ret.error)}</div><div class="vmeta">The return was not decided. Resubmit it, or review manually.</div></div></div>`;
    return;
  }

  const r = ret.result, d = r.decision;
  $('#res-title').textContent = d.headline;
  $('#res-report').href = `/report/${ret.return_id}`;
  $('#res-report').classList.remove('hidden');
  $('#res-verdict').innerHTML = `
    <div class="verdict ${d.decision}">
      <div>
        <div class="vlabel">${VERDICT[d.decision]}</div>
        <div class="vhead">${esc(x.decision.sentence)}</div>
        ${x.decision.reasons.length ? `<p class="muted" style="margin-top:8px">Main reasons: ${x.decision.reasons.map(esc).join(' · ')}</p>` : ''}
        ${d.fraud_type ? `<span class="ftype">${esc(FRAUD_LABEL[d.fraud_type] || d.fraud_type)}</span>` : ''}
        <ul class="list" style="margin-top:12px">${d.actions.map(a => `<li>${esc(a)}</li>`).join('')}</ul>
        <div class="vmeta">${r.llm_call_count ? `${r.llm_call_count} Gemini call${r.llm_call_count === 1 ? '' : 's'}` : 'Decided by the free visual check, no Gemini call'}${d.thresholds ? ` · auto-approved below ${d.thresholds.accept_below}, rejected from ${d.thresholds.reject_from}` : ''}</div>
      </div>
      ${d.risk_score != null ? gauge(d.risk_score, x.decision.risk_band) : ''}
    </div>`;

  $('#res-checks').innerHTML = x.checks.map(checkRow).join('') || '<p class="muted">No checks ran.</p>';
  $('#res-gemini').innerHTML = x.gemini.map(g => geminiCard(g, ret.return_id)).join('');
  $$('[data-second-opinion]').forEach(b => b.addEventListener('click', () => requestSecondOpinion(Number(b.dataset.secondOpinion), b)));

  // technical details
  $('#res-evidence').innerHTML = x.evidence.length ? x.evidence.map(e => {
    const w = Math.min(Math.abs(e.weight) / 6, 1) * 50;
    const bar = e.weight >= 0 ? `left:50%;width:${w}%;background:var(--bad)` : `left:${50 - w}%;width:${w}%;background:var(--ok)`;
    return `<div class="ev-row"><div><div class="ev-src">${esc(e.source.replace(/_/g, ' '))} · ${esc(e.effect)}</div>${esc(e.finding)}</div>
      <div class="ev-bar"><i style="${bar}"></i></div><div class="ev-w ${e.weight > 0 ? 'pos' : e.weight < 0 ? 'neg' : ''}">${e.weight > 0 ? '+' : ''}${e.weight.toFixed(1)}</div></div>`;
  }).join('') + '<p class="dim" style="font-size:12px;margin-top:10px">Each finding adds (red, towards fraud) or subtracts (green, towards genuine) log-odds; the total goes through a sigmoid to give the 0–100 score.</p>'
    : `<p class="muted">${esc(d.summary)}</p>`;

  const idn = r.identity;
  $('#res-identity').innerHTML = idn?.locations ? `<div class="card-title" style="margin-top:22px">Identity agent · raw label readout</div>
    <table class="t"><tr><th>Location</th><th>Recorded at delivery</th><th>Read at return</th><th>Result</th></tr>
    ${idn.locations.map(l => `<tr><td>${esc(l.location)}<div class="dim" style="font-size:12px">${esc(l.view)} view</div></td>
      <td class="mono" style="font-size:12px">${(l.expected || (order.fingerprint?.identifiers || [])
        .filter(i => i.location === l.location && i.view === l.view).map(i => i.text)).map(esc).join('<br>') || '—'}</td>
      <td class="mono" style="font-size:12px">${esc(l.observed) || '—'}</td>
      <td><span class="badge ${['unit_match', 'model_match'].includes(l.status) ? 'b-ok' : ['missing', 'mismatch'].includes(l.status) ? 'b-bad' : 'b-dim'}">${esc(l.status.replace(/_/g, ' '))}</span></td></tr>`).join('')}
    </table>` : '';

  const ins = r.inspection;
  $('#res-inspection').innerHTML = ins ? `<div class="card-title" style="margin-top:22px">Visual inspector · raw output per view</div>
    <table class="t"><tr><th>View</th><th>Verdict</th><th>Differences</th></tr>
    ${ins.findings.map(f => `<tr><td>${esc(f.view)}</td><td>${esc(f.verdict.replace(/_/g, ' '))}</td><td>${esc(f.differences.join('; ')) || '—'}</td></tr>`).join('')}</table>` : '';

  $('#res-llm').innerHTML = `<div class="card-title" style="margin-top:22px">LLM calls (${r.llm_call_count})</div>
    ${r.llm_calls.length ? `<table class="t"><tr><th>Agent</th><th>Time</th><th>Tokens</th><th>Tries</th></tr>${r.llm_calls.map(c =>
      `<tr><td>${esc(c.agent.replace(/_/g, ' '))}${c.ok ? '' : ' <span class="badge b-bad">failed</span>'}</td><td class="mono">${c.latency_s}s</td><td class="mono">${c.input_tokens + c.output_tokens}</td><td class="mono">${c.attempts}</td></tr>`).join('')}</table>`
      : '<p class="muted">None. The free visual check settled this return on its own.</p>'}`;

  const q = r.quality || {};
  $('#res-views').innerHTML = `<div class="card-title" style="margin-top:4px">Delivered vs returned, view by view</div><div class="views">${ANGLES.map(a => {
    const v = x.views[a];
    const retImg = d.decision === 'RETAKE_REQUIRED' ? rImg[a].photo : rImg[a].cutout;
    return `<div class="view"><div class="pair"><div><span>DELIVERED</span><img src="${dImg[a].cutout}" alt="Delivered ${a}"></div>
      <div><span>RETURNED</span><img src="${retImg}" alt="Returned ${a}" onerror="this.src='${rImg[a].photo}'"></div></div>
      <div class="vfoot"><b>${a}</b>${q[a] && !q[a].ok ? `<span class="badge b-warn">${esc(q[a].problem)}</span>` : v ? `<span>
        <span class="badge ${LEVEL_BADGE[v.shape_level]}" title="${esc(v.shape_verdict)}">shape ${esc(v.shape)}</span>
        <span class="badge ${LEVEL_BADGE[v.colour_level]}">${esc(v.colour_verdict)}</span></span>` : ''}</div></div>`;
  }).join('')}</div>`;
}

async function requestSecondOpinion(returnId, btn) {
  btn.disabled = true;
  btn.textContent = 'Asking Gemini…';
  try {
    const { opinion } = await api(`/api/returns/${returnId}/second-opinion`, { method: 'POST' });
    toast(opinion.ok ? 'Gemini second opinion added.' : 'Gemini could not run right now; the reason is shown below.', opinion.ok ? 'success' : 'error');
  } catch (err) {
    toast(err.message, 'error');
  }
  openResult(returnId);
}

/* ── account ─────────────────────────────────────────────────────────── */
let me = null;

async function refreshMe() {
  try {
    me = await api('/api/auth/me');
  } catch (e) {
    me = { customer: null };
  }
  const c = me.customer;
  $('#nav-account').textContent = c ? c.customer_id : 'Sign in';
  $('#nav-account').classList.toggle('signed-in', !!c);
  $$('[data-who]').forEach(el => {
    el.classList.toggle('out', !c);
    el.innerHTML = c
      ? `<span class="badge b-ok">Signed in</span><span class="who-text">Customer <b class="mono">${esc(c.customer_id)}</b> · ${esc(c.email)}</span>`
      : `<span class="who-text">Sign in so this is linked to your customer ID and return history.</span><a class="btn btn-dark btn-sm" href="#account">Sign in</a>`;
  });
  const chips = $('#r-my-orders');
  if (chips) {
    chips.innerHTML = c && me.orders?.length
      ? '<span class="dim" style="font-size:12px">Your orders:</span>' + me.orders.map(o => `<button type="button" class="chip" data-pick="${o.order_id}">#${o.order_id} ${esc((o.product_name || o.category).slice(0, 24))}</button>`).join('')
      : '';
    $$('[data-pick]', chips).forEach(b => b.addEventListener('click', () => { $('#r-order').value = b.dataset.pick; }));
  }
  return me;
}

async function loadAccount() {
  await refreshMe();
  const c = me.customer;
  $('#acct-out').classList.toggle('hidden', !!c);
  $('#acct-in').classList.toggle('hidden', !c);
  if (!c) return;
  $('#acct-id').textContent = c.customer_id;
  $('#acct-details').innerHTML = `<dt>Email</dt><dd>${esc(c.email)}</dd><dt>Mobile</dt><dd class="mono">${esc(c.phone)}</dd><dt>Member since</dt><dd>${esc(c.created_at.slice(0, 10))}</dd>`;
  const p = me.profile, px = me.profile_explained;
  $('#acct-profile').innerHTML = historyCard(me.profile, me.profile_explained);
}

function historyCard(p, px) {
  return checkRow({ name: 'Return history', ...px }) +
    `<p class="dim" style="font-size:13px;margin-top:10px">${p.prior_returns} earlier return(s), ${p.prior_flagged} flagged. Your next return is auto-approved below risk ${p.accept_below} (standard: 50) and rejected from ${p.reject_from}.</p>`;
}

const AUTH_COPY = {
  login: ['Welcome back', 'Sign in with the email and mobile number you registered with.'],
  signup: ['Create your account', 'Get a customer ID that links your deliveries and returns.'],
};
const DEMO_ACCOUNT = { email: 'demo@returnguard.app', phone: '9000000001' };

function showAuthTab(tab) {
  $$('[data-auth-tab]').forEach(b => {
    const on = b.dataset.authTab === tab;
    b.classList.toggle('on', on);
    b.setAttribute('aria-selected', on);
  });
  $('#login-form').classList.toggle('hidden', tab !== 'login');
  $('#signup-form').classList.toggle('hidden', tab !== 'signup');
  [$('#auth-title').textContent, $('#auth-sub').textContent] = AUTH_COPY[tab];
}

async function authRequest(url, email, phone) {
  return api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, phone }) });
}

function afterSignIn(customer, verb) {
  toast(`${verb} · ${customer.customer_id}`, 'success');
  const next = store.get('rg-after-signin');
  if (next) { store.set('rg-after-signin', ''); location.hash = next; } else { loadAccount(); }
}

function initAccount() {
  $$('[data-auth-tab]').forEach(b => b.addEventListener('click', () => showAuthTab(b.dataset.authTab)));
  const submit = (formId, url, verb) => $(formId).addEventListener('submit', async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const { customer } = await authRequest(url, f.get('email'), f.get('phone'));
      e.target.reset();
      afterSignIn(customer, verb);
    } catch (err) {
      toast(err.message, 'error');
    }
  });
  submit('#signup-form', '/api/auth/signup', 'Account created');
  submit('#login-form', '/api/auth/login', 'Signed in');
  $('#demo-login').addEventListener('click', async () => {
    try {
      let customer;
      try {
        ({ customer } = await authRequest('/api/auth/login', DEMO_ACCOUNT.email, DEMO_ACCOUNT.phone));
      } catch (e) {
        ({ customer } = await authRequest('/api/auth/signup', DEMO_ACCOUNT.email, DEMO_ACCOUNT.phone));
      }
      afterSignIn(customer, 'Signed in to the demo account');
    } catch (err) {
      toast(err.message, 'error');
    }
  });
  $('#logout-btn').addEventListener('click', async () => {
    await api('/api/auth/logout', { method: 'POST' });
    toast('Signed out.', 'success');
    loadAccount();
  });
}

/* ── dashboard ───────────────────────────────────────────────────────── */
async function loadDashboard() {
  await refreshMe();
  const signedIn = !!me.customer;
  $('#dash-signed-out').classList.toggle('hidden', signedIn);
  $('#dash-body').classList.toggle('hidden', !signedIn);
  $('#dash-eyebrow').textContent = signedIn ? `Customer ${me.customer.customer_id}` : 'Your activity';
  if (!signedIn) return;
  try {
    const [{ stats: s, profile, profile_explained: px }, { returns }, { orders }] =
      await Promise.all([api('/api/stats'), api('/api/returns'), api('/api/orders')]);
    const by = s.by_status;
    const flagged = (by.HUMAN_REVIEW || 0) + (by.REJECT || 0);
    $('#dash-kpis').innerHTML = [
      [s.orders, 'My deliveries'], [s.returns, 'My returns'], [by.ACCEPT || 0, 'Auto-accepted'],
      [flagged, 'Flagged (review + reject)'], [s.decided_without_llm, 'Decided with no LLM call'],
    ].map(([v, k]) => `<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('');
    $('#dash-history').innerHTML = historyCard(profile, px);
    $('#dash-returns').innerHTML = returns.length ? `<table class="t"><tr><th>Return</th><th>Order</th><th>Product</th><th>Reason</th><th>Risk</th><th>Verdict</th></tr>
      ${returns.map(r => `<tr class="click" data-href="#result/${r.return_id}"><td class="mono">#${r.return_id}</td><td class="mono">#${r.order_id}</td>
        <td>${esc(r.product_name || r.category)}</td><td>${esc(r.reason.replace(/_/g, ' '))}</td><td class="mono">${r.risk_score ?? '—'}</td>
        <td><span class="pill ${r.status}">${VERDICT[r.status] || r.status}</span></td></tr>`).join('')}</table>`
      : '<div class="empty">No returns yet. Register a delivery, then process a return.</div>';
    $('#dash-orders').innerHTML = orders.length ? `<table class="t"><tr><th>Order</th><th>Delivered</th><th>Product</th><th>Category</th><th>Fingerprint</th><th>Last return</th></tr>
      ${orders.map(o => `<tr><td class="mono">#${o.order_id}</td><td>${esc(o.delivered_at.slice(0, 10))}</td><td>${esc(o.product_name || '—')}</td><td>${esc(o.category)}</td>
        <td>${o.has_fingerprint ? '<span class="badge b-ok">saved</span>' : '<span class="badge b-dim">visual only</span>'}</td>
        <td>${o.last_return_status ? `<span class="pill ${o.last_return_status}">${VERDICT[o.last_return_status] || o.last_return_status}</span>` : '—'}</td></tr>`).join('')}</table>`
      : '<div class="empty">No deliveries yet.</div>';
    $$('#dash-returns tr.click').forEach(tr => tr.addEventListener('click', () => { location.hash = tr.dataset.href; }));
  } catch (err) {
    toast(err.message, 'error');
  }
}

/* ── evaluation ──────────────────────────────────────────────────────── */
let evalCache = null;
async function getEval(pairs = false) {
  if (evalCache && (!pairs || evalCache.per_pair)) return evalCache;
  evalCache = (await api(`/api/metrics${pairs ? '?pairs=1' : ''}`)).results;
  return evalCache;
}

let stressCache;
async function getStress() {
  if (stressCache === undefined) {
    try { stressCache = await api('/api/stress'); } catch (e) { stressCache = null; }
  }
  return stressCache;
}
const num = n => Number(n).toLocaleString('en-US');

async function loadHomeMetrics() {
  try {
    const [r, s] = await Promise.all([getEval(), getStress()]);
    const m = r.metrics, a = r.agentic;
    const p = s?.pooled;
    const vals = { f0_5: m.f0_5.toFixed(3), precision: pct(p ? p.precision : m.precision), recall: pct(m.recall),
                   no_llm: a.decided_without_llm_pct + '%', calls: a.llm_calls_per_return };
    $$('#home-metrics [data-m]').forEach(el => { el.textContent = vals[el.dataset.m]; });
    const prec = p
      ? ` Precision ${pct(p.precision)}: ${num(p.tp)} of ${num(p.flags)} flags were fraud across ${p.conditions} photo conditions (95% interval ${pct(p.precision_ci[0])}–${pct(p.precision_ci[1])}); ${m.tp}/${m.tp + m.fp} on the main set.`
      : (m.precision_ci ? ` Precision 95% interval ${pct(m.precision_ci[0], 0)}–${pct(m.precision_ci[1], 0)}.` : '');
    const held = r.held_out ? ` On items added after tuning was frozen: F0.5 ${r.held_out.f0_5.toFixed(3)} (${r.held_out.pairs} pairs).` : '';
    $('#home-metrics-note').innerHTML = `F0.5, recall and LLM use measured on ${r.dataset.pairs} labelled delivery/return pairs (${r.dataset.genuine} genuine, ${r.dataset.fraud} fraud, ${r.dataset.items} physical items) with <span class="mono">${esc(r.model)}</span>.${prec}${held} <a href="#evaluation">How these are measured →</a>`;
  } catch (e) {
    $('#home-metrics-note').textContent = 'No evaluation results yet. Run: python scripts/evaluate.py';
  }
}

async function loadEvaluation() {
  const body = $('#eval-body');
  let r;
  try { r = await getEval(true); } catch (e) {
    body.innerHTML = `<div class="note">No evaluation results yet. Run <span class="code">python scripts/evaluate.py</span>.</div>`;
    return;
  }
  const s = await getStress();
  const sp = s?.pooled;
  const m = r.metrics, a = r.agentic;
  const kpi = (v, k, d, hero) => `<div class="kpi ${hero ? 'hero-kpi' : ''}"><div class="v">${v}</div><div class="k">${k}</div>${d ? `<div class="d">${d}</div>` : ''}</div>`;
  const cell = (lab, dec) => {
    const n = (r.confusion[lab] || {})[dec] || 0;
    const good = (lab === 'genuine' && dec === 'ACCEPT') || (lab === 'fraud' && dec !== 'ACCEPT');
    return `<div class="c ${n ? (good ? 'good' : 'badc') : ''}">${n}<small>${good ? 'correct' : 'error'}</small></div>`;
  };
  const misses = (r.per_pair || []).filter(p => (p.decision !== 'ACCEPT') !== p.is_fraud);
  const maxRoute = Math.max(...Object.values(a.routes));
  const ci = c => c ? `95% interval ${pct(c[0], 0)}–${pct(c[1], 0)}` : '';
  const DECISIONS = ['ACCEPT', 'HUMAN_REVIEW', 'REJECT', 'RETAKE_REQUIRED'];
  body.innerHTML = `
    <div class="kpis">
      ${kpi(m.f0_5.toFixed(3), 'F0.5 score', 'precision-weighted (β = 0.5)', true)}
      ${sp ? kpi(pct(sp.precision), 'Precision, stress-tested', `${num(sp.tp)} of ${num(sp.flags)} flags were fraud · 95% interval ${pct(sp.precision_ci[0])}–${pct(sp.precision_ci[1])} · main set ${m.tp}/${m.tp + m.fp}`)
           : kpi(pct(m.precision), 'Precision', `${m.tp} of ${m.tp + m.fp} flags were fraud · ${ci(m.precision_ci)}`)}
      ${kpi(pct(m.recall), 'Recall', `${m.tp} of ${m.tp + m.fn} frauds flagged · ${ci(m.recall_ci)}`)}
      ${kpi(m.f1.toFixed(3), 'F1 score')}
      ${kpi(pct(m.false_rejection_rate), 'Genuine returns flagged', `${m.fp} of ${m.fp + m.tn} · ${ci(m.false_rejection_rate_ci)}`)}
    </div>
    ${r.held_out ? `<div class="section-head" style="margin:8px 0 14px"><span class="eyebrow">Held-out test · ${r.held_out.items.map(esc).join(' + ')}</span></div>
    <div class="kpis">
      ${kpi(r.held_out.f0_5.toFixed(3), 'F0.5 on held-out items', `${r.held_out.pairs} pairs (${r.held_out.genuine} genuine, ${r.held_out.fraud} fraud)`, true)}
      ${kpi(pct(r.held_out.precision), 'Precision', `${r.held_out.tp}/${r.held_out.tp + r.held_out.fp} · ${ci(r.held_out.precision_ci)}`)}
      ${kpi(pct(r.held_out.recall), 'Recall', `${r.held_out.tp}/${r.held_out.tp + r.held_out.fn} · ${ci(r.held_out.recall_ci)}`)}
      ${kpi(pct(r.held_out.false_rejection_rate), 'Genuine flagged', `${r.held_out.fp} of ${r.held_out.fp + r.held_out.tn}`)}
      ${kpi('frozen', 'Thresholds & weights', 'not changed after these items were added')}
    </div>` : ''}
    <div class="note" style="margin-bottom:20px"><b>Positive class = fraud.</b> A return is "flagged" when it is not auto-accepted (human review, reject${r.retakes?.count ? `, or one of the ${r.retakes.count} retake requests` : ''}). F0.5 weights precision twice as much as recall, because wrongly blocking a genuine customer costs trust. The 95% intervals show how much a small test set can say: a perfect score on a few dozen pairs is still compatible with a noticeably lower true rate.</div>

    <div class="result-grid">
      <div class="card"><div class="card-title">Ablation · what each stage adds (F0.5)</div><div class="bars">
        ${r.ablations.map(x => `<div class="bar-row"><span>${esc(x.name)}<div class="dim" style="font-size:12px">${esc(x.detail)}</div></span>
          <div class="track"><div class="fill" style="width:${x.f0_5 * 100}%"></div></div><b class="mono">${x.f0_5.toFixed(3)}</b></div>`).join('')}
        </div>
        <table class="t" style="margin-top:12px"><tr><th>System</th><th>Precision</th><th>Recall</th><th>LLM calls</th></tr>
        ${r.ablations.map(x => `<tr><td>${esc(x.name)}</td><td class="mono">${pct(x.precision)}</td><td class="mono">${pct(x.recall)}</td><td class="mono">${x.llm_calls_per_return ?? '—'}</td></tr>`).join('')}</table>
      </div>
      <div class="card"><div class="card-title">Confusion matrix · full pipeline</div>
        <div class="confusion"><div></div><div class="h">Accept</div><div class="h">Human review</div><div class="h">Reject</div><div class="h">Retake</div>
          <div class="h">Genuine (${r.dataset.genuine})</div>${DECISIONS.map(d => cell('genuine', d)).join('')}
          <div class="h">Fraud (${r.dataset.fraud})</div>${DECISIONS.map(d => cell('fraud', d)).join('')}
        </div>
        <table class="t" style="margin-top:16px"><tr><th>Pair type</th><th>Accept</th><th>Review</th><th>Reject</th><th>Retake</th></tr>
        ${Object.entries(r.by_pair_type).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, ' '))}</td>${DECISIONS.map(d => `<td class="mono">${v[d] || 0}</td>`).join('')}</tr>`).join('')}</table>
      </div>
    </div>

    ${sp ? robustness(s, kpi) : ''}

    <div class="section-head" style="margin:28px 0 16px"><span class="eyebrow">Agentic metrics</span></div>
    <div class="kpis">
      ${kpi(a.llm_calls_per_return, 'LLM calls per return', `v1 made up to ${a.v1_llm_calls_per_return_upper_bound}`, true)}
      ${kpi(a.decided_without_llm_pct + '%', 'Decided with no LLM call')}
      ${kpi(a.schema_valid_first_try_pct + '%', 'Valid structured output, 1st try', `${a.total_retries} retries`)}
      ${kpi(`${a.identity_agent_accuracy.correct}/${a.identity_agent_accuracy.runs}`, 'Identity agent correct')}
      ${kpi(`${a.inspector_accuracy.correct}/${a.inspector_accuracy.runs}`, 'Visual inspector correct')}
    </div>
    <div class="result-grid">
      <div class="card"><div class="card-title">Routes through the graph</div><div class="bars">
        ${Object.entries(a.routes).map(([k, v]) => `<div class="bar-row"><span class="mono" style="font-size:12.5px">${esc(k)}</span><div class="track"><div class="fill" style="width:${v / maxRoute * 100}%"></div></div><b class="mono">${v}</b></div>`).join('')}
      </div></div>
      <div class="card"><div class="card-title">Cost &amp; latency</div><dl class="kv">
        <dt>Tokens / return</dt><dd class="mono">${a.tokens_per_return}</dd>
        <dt>Cost / 1,000 returns</dt><dd class="mono">${a.est_cost_usd_per_1000_returns != null ? '$' + a.est_cost_usd_per_1000_returns : 'n/a'} <span class="dim">(Gemini list price)</span></dd>
        <dt>Latency / return</dt><dd class="mono">mean ${a.latency_s_per_return.mean}s · max ${a.latency_s_per_return.p_max}s</dd>
        ${Object.entries(a.agents).map(([k, v]) => `<dt>${esc(k.replace(/_/g, ' '))}</dt><dd class="mono">${v.calls} calls · ${v.mean_latency_s}s · ${v.mean_tokens} tok</dd>`).join('')}
      </dl></div>
    </div>

    <div class="section-head" style="margin:28px 0 16px"><span class="eyebrow">Error analysis &amp; honest caveats</span></div>
    <div class="card" style="margin-bottom:20px"><div class="card-title">Misclassified pairs (${misses.length})</div>
      ${misses.length ? `<table class="t"><tr><th>Pair</th><th>Truth</th><th>Decision</th><th>Strongest evidence</th></tr>${misses.map(p => `<tr><td>${esc(p.delivery_item)} → ${esc(p.return_item)}<div class="dim" style="font-size:12px">${esc(p.pair_type.replace(/_/g, ' '))}</div></td>
        <td>${p.is_fraud ? 'fraud' : 'genuine'}</td><td><span class="pill ${p.decision}">${VERDICT[p.decision]}</span></td>
        <td style="font-size:13px">${p.evidence.slice().sort((x, y) => Math.abs(y.weight) - Math.abs(x.weight)).slice(0, 2).map(e => `${esc(e.finding)} (${e.weight > 0 ? '+' : ''}${e.weight.toFixed(1)})`).join('<br>')}</td></tr>`).join('')}</table>
      <p class="muted" style="margin-top:12px;font-size:14px">Each row shows the two strongest pieces of evidence behind the wrong decision. Fixes suggested by these errors are
        <b>not</b> applied before this run: they come from the same data, so they need new items to be validated honestly. Full per-pair log: <span class="code">results/eval_pairs.csv</span>.</p>`
      : '<p class="muted">None.</p>'}
    </div>
    ${r.real_recapture ? `<div class="card" style="margin-bottom:20px"><div class="card-title">Real re-photographs vs simulated</div>
      <table class="t"><tr><th>Genuine pairs</th><th>Pairs</th><th>Auto-accepted</th><th>Flagged</th></tr>
      ${r.real_recapture.map(x => `<tr><td>${esc(x.kind)}</td><td class="mono">${x.pairs}</td><td class="mono">${x.accepted}</td><td class="mono">${x.flagged}</td></tr>`).join('')}</table>
      <p class="muted" style="margin-top:10px;font-size:14px">Simulated re-captures re-use the delivery photo, so they are easy. Real ones are separate photo sessions (new place, angle and lighting) and are the honest test.</p></div>` : ''}
    <div class="note"><b>Read these numbers with care.</b> ${esc(r.dataset.note)} ${r.dataset.pairs} pairs is small, and the thresholds and weights were chosen by looking at the first 6 items${r.held_out ? ' (the held-out items above were added only after that)' : ''}.
      Reproduce with <span class="code">python scripts/evaluate.py</span>. Generated ${esc(r.generated_at)} with <span class="mono">${esc(r.model)}</span>.</div>`;
}

function robustness(s, kpi) {
  const p = s.pooled, sum = s.summary;
  const byLabel = {};
  s.conditions.forEach(c => { (byLabel[c.label] = byLabel[c.label] || {})[c.level] = c; });
  const lvl = c => c ? `<td class="mono ${c.fp >= c.genuine / 2 ? 'bad-t' : ''}">${c.fp}/${c.genuine}</td><td class="mono">${pct(c.precision)}</td>` : '<td>—</td><td>—</td>';
  return `
    <div class="section-head" style="margin:28px 0 16px"><span class="eyebrow">Robustness · precision under bad photos</span></div>
    <div class="kpis kpis-3">
      ${kpi(pct(p.precision), 'Pooled precision', `${num(p.tp)} of ${num(p.flags)} flags were fraud · 95% interval ${pct(p.precision_ci[0])}–${pct(p.precision_ci[1])}`, true)}
      ${kpi(pct(p.recall), 'Recall', `every fraud flagged in all ${p.conditions} conditions`)}
      ${kpi(`${sum.genuine_flagged_by_local_stage}/${sum.genuine_returns_tested}`, 'Genuine returns flagged', `${sum.hard_false_rejections} hard rejections · ${sum.sent_to_gemini} sent to Gemini · ${sum.retakes} retakes`)}
    </div>
    <div class="card" style="margin-bottom:20px"><div class="card-title">Each return photo distorted ${p.conditions / 2} ways at two strengths (${num(p.pairs)} pairs)</div>
      <table class="t"><tr><th>Condition</th><th>Mild · genuine flagged</th><th>Precision</th><th>Strong · genuine flagged</th><th>Precision</th></tr>
      ${Object.entries(byLabel).map(([k, v]) => `<tr><td>${esc(k)}</td>${lvl(v.mild)}${lvl(v.strong)}</tr>`).join('')}</table>
      <p class="muted" style="margin-top:12px;font-size:14px">Only the local stage (DINOv2 + colour) was run, so a genuine return that would be sent to Gemini counts as a false flag here. That makes these figures a worst case.
        The weak spots are strong warm or cool light, very heavy JPEG compression and photos taken from far away. Colour-cast correction and a compression quality gate are the planned fixes.
        Precision also depends on how common fraud is: this test has 7 fraud pairs per genuine one, while a real store might see around 15% fraud, which would give a much lower precision for the local stage alone.
        Reproduce with <span class="code">python scripts/stress_test_precision.py</span>.</p>
    </div>`;
}

/* ── hero animation ──────────────────────────────────────────────────── */
const scene = (() => {
  const el = $('#scene');
  if (!el) return { setVisible() {} };
  const steps = [
    { t: 700, cap: 'A delivery agent brings a new speaker to the customer.', day: 'Day 0 · Delivery' },
    { t: 1900, cap: 'At the door, before handing it over…' },
    { t: 3400, cap: 'the agent photographs it in ReturnGuard: 3 views, label read, fingerprint saved.' },
    { t: 2400, cap: 'The customer receives the blue speaker.' },
    { t: 2600, cap: 'The customer asks for a return and hands back… a speaker.', day: 'Day 5 · Return pickup', fade: true },
    { t: 3600, cap: 'The agent scans it: same model, but the colour is off and the batch label is gone.' },
    { t: 4400, cap: 'Fraud caught at the doorstep. The refund is held and the seller gets the evidence.' },
  ];
  let i = 0, timer = null, playing = !REDUCED_MOTION, visible = true;
  const dots = $('#scene-dots');
  dots.innerHTML = steps.map((_, k) => `<button aria-label="Show step ${k + 1}"></button>`).join('');

  function show(n) {
    i = n;
    el.dataset.step = n;
    $('#scene-agent').classList.toggle('walking', n <= 1);
    $('#scene-caption').textContent = steps[n].cap;
    const day = steps.slice(0, n + 1).reverse().find(s => s.day);
    $('#scene-day').textContent = day.day;
    $$('button', dots).forEach((b, k) => b.classList.toggle('on', k === n));
  }
  function schedule() {
    clearTimeout(timer);
    if (playing && visible && !document.hidden) timer = setTimeout(next, steps[i].t);
  }
  function next() {
    const n = (i + 1) % steps.length;
    if (steps[n].fade) {
      el.classList.add('transition');
      timer = setTimeout(() => { show(n); el.classList.remove('transition'); schedule(); }, 1400);
    } else {
      show(n);
      schedule();
    }
  }
  $$('button', dots).forEach((b, k) => b.addEventListener('click', () => { show(k); schedule(); }));
  $('#scene-toggle').addEventListener('click', () => {
    playing = !playing;
    $('#scene-toggle').textContent = playing ? 'Pause' : 'Play';
    schedule();
  });
  document.addEventListener('visibilitychange', schedule);
  show(REDUCED_MOTION ? 6 : 0);
  if (REDUCED_MOTION) $('#scene-toggle').textContent = 'Play';
  schedule();
  return { setVisible(v) { visible = v; schedule(); } };
})();

/* ── init ────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initUploads();
  initSamples();
  initDelivery();
  initReturn();
  initAccount();
  refreshMe();
  $('#menu-btn').addEventListener('click', () => $('#mobile-nav').classList.toggle('open'));
  $('#dash-refresh').addEventListener('click', loadDashboard);
  window.addEventListener('hashchange', route);
  route();
  loadHomeMetrics();
});
