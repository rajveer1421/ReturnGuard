/* ═══════════════════════════════════════════════════════════════
   ReturnGuard — Frontend Application Logic
   ═══════════════════════════════════════════════════════════════ */

'use strict';

// ── State ──────────────────────────────────────────────────────
let currentSection = 'home';
let pipelineTimer  = null;
let currentPipelineStage = 0;

// ── Navigation ─────────────────────────────────────────────────
function showSection(id) {
    document.querySelectorAll('.page-section').forEach(s => {
        s.classList.remove('active');
        s.style.display = 'none';
    });

    const section = document.getElementById(id);
    if (!section) return;
    section.style.display = 'block';
    // small timeout so display:block takes effect before class (transition hook)
    requestAnimationFrame(() => section.classList.add('active'));

    // Nav active state — results is not in nav so clear all
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    const link = document.querySelector(`.nav-link[data-section="${id}"]`);
    if (link) link.classList.add('active');

    window.scrollTo({ top: 0, behavior: 'smooth' });
    currentSection = id;

    // Load data when entering dashboard
    if (id === 'dashboard') loadOrders();
}

function initNavigation() {
    document.querySelectorAll('.nav-link').forEach(btn => {
        btn.addEventListener('click', () => {
            const section = btn.dataset.section;
            if (section) {
                showSection(section);
                // close mobile nav
                document.getElementById('mobile-nav').classList.remove('open');
            }
        });
    });

    const mobileBtn = document.getElementById('mobile-menu-btn');
    const mobileNav = document.getElementById('mobile-nav');
    if (mobileBtn && mobileNav) {
        mobileBtn.addEventListener('click', () => mobileNav.classList.toggle('open'));
    }
}

// ── Flash Messages ──────────────────────────────────────────────
function showFlash(type, msg) {
    const el   = document.getElementById(`flash-${type}`);
    const text = document.getElementById(`flash-${type}-text`);
    if (!el || !text) return;
    text.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 4500);
}

// ── Processing Overlay ──────────────────────────────────────────
function showProcessing(mode = 'return') {
    const overlay = document.getElementById('processing-overlay');
    const stages  = document.getElementById('pipeline-stages');

    resetPipelineStages();

    if (mode === 'delivery') {
        document.getElementById('processing-title').textContent = 'Registering Delivery';
        document.getElementById('processing-sub').textContent   = 'Removing background and generating DINOv2 embeddings…';
        if (stages) stages.style.display = 'none';
    } else {
        document.getElementById('processing-title').textContent = 'Analyzing Return';
        document.getElementById('processing-sub').textContent   = 'Running the fraud detection pipeline…';
        if (stages) stages.style.display = 'flex';
        startPipelineAnimation();
    }

    overlay.classList.add('active');
}

function hideProcessing() {
    const overlay = document.getElementById('processing-overlay');
    overlay.classList.remove('active');
    clearPipelineAnimation();
}

function resetPipelineStages() {
    document.querySelectorAll('.stage').forEach(s => {
        s.classList.remove('active', 'done');
        const dot = s.querySelector('.stage-dot');
        if (dot) { dot.className = 'stage-dot pending'; }
        const span = s.querySelector('span');
        if (span) span.style.textDecoration = '';
    });
    currentPipelineStage = 0;
}

const STAGE_DURATIONS = [3000, 5000, 3000, 20000, 8000, 2000]; // ms per stage

function startPipelineAnimation() {
    advanceStage(0);
}

function advanceStage(index) {
    const stages = document.querySelectorAll('.stage');
    if (index >= stages.length) return;

    // Mark previous done
    if (index > 0) {
        const prev = stages[index - 1];
        prev.classList.remove('active');
        prev.classList.add('done');
        const prevDot = prev.querySelector('.stage-dot');
        if (prevDot) prevDot.className = 'stage-dot done';
    }

    // Activate current
    const cur = stages[index];
    cur.classList.add('active');
    const dot = cur.querySelector('.stage-dot');
    if (dot) dot.className = 'stage-dot running';

    currentPipelineStage = index;

    pipelineTimer = setTimeout(() => {
        advanceStage(index + 1);
    }, STAGE_DURATIONS[index] || 5000);
}

