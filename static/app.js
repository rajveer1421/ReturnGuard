/* ============================================================
   ReturnGuard — Dashboard Application Logic
   Particle effects, drag-drop uploads, API calls,
   animated gauges, pipeline visualization
   ============================================================ */

// ── Particle Background ──
class ParticleSystem {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.particles = [];
        this.connections = [];
        this.mouse = { x: null, y: null };
        this.resize();
        this.init();
        this.animate();

        window.addEventListener('resize', () => this.resize());
        window.addEventListener('mousemove', (e) => {
            this.mouse.x = e.clientX;
            this.mouse.y = e.clientY;
        });
    }

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }

    init() {
        const count = Math.floor((this.canvas.width * this.canvas.height) / 18000);
        this.particles = [];
        for (let i = 0; i < Math.min(count, 80); i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * 0.4,
                vy: (Math.random() - 0.5) * 0.4,
                r: Math.random() * 1.5 + 0.5,
                opacity: Math.random() * 0.3 + 0.1
            });
        }
    }

    animate() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        this.particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
            if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

            // Mouse repulsion
            if (this.mouse.x !== null) {
                const dx = p.x - this.mouse.x;
                const dy = p.y - this.mouse.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 120) {
                    p.vx += dx * 0.0003;
                    p.vy += dy * 0.0003;
                }
            }

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            this.ctx.fillStyle = `rgba(37, 99, 235, ${p.opacity})`;
            this.ctx.fill();
        });

        // Draw connections
        for (let i = 0; i < this.particles.length; i++) {
            for (let j = i + 1; j < this.particles.length; j++) {
                const dx = this.particles[i].x - this.particles[j].x;
                const dy = this.particles[i].y - this.particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 140) {
                    this.ctx.beginPath();
                    this.ctx.moveTo(this.particles[i].x, this.particles[i].y);
                    this.ctx.lineTo(this.particles[j].x, this.particles[j].y);
                    this.ctx.strokeStyle = `rgba(37, 99, 235, ${0.05 * (1 - dist / 140)})`;
                    this.ctx.lineWidth = 0.5;
                    this.ctx.stroke();
                }
            }
        }

        requestAnimationFrame(() => this.animate());
    }
}

// ── Navigation ──
function initNavigation() {
    const tabs = document.querySelectorAll('.nav-tab');
    const sections = document.querySelectorAll('.page-section');

    function switchTab(tabId) {
        tabs.forEach(t => t.classList.remove('active'));
        sections.forEach(s => {
            s.classList.remove('active');
            s.style.display = 'none';
        });

        document.querySelectorAll(`.nav-tab[data-tab="${tabId}"]`).forEach(t => t.classList.add('active'));

        const target = document.getElementById(tabId);
        if (target) {
            target.style.display = 'block';
            requestAnimationFrame(() => {
                target.classList.add('active');
            });
        }

        // Close mobile nav
        const mobileNav = document.querySelector('.mobile-nav');
        if (mobileNav) mobileNav.classList.remove('open');
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Mobile menu toggle
    const mobileBtn = document.getElementById('mobile-menu-btn');
    const mobileNav = document.getElementById('mobile-nav');
    if (mobileBtn && mobileNav) {
        mobileBtn.addEventListener('click', () => {
            mobileNav.classList.toggle('open');
        });
    }

    // Show dashboard by default
    switchTab('dashboard');
}

// ── Drag & Drop Upload ──
function initUploadZones() {
    document.querySelectorAll('.upload-zone').forEach(zone => {
        const input = zone.querySelector('input[type="file"]');

        ['dragenter', 'dragover'].forEach(evt => {
            zone.addEventListener(evt, (e) => {
                e.preventDefault();
                zone.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(evt => {
            zone.addEventListener(evt, (e) => {
                e.preventDefault();
                zone.classList.remove('drag-over');
            });
        });

        zone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                input.files = files;
                showPreview(zone, files[0]);
            }
        });

        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                showPreview(zone, input.files[0]);
            }
        });
    });
}