function clearPipelineAnimation() {
    if (pipelineTimer) {
        clearTimeout(pipelineTimer);
        pipelineTimer = null;
    }
}

// ── Upload Zones ───────────────────────────────────────────────
function initUploadZones() {
    document.querySelectorAll('.upload-zone').forEach(zone => {
        const input = zone.querySelector('input[type="file"]');
        if (!input) return;

        input.addEventListener('change', () => {
            if (input.files && input.files[0]) {
                showFilePreview(zone, input.files[0]);
            }
        });

        zone.addEventListener('dragover', e => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });
        zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
        zone.addEventListener('drop', e => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                const dt = new DataTransfer();
                dt.items.add(e.dataTransfer.files[0]);
                input.files = dt.files;
                showFilePreview(zone, e.dataTransfer.files[0]);
            }
        });
    });
}

function showFilePreview(zone, file) {
    if (!file.type.startsWith('image/')) return;

    // Remove old preview if any
    const old = zone.querySelector('.preview-img');
    if (old) old.remove();
    const oldOverlay = zone.querySelector('.preview-overlay');
    if (oldOverlay) oldOverlay.remove();

    const reader = new FileReader();
    reader.onload = e => {
        const img = document.createElement('img');
        img.className = 'preview-img';
        img.src = e.target.result;
        img.alt = 'Preview';
        zone.prepend(img);

        const overlay = document.createElement('div');
        overlay.className = 'preview-overlay';
        overlay.textContent = 'Click to replace';
        zone.appendChild(overlay);

        zone.classList.add('has-file');
    };
    reader.readAsDataURL(file);
}

// ── Delivery Form ──────────────────────────────────────────────
function initDeliveryForm() {
    const form = document.getElementById('delivery-form');
    if (!form) return;

    form.addEventListener('submit', async e => {
        e.preventDefault();

        const formData = new FormData(form);
        showProcessing('delivery');

        try {
            const res  = await fetch('/submit_delivery_image', { method: 'POST', body: formData });
            const data = await res.json();

            hideProcessing();

            if (!data.success) {
                showFlash('error', data.error || 'Failed to register delivery.');
                return;
            }

            // Show success block
            document.getElementById('delivery-order-id-display').textContent = data.order_id;
            document.getElementById('delivery-success').style.display = 'flex';
            showFlash('success', `Delivery registered. Order ID: ${data.order_id}`);
            form.reset();
            // Clear previews
            document.querySelectorAll('#register .upload-zone').forEach(z => {
                z.classList.remove('has-file');
                const img = z.querySelector('.preview-img');
                if (img) img.remove();
                const ov = z.querySelector('.preview-overlay');
                if (ov) ov.remove();
            });

        } catch (err) {
            hideProcessing();
            showFlash('error', 'Network error — could not reach server.');
        }
    });
}

// ── Return Form ────────────────────────────────────────────────
function initReturnForm() {
    const form = document.getElementById('return-form');
    if (!form) return;

    form.addEventListener('submit', async e => {
        e.preventDefault();

        const orderId = document.getElementById('return-order-id').value.trim();
        if (!orderId) { showFlash('error', 'Order ID is required.'); return; }

        const formData = new FormData(form);
        formData.set('order_id', orderId);

        showProcessing('return');

        try {
            const res  = await fetch('/submit_return_images', { method: 'POST', body: formData });
            const data = await res.json();

            hideProcessing();

            if (!data.success) {
                showFlash('error', data.error || 'Failed to process return.');
                return;
            }

            displayResults(data);
            showSection('results');

        } catch (err) {
            hideProcessing();
            showFlash('error', 'Network error — pipeline call failed. Check the server is running.');
        }
    });
}