function showPreview(zone, file) {
    // Remove existing preview
    const existing = zone.querySelector('.preview-img');
    const existingOverlay = zone.querySelector('.preview-overlay');
    if (existing) existing.remove();
    if (existingOverlay) existingOverlay.remove();

    zone.classList.add('has-file');

    const reader = new FileReader();
    reader.onload = (e) => {
        const img = document.createElement('img');
        img.src = e.target.result;
        img.className = 'preview-img';
        zone.appendChild(img);

        const overlay = document.createElement('div');
        overlay.className = 'preview-overlay';
        overlay.innerHTML = '<span>🔄 Change Image</span>';
        zone.appendChild(overlay);
    };
    reader.readAsDataURL(file);
}

// ── Flash Notifications ──
function showSuccess(message) {
    const flash = document.getElementById('success-flash');
    flash.querySelector('.flash-text').textContent = message;
    flash.classList.add('active');
    setTimeout(() => flash.classList.remove('active'), 5000);
}

function showError(message) {
    const flash = document.getElementById('error-flash');
    flash.querySelector('.flash-text').textContent = message;
    flash.classList.add('active');
    setTimeout(() => flash.classList.remove('active'), 6000);
}

// ── Processing Overlay ──
function showProcessing(message, sub) {
    const overlay = document.getElementById('processing-overlay');
    overlay.querySelector('.processing-text').textContent = message || 'Processing...';
    overlay.querySelector('.processing-sub').textContent = sub || '';
    overlay.classList.add('active');

    // Animate pipeline steps
    animatePipeline();
}

function hideProcessing() {
    document.getElementById('processing-overlay').classList.remove('active');
    resetPipeline();
}

function animatePipeline() {
    const steps = document.querySelectorAll('#processing-overlay .step-dot');
    const connectors = document.querySelectorAll('#processing-overlay .pipeline-connector');
    let idx = 0;

    function nextStep() {
        if (idx < steps.length) {
            if (idx > 0) {
                steps[idx - 1].classList.remove('active');
                steps[idx - 1].classList.add('done');
                if (connectors[idx - 1]) connectors[idx - 1].classList.add('done');
            }
            steps[idx].classList.add('active');
            idx++;
            setTimeout(nextStep, 2500);
        }
    }
    nextStep();
}

function resetPipeline() {
    document.querySelectorAll('#processing-overlay .step-dot').forEach(d => {
        d.classList.remove('active', 'done');
    });
    document.querySelectorAll('#processing-overlay .pipeline-connector').forEach(c => {
        c.classList.remove('done');
    });
}

// ── Delivery Form Submit ──
function initDeliveryForm() {
    const form = document.getElementById('delivery-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const front = form.querySelector('input[name="front_image"]');
        const back = form.querySelector('input[name="back_image"]');
        const side = form.querySelector('input[name="side_image"]');

        if (!front.files[0] || !back.files[0] || !side.files[0]) {
            showError('Please upload all three images (Front, Back, Side).');
            return;
        }

        const formData = new FormData();
        formData.append('front_image', front.files[0]);
        formData.append('back_image', back.files[0]);
        formData.append('side_image', side.files[0]);

        showProcessing('Registering Delivery Evidence', 'Removing backgrounds and generating product embeddings...');

        try {
            const response = await fetch('/submit_delivery_image', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            hideProcessing();

            if (data.success) {
                showSuccess(`✅ Delivery registered! Order ID: ${data.order_id}`);
                document.getElementById('delivery-order-id').textContent = data.order_id;
                document.getElementById('delivery-success').style.display = 'block';
                form.reset();
                // Clear previews
                form.querySelectorAll('.upload-zone').forEach(zone => {
                    zone.classList.remove('has-file');
                    const img = zone.querySelector('.preview-img');
                    const overlay = zone.querySelector('.preview-overlay');
                    if (img) img.remove();
                    if (overlay) overlay.remove();
                });
                loadOrders();
            } else {
                showError(data.error || 'Failed to register delivery.');
            }
        } catch (err) {
            hideProcessing();
            showError('Server error. Make sure all dependencies are installed.');
            console.error(err);
        }
    });
}

// ── Return Form Submit ──
function initReturnForm() {
    const form = document.getElementById('return-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const orderId = form.querySelector('input[name="order_id"]').value.trim();
        const front = form.querySelector('input[name="front_image"]');
        const back = form.querySelector('input[name="back_image"]');
        const side = form.querySelector('input[name="side_image"]');

        if (!orderId) {
            showError('Please enter the Order ID.');
            return;
        }

        if (!front.files[0] || !back.files[0] || !side.files[0]) {
            showError('Please upload all three return images.');
            return;
        }

        const formData = new FormData();
        formData.append('order_id', orderId);
        formData.append('front_image', front.files[0]);
        formData.append('back_image', back.files[0]);
        formData.append('side_image', side.files[0]);

        showProcessing(
            'AI Agents Analyzing Return',
            'Running DINOv2 embeddings, cosine similarity, VLM review, and final judge...'
        );

        try {
            const response = await fetch('/submit_return_images', {
                method: 'POST',
                body: formData
            });
            const data = await response.json();
            hideProcessing();

            if (data.success) {
                showSuccess(`Analysis complete for Order #${data.order_id}`);
                displayResults(data);
                loadOrders();
            } else {
                showError(data.error || 'Failed to process return.');
            }
        } catch (err) {
            hideProcessing();
            showError('Server error during analysis. Check backend logs.');
            console.error(err);
        }
    });
}

// ── Display Results — triggers the gold-sweep verdict reveal ──
function displayResults(data) {
    const section = document.getElementById('results');
    section.style.display = 'block';
    section.classList.add('active');

    // Switch to results view
    document.querySelectorAll('.page-section').forEach(s => {
        if (s.id !== 'results') {
            s.classList.remove('active');
            s.style.display = 'none';
        }
    });
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));

    // Order ID
    document.getElementById('result-order-id').textContent = data.order_id;

    // ── Verdict card: map status → classes and copy ──
    const card = document.getElementById('verdict-card');
    const verdictText = document.getElementById('verdict-text');
    const verdictSub = document.getElementById('verdict-sub');
    const status = data.status || 'Pending';

    // Clear previous state
    card.className = 'verdict-card';

    let verdictLabel = status;
    let verdictClass = '';

    if (status === 'RETURN_ACCEPTED') {
        verdictLabel = 'Return Accepted';
        verdictClass = 'v-accepted';
        verdictSub.textContent = 'Embedding similarity exceeded threshold — no VLM review required.';
    } else if (status === 'VLM Accepted') {
        verdictLabel = 'Return Accepted';
        verdictClass = 'v-vlm';
        verdictSub.textContent = 'VLM review completed — all agents confirm the product matches.';
    } else if (status === 'Human Review') {
        verdictLabel = 'Requires Human Review';
        verdictClass = 'v-review';
        verdictSub.textContent = 'Evidence is ambiguous. A human reviewer should inspect this return.';
    } else if (status === 'Rejected') {
        verdictLabel = 'Return Rejected';
        verdictClass = 'v-rejected';
        verdictSub.textContent = 'Convincing product-specific discrepancies identified by multiple VLM agents.';
    } else {
        verdictLabel = status;
        verdictClass = 'v-review';
    }

    verdictText.textContent = verdictLabel;

    // Fire the signature animation: scan line sweeps, then text stamps in
    requestAnimationFrame(() => {
        card.classList.add(verdictClass, 'scanning');
        setTimeout(() => {
            card.classList.add('revealed');
        }, 200);
    });

    // Score gauge
    const avgScore = data.avg_score || 0;
    animateGauge(avgScore);

    // Score breakdown
    document.getElementById('front-score').textContent = formatScore(data.front_score);
    document.getElementById('back-score').textContent = formatScore(data.back_score);
    document.getElementById('side-score').textContent = formatScore(data.side_score);

    // VLM Reviews
    setReview('front-review', data.front_review, '↳ FRONT VIEW');
    setReview('back-review', data.back_review, '↳ BACK VIEW');
    setReview('side-review', data.side_review, '↳ SIDE VIEW');
    setReview('main-review', data.main_review, '⚖ Final Judge Decision');

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function formatScore(score) {
    if (score === null || score === undefined) return '—';
    return (score * 100).toFixed(1) + '%';
}