// ── Results Display ────────────────────────────────────────────
function displayResults(data) {
    const status = data.status || 'Unknown';

    // ── Verdict banner ──
    const banner = document.getElementById('verdict-banner');
    const labelEl = document.getElementById('verdict-label');
    const subEl   = document.getElementById('verdict-sub');
    const orderEl = document.getElementById('verdict-order-label');

    banner.classList.remove('v-accepted', 'v-review', 'v-rejected');

    const statusLower = status.toLowerCase();
    let bannerClass, verdictText, verdictSub;

    if (statusLower.includes('accepted')) {
        bannerClass = 'v-accepted';
        verdictText = statusLower.includes('vlm') ? 'VLM Accepted' : 'Return Accepted';
        verdictSub  = statusLower.includes('vlm')
            ? 'VLM agents confirmed the product matches. Refund can proceed.'
            : 'Embedding similarity was conclusive — no VLM review required. Refund can proceed.';
    } else if (statusLower.includes('human') || statusLower.includes('review')) {
        bannerClass = 'v-review';
        verdictText = 'Human Review Required';
        verdictSub  = 'VLM agents reached ambiguous conclusions. Full evidence packaged for human review.';
    } else {
        bannerClass = 'v-rejected';
        verdictText = 'Return Rejected';
        verdictSub  = 'Multiple VLM agents identified product-specific discrepancies. Refund blocked.';
    }

    banner.classList.add(bannerClass);
    labelEl.textContent = verdictText;
    subEl.textContent   = verdictSub;
    orderEl.textContent = `Order #${data.order_id || '—'}`;

    // ── Similarity gauge ──
    const avgScore = parseFloat(data.avg_score) || 0;
    animateSimGauge(avgScore);
    document.getElementById('sim-gauge-number').textContent = (avgScore * 100).toFixed(1) + '%';
    document.getElementById('sub-front').textContent = data.front_score != null ? (data.front_score * 100).toFixed(1) + '%' : '—';
    document.getElementById('sub-back').textContent  = data.back_score  != null ? (data.back_score  * 100).toFixed(1) + '%' : '—';
    document.getElementById('sub-side').textContent  = data.side_score  != null ? (data.side_score  * 100).toFixed(1) + '%' : '—';

    // Color subscores
    colorSubscore('sub-front', data.front_score);
    colorSubscore('sub-back',  data.back_score);
    colorSubscore('sub-side',  data.side_score);

    // ── Risk score gauge ──
    const riskScore = (data.risk_score !== undefined && data.risk_score !== -1) ? data.risk_score : null;
    if (riskScore !== null) {
        animateRiskGauge(riskScore);
        document.getElementById('risk-gauge-number').textContent = riskScore;
        let riskLabel;
        if (riskScore < 50)       riskLabel = 'LOW RISK';
        else if (riskScore < 90)  riskLabel = 'ELEVATED';
        else                      riskLabel = 'CRITICAL';
        document.getElementById('risk-gauge-label').textContent = riskLabel;
    } else {
        document.getElementById('risk-gauge-number').textContent = '—';
        document.getElementById('risk-gauge-label').textContent  = 'N/A';
    }

    // ── View cards ──
    const isEmbeddingOnly = statusLower.includes('return_accepted') || 
                            (statusLower.includes('accepted') && !statusLower.includes('vlm'));

    if (isEmbeddingOnly) {
        // No VLM was run — show informational message
        ['front', 'back', 'side'].forEach(view => {
            const bodyEl  = document.getElementById(`vcard-${view}-body`);
            const scoreEl = document.getElementById(`vcard-${view}-score`);
            const card    = document.getElementById(`card-${view}`);
            const score   = data[`${view}_score`];
            if (scoreEl) {
                scoreEl.textContent = score != null ? (score * 100).toFixed(1) + '%' : '—';
                scoreEl.style.color = getScoreColor(score);
            }
            if (bodyEl) bodyEl.innerHTML = '<p class="skip-msg">Embedding similarity was conclusive — VLM analysis was not required for this view.</p>';
            setCardScoreClass(card, score);
        });
    } else {
        renderViewCard('front', data.front_review, data.front_score);
        renderViewCard('back',  data.back_review,  data.back_score);
        renderViewCard('side',  data.side_review,  data.side_score);
    }

    // ── Main review ──
    const mrBody = document.getElementById('main-review-body');
    if (mrBody) {
        mrBody.innerHTML = data.main_review ? renderMarkdown(data.main_review) : '<p class="review-placeholder">No synthesis available.</p>';
    }
}