function setReview(elementId, text, headingText) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const pre = el.querySelector('pre');
    if (headingText) {
        const h3 = el.querySelector('h3');
        if (h3) h3.textContent = headingText;
    }
    if (pre) {
        pre.textContent = text || 'No review available (similarity score was high enough to skip VLM).';
    }
}

// ── Gauge Animation ──
function animateGauge(score) {
    const circle = document.getElementById('gauge-fill');
    const number = document.getElementById('gauge-number');
    if (!circle || !number) return;

    const circumference = 2 * Math.PI * 60;
    circle.style.strokeDasharray = circumference;
    circle.style.strokeDashoffset = circumference;

    // Color thresholds match 0.60 accept threshold
    let color = '#DC2626'; // crimson
    if (score >= 0.75) color = '#10B981';   // emerald
    else if (score >= 0.55) color = '#D97706'; // amber

    circle.style.stroke = color;
    number.style.color = color;

    requestAnimationFrame(() => {
        setTimeout(() => {
            const offset = circumference - (score * circumference);
            circle.style.strokeDashoffset = offset;

            // Animate number counter
            let current = 0;
            const target = score * 100;
            const duration = 1400;
            const startTime = performance.now();

            function updateNumber(now) {
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                current = eased * target;
                number.textContent = current.toFixed(1) + '%';
                if (progress < 1) requestAnimationFrame(updateNumber);
            }
            requestAnimationFrame(updateNumber);
        }, 100);
    });
}

// ── Order Lookup ──
function initLookup() {
    const form = document.getElementById('lookup-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const orderId = form.querySelector('input[name="lookup_order_id"]').value.trim();
        if (!orderId) return;

        try {
            const response = await fetch(`/api/status/${orderId}`);
            const data = await response.json();

            const resultDiv = document.getElementById('lookup-result');
            if (data.success) {
                const order = data.order;
                resultDiv.innerHTML = `
                    <div class="glass-card" style="margin-top: 20px;">
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:20px;">
                            <h3 style="font-size:18px;">Order #${order.Order_ID}</h3>
                            ${getStatusPillHTML(order.Status)}
                        </div>
                        <div class="detail-grid">
                            <div class="detail-item">
                                <div class="label">Avg Similarity</div>
                                <div class="value">${order.avg_score !== null ? (order.avg_score * 100).toFixed(1) + '%' : '—'}</div>
                            </div>
                            <div class="detail-item">
                                <div class="label">Similarity Score</div>
                                <div class="value">${order.Similarity_Score !== null ? (order.Similarity_Score * 100).toFixed(1) + '%' : '—'}</div>
                            </div>
                            <div class="detail-item">
                                <div class="label">Front Score</div>
                                <div class="value">${order.front_score !== null ? (order.front_score * 100).toFixed(1) + '%' : '—'}</div>
                            </div>
                            <div class="detail-item">
                                <div class="label">Back Score</div>
                                <div class="value">${order.back_score !== null ? (order.back_score * 100).toFixed(1) + '%' : '—'}</div>
                            </div>
                            <div class="detail-item">
                                <div class="label">Side Score</div>
                                <div class="value">${order.side_score !== null ? (order.side_score * 100).toFixed(1) + '%' : '—'}</div>
                            </div>
                            <div class="detail-item">
                                <div class="label">Status</div>
                                <div class="value" style="font-size:13px;">${order.Status || '—'}</div>
                            </div>
                        </div>
                        ${order.main_review ? `
                        <div class="review-block" style="margin-top:20px;">
                            <h3>🤖 Final Judge Review</h3>
                            <pre>${order.main_review}</pre>
                        </div>
                        ` : ''}
                    </div>
                `;
            } else {
                resultDiv.innerHTML = `
                    <div class="glass-card" style="margin-top:20px; text-align:center; padding:40px;">
                        <div style="font-size:40px; margin-bottom:12px;">🔍</div>
                        <p style="color:var(--text-tertiary);">Order #${orderId} not found in the database.</p>
                    </div>
                `;
            }
        } catch (err) {
            showError('Failed to lookup order. Check server connection.');
            console.error(err);
        }
    });
}

function getStatusPillHTML(status) {
    if (!status) return '<span class="status-pill pending">Pending</span>';

    let cls = 'pending';
    if (status === 'RETURN_ACCEPTED') cls = 'accepted';
    else if (status === 'Rejected') cls = 'rejected';
    else if (status === 'Human Review') cls = 'review';
    else if (status === 'VLM Accepted') cls = 'vlm';
    else if (status.includes('VLM')) cls = 'vlm';

    return `<span class="status-pill ${cls}">${status}</span>`;
}

// ── Load Orders Table ──
async function loadOrders() {
    try {
        const response = await fetch('/api/orders');
        const data = await response.json();

        const tbody = document.getElementById('orders-tbody');
        const emptyState = document.getElementById('orders-empty');

        if (!data.success || data.orders.length === 0) {
            if (tbody) tbody.innerHTML = '';
            if (emptyState) emptyState.style.display = 'block';
            return;
        }

        if (emptyState) emptyState.style.display = 'none';

        // Update stats
        const totalEl = document.getElementById('stat-total');
        const acceptedEl = document.getElementById('stat-accepted');
        const flaggedEl = document.getElementById('stat-flagged');
        const avgEl = document.getElementById('stat-avg');

        if (totalEl) totalEl.textContent = data.orders.length;
        if (acceptedEl) {
            const accepted = data.orders.filter(o => o.Status === 'RETURN_ACCEPTED' || o.Status === 'VLM Accepted').length;
            acceptedEl.textContent = accepted;
        }
        if (flaggedEl) {
            const flagged = data.orders.filter(o => o.Status === 'Human Review' || o.Status === 'Rejected').length;
            flaggedEl.textContent = flagged;
        }
        if (avgEl) {
            const scores = data.orders.filter(o => o.avg_score !== null).map(o => o.avg_score);
            if (scores.length > 0) {
                const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
                avgEl.textContent = (avg * 100).toFixed(0) + '%';
            }
        }

        if (!tbody) return;
        tbody.innerHTML = data.orders.map(order => `
            <tr>
                <td class="mono">#${order.Order_ID}</td>
                <td class="mono">${order.Similarity_Score !== null ? (order.Similarity_Score * 100).toFixed(1) + '%' : '—'}</td>
                <td class="mono">${order.avg_score !== null ? (order.avg_score * 100).toFixed(1) + '%' : '—'}</td>
                <td>${getStatusPillHTML(order.Status)}</td>
            </tr>
        `).join('');

    } catch (err) {
        console.error('Failed to load orders:', err);
    }
}

// ── Back to Dashboard from Results ──
function backToDashboard() {
    document.getElementById('results').classList.remove('active');
    document.getElementById('results').style.display = 'none';

    const dashboard = document.getElementById('dashboard');
    dashboard.style.display = 'block';
    requestAnimationFrame(() => dashboard.classList.add('active'));

    document.querySelectorAll('.nav-tab[data-tab="dashboard"]').forEach(t => t.classList.add('active'));
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    // Particles
    const canvas = document.getElementById('particle-canvas');
    if (canvas) new ParticleSystem(canvas);

    initNavigation();
    initUploadZones();
    initDeliveryForm();
    initReturnForm();
    initLookup();
    loadOrders();
});