function renderViewCard(view, reviewText, score) {
    const scoreEl = document.getElementById(`vcard-${view}-score`);
    const bodyEl  = document.getElementById(`vcard-${view}-body`);
    const card    = document.getElementById(`card-${view}`);

    if (scoreEl) {
        scoreEl.textContent = score != null ? (score * 100).toFixed(1) + '%' : '—';
        scoreEl.style.color = getScoreColor(score);
    }

    if (bodyEl) {
        bodyEl.innerHTML = reviewText
            ? renderMarkdown(reviewText)
            : '<p class="review-placeholder">No review available for this view.</p>';
    }

    setCardScoreClass(card, score);
}

function setCardScoreClass(card, score) {
    if (!card) return;
    card.classList.remove('score-high', 'score-mid', 'score-low');
    if      (score >= 0.75) card.classList.add('score-high');
    else if (score >= 0.55) card.classList.add('score-mid');
    else if (score != null) card.classList.add('score-low');
}

function colorSubscore(id, score) {
    const el = document.getElementById(id);
    if (el) el.style.color = getScoreColor(score);
}

function getScoreColor(score) {
    if (score == null) return 'var(--text-muted)';
    if (score >= 0.75) return 'var(--verified)';
    if (score >= 0.55) return 'var(--caution)';
    return 'var(--alert)';
}

function getRiskColor(risk) {
    if (risk == null) return 'var(--text-muted)';
    if (risk < 50)    return 'var(--verified)';
    if (risk < 90)    return 'var(--caution)';
    return 'var(--alert)';
}

// ── Gauge Math ─────────────────────────────────────────────────
// 180° arc: score 0 = left (20,90), score 1 = right (160,90)
// angle α = score * π, point = (90 - 70*cos(α), 90 - 70*sin(α))
function arcPath(cx, cy, r, score) {
    if (score <= 0) return `M ${cx - r} ${cy}`;
    if (score >= 1) return `M ${cx - r} ${cy} A ${r} ${r} 0 1 1 ${cx + r} ${cy}`;
    const angle = score * Math.PI;
    const ex = cx - r * Math.cos(angle);
    const ey = cy - r * Math.sin(angle);
    const largeArc = score > 0.5 ? 1 : 0;
    return `M ${cx - r} ${cy} A ${r} ${r} 0 ${largeArc} 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`;
}

function animateSimGauge(score) {
    // score: 0 to 1
    const fill = document.getElementById('sim-gauge-fill');
    if (!fill) return;

    let color;
    if      (score >= 0.75) color = 'var(--verified)';
    else if (score >= 0.55) color = 'var(--caution)';
    else                    color = 'var(--alert)';

    fill.setAttribute('stroke', color);

    let current = 0;
    const target = Math.min(score, 1);
    const steps  = 40;
    const step   = target / steps;

    const anim = setInterval(() => {
        current = Math.min(current + step, target);
        fill.setAttribute('d', arcPath(90, 90, 70, current));
        if (current >= target) clearInterval(anim);
    }, 25);

    // Color the gauge number
    const numEl = document.getElementById('sim-gauge-number');
    if (numEl) numEl.style.color = color;
}

function animateRiskGauge(riskScore) {
    // riskScore: 0 to 100
    const fill    = document.getElementById('risk-gauge-fill');
    const numEl   = document.getElementById('risk-gauge-number');
    const labelEl = document.getElementById('risk-gauge-label');
    if (!fill) return;

    const score01 = Math.min(riskScore / 100, 1);
    const color   = getRiskColor(riskScore);

    fill.setAttribute('stroke', color);
    if (numEl)   numEl.style.color   = color;
    if (labelEl) labelEl.style.color = color;

    let current = 0;
    const target = score01;
    const steps  = 40;
    const step   = target / steps;

    const anim = setInterval(() => {
        current = Math.min(current + step, target);
        fill.setAttribute('d', arcPath(90, 90, 70, current));
        if (current >= target) clearInterval(anim);
    }, 25);
}

// ── Markdown renderer (minimal: handles ## headings, bullets, paragraphs) ──
function renderMarkdown(text) {
    if (!text) return '';
    const lines = text.split('\n');
    const out   = [];
    let inList  = false;

    for (const line of lines) {
        const trimmed = line.trim();

        if (trimmed.startsWith('## ')) {
            if (inList) { out.push('</ul>'); inList = false; }
            out.push(`<h3 class="rv-h">${esc(trimmed.slice(3))}</h3>`);
        } else if (trimmed.startsWith('# ')) {
            if (inList) { out.push('</ul>'); inList = false; }
            out.push(`<h3 class="rv-h">${esc(trimmed.slice(2))}</h3>`);
        } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
            if (!inList) { out.push('<ul class="rv-ul">'); inList = true; }
            out.push(`<li>${esc(trimmed.slice(2))}</li>`);
        } else if (trimmed === '') {
            if (inList) { out.push('</ul>'); inList = false; }
        } else if (/^risk_score\s*=\s*\d+/.test(trimmed)) {
            // suppress raw risk_score= line from rendered output
        } else {
            if (inList) { out.push('</ul>'); inList = false; }
            out.push(`<p class="rv-p">${esc(trimmed)}</p>`);
        }
    }

    if (inList) out.push('</ul>');
    return out.join('\n');
}

function esc(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Dashboard ──────────────────────────────────────────────────
async function loadOrders() {
    try {
        const res  = await fetch('/api/orders');
        const data = await res.json();

        if (!data.success || !Array.isArray(data.orders)) {
            showEmpty();
            return;
        }

        const orders = data.orders;

        if (orders.length === 0) {
            showEmpty();
            return;
        }

        // Stats
        const accepted = orders.filter(o => (o.status || '').toLowerCase().includes('accept')).length;
        const flagged  = orders.filter(o => {
            const s = (o.status || '').toLowerCase();
            return s.includes('reject') || s.includes('review');
        }).length;

        const avgScores = orders.map(o => parseFloat(o.avg_score)).filter(v => !isNaN(v));
        const avgConf   = avgScores.length ? (avgScores.reduce((a,b) => a+b,0) / avgScores.length * 100).toFixed(1) + '%' : '—';

        document.getElementById('stat-total').textContent    = orders.length;
        document.getElementById('stat-accepted').textContent = accepted;
        document.getElementById('stat-flagged').textContent  = flagged;
        document.getElementById('stat-avg').textContent      = avgConf;

        // Table
        const tbody = document.getElementById('orders-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        orders.forEach(order => {
            const tr = document.createElement('tr');
            const avgPct = order.avg_score != null ? (parseFloat(order.avg_score) * 100).toFixed(1) + '%' : '—';
            tr.innerHTML = `
                <td><span class="mono" style="color:var(--accent);">#${order.order_id}</span></td>
                <td><span class="mono" style="color:${scoreColor01(order.avg_score)};">${avgPct}</span></td>
                <td>${getStatusPill(order.status)}</td>
            `;
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', () => {
                document.getElementById('lookup-order-id').value = order.order_id;
                doLookup(order.order_id);
                showSection('lookup');
            });
            tbody.appendChild(tr);
        });

        document.getElementById('orders-empty').style.display = 'none';
        document.getElementById('orders-table').style.display = 'table';

    } catch (e) {
        showEmpty();
    }
}

function showEmpty() {
    document.getElementById('orders-empty').style.display = 'flex';
    document.getElementById('orders-table').style.display = 'none';
    document.getElementById('stat-total').textContent    = '0';
    document.getElementById('stat-accepted').textContent = '0';
    document.getElementById('stat-flagged').textContent  = '0';
    document.getElementById('stat-avg').textContent      = '—';
}

function scoreColor01(score) {
    if (score == null) return 'var(--text-muted)';
    const f = parseFloat(score);
    if (f >= 0.75) return 'var(--verified)';
    if (f >= 0.55) return 'var(--caution)';
    return 'var(--alert)';
}

function getStatusPill(status) {
    if (!status) return `<span class="status-pill pill-pending">Unknown</span>`;
    const s = status.toLowerCase();
    if (s.includes('accept')) return `<span class="status-pill pill-accepted">${status}</span>`;
    if (s.includes('review')) return `<span class="status-pill pill-review">${status}</span>`;
    if (s.includes('reject')) return `<span class="status-pill pill-rejected">${status}</span>`;
    return `<span class="status-pill pill-pending">${status}</span>`;
}

// ── Order Lookup ───────────────────────────────────────────────
function initLookup() {
    const form = document.getElementById('lookup-form');
    if (!form) return;

    form.addEventListener('submit', e => {
        e.preventDefault();
        const id = document.getElementById('lookup-order-id').value.trim();
        if (!id) return;
        doLookup(id);
    });
}

async function doLookup(orderId) {
    const resultEl = document.getElementById('lookup-result');
    if (!resultEl) return;
    resultEl.innerHTML = '<p style="color:var(--text-muted);font-size:14px;padding:16px 0;">Searching…</p>';

    try {
        const res  = await fetch(`/api/status/${encodeURIComponent(orderId)}`);
        const data = await res.json();

        if (!data.success || !data.order) {
            resultEl.innerHTML = `<p style="color:var(--alert);font-size:14px;padding:16px 0;">Order #${orderId} not found or has not been processed yet.</p>`;
            return;
        }

        const o = data.order;
        const avgPct = o.avg_score != null ? (parseFloat(o.avg_score) * 100).toFixed(1) + '%' : '—';
        const frontPct = o.front_score != null ? (parseFloat(o.front_score) * 100).toFixed(1) + '%' : '—';
        const backPct  = o.back_score  != null ? (parseFloat(o.back_score)  * 100).toFixed(1) + '%' : '—';
        const sidePct  = o.side_score  != null ? (parseFloat(o.side_score)  * 100).toFixed(1) + '%' : '—';

        let reviewHtml = '';
        if (o.main_review) {
            reviewHtml = `
                <div class="lookup-review">
                    <div class="lookup-review-title">JUDGE SYNTHESIS</div>
                    <div class="lookup-review-rendered">${renderMarkdown(o.main_review)}</div>
                </div>
            `;
        }

        resultEl.innerHTML = `
            <div class="lookup-result-card">
                <div class="lookup-result-header">
                    <h3 class="mono">#${o.order_id}</h3>
                    ${getStatusPill(o.status)}
                </div>
                <div class="detail-grid">
                    <div class="detail-item"><div class="detail-label">AVG SIMILARITY</div><div class="detail-value mono" style="color:${scoreColor01(o.avg_score)}">${avgPct}</div></div>
                    <div class="detail-item"><div class="detail-label">FRONT</div><div class="detail-value mono" style="color:${scoreColor01(o.front_score)}">${frontPct}</div></div>
                    <div class="detail-item"><div class="detail-label">BACK</div><div class="detail-value mono" style="color:${scoreColor01(o.back_score)}">${backPct}</div></div>
                    <div class="detail-item"><div class="detail-label">SIDE</div><div class="detail-value mono" style="color:${scoreColor01(o.side_score)}">${sidePct}</div></div>
                </div>
                ${reviewHtml}
            </div>
        `;

    } catch (e) {
        resultEl.innerHTML = '<p style="color:var(--alert);font-size:14px;padding:16px 0;">Network error — could not reach server.</p>';
    }
}

// ── Spline progressive enhancement ────────────────────────────
function initSpline() {
    const spline   = document.getElementById('spline-scene');
    const fallback = document.getElementById('spline-fallback');
    if (!spline) return;

    // Listen for Spline's own load event
    spline.addEventListener('load', () => {
        spline.classList.add('loaded');
        if (fallback) fallback.style.opacity = '0';
    });

    // Timeout: if Spline hasn't loaded in 6s, keep fallback
    setTimeout(() => {
        if (!spline.classList.contains('loaded')) {
            // Spline unavailable — fallback is already visible
        }
    }, 6000);
}

// ── Init ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initUploadZones();
    initDeliveryForm();
    initReturnForm();
    initLookup();
    initSpline();
    loadOrders();
});
