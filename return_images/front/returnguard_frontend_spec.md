# ReturnGuard — Frontend Rebuild Specification

> **Purpose of this document**: A complete functional and technical specification for rebuilding the ReturnGuard frontend from scratch. The existing frontend is being fully discarded. Do not attempt to replicate its visual design, layout, or component structure — only the functional requirements documented here matter.

---

## 1. PRODUCT CONTEXT

### What the Product Does

ReturnGuard is an internal operations tool for e-commerce return fraud detection. It sits between a warehouse/fulfillment team and the refund pipeline. The system works in two phases:

1. **Delivery registration**: At dispatch time, a warehouse operator uploads three photos of a product (front, back, and side views). The backend strips the background from each image, stores them on disk, and assigns a unique integer Order ID that acts as the reference for this product instance.

2. **Return verification**: When a customer initiates a return for a given Order ID, an operator uploads three new photos of the returned item. The backend runs a multi-stage AI pipeline that compares the returned item against the delivery-time ground truth and produces one of four verdicts:
   - **`RETURN_ACCEPTED`** — Embedding similarity was high enough (> 0.60); no VLM analysis needed.
   - **`VLM Accepted`** — Embedding similarity was ambiguous (≤ 0.60) but VLM agents confirmed the product is the same.
   - **`Human Review`** — Evidence is ambiguous or conflicting; a human reviewer must inspect.
   - **`Rejected`** — Multiple VLM agents found convincing product-specific discrepancies.

### Who the Users Are

**Primary users**: Internal warehouse/fulfillment staff and operations managers at an e-commerce platform. These are not end-customers. There is no customer-facing surface. No authentication is currently implemented (the app is assumed to run in a trusted internal network).

### Core User Journeys

1. **Register a delivery** — Operator uploads front, back, and side images of a product before it ships. Gets back an Order ID to record against the physical shipment.

2. **Process a return** — Operator enters an Order ID and uploads front, back, and side images of the returned item. Waits for AI analysis (which can take tens of seconds) and reads the final verdict plus supporting evidence.

3. **Read a verdict report** — After return processing, operator reviews the structured result: the weighted similarity score, per-view subscores (front/back/side), per-view VLM agent reasoning text, and the final judge LLM synthesis. Based on this, they decide to accept/reject/escalate the return.

4. **Look up a past order** — Operator enters an Order ID to retrieve the stored verdict, all similarity scores, and the full judge review text for any historically processed order.

5. **Monitor the operations dashboard** — Manager views aggregate stats (total orders analyzed, auto-accepted count, flagged count, average similarity score) and a scrollable table of recent processed returns with their verdicts.

---

## 2. INFORMATION ARCHITECTURE

The entire app is served as a **single HTML page** (`/`). Navigation between views is tab-based client-side routing — no actual URL changes occur. The backend is a Flask server that serves one HTML template and answers JSON API calls.

### Views / Sections

| View ID | Name | Purpose | Access |
|---|---|---|---|
| `dashboard` | Dashboard | Landing view. Displays aggregate stats and a table of recent processed returns. | Public (no auth) |
| `register` | Register Delivery | Form to upload 3 delivery images. On success, displays the generated Order ID. | Public (no auth) |
| `return` | Process Return | Form to enter an Order ID + upload 3 return images. Triggers the AI pipeline. | Public (no auth) |
| `results` | Analysis Results | Displays the verdict, similarity gauge, per-view scores, VLM agent reviews, and final judge text after a return is processed. Not directly navigable — appears automatically after return form submission. | Public (no auth) |
| `lookup` | Order Lookup | Form to search any past order by ID and display its full stored record. | Public (no auth) |
| `how` | How It Works | Static informational page explaining the 4-stage pipeline. No API calls. | Public (no auth) |

**No authentication is implemented.** No login, no session, no roles. All views are public.

---

## 3. DATA & API CONTRACTS

### Backend

- **Framework**: Python Flask, serving a Jinja2 HTML template and JSON REST endpoints.
- **Base URL**: `http://localhost:5000` (default Flask dev server, run via `python similarity.py`).
- **Static assets**: served by Flask at `/static/`.
- **No WebSockets, no SSE, no polling.** All calls are standard HTTP request/response. The return analysis endpoint is synchronous and long-running (10–60+ seconds depending on hardware); the frontend simply `await`s it with a blocking loading overlay.

### Endpoints

#### `GET /`
Returns the single-page HTML shell. The frontend lives entirely inside this response.

---

#### `POST /submit_delivery_image`
Registers a delivery. Uploads all three images as `multipart/form-data`.

**Request** — `Content-Type: multipart/form-data`:
```
front_image  : File  (required, any image MIME type)
back_image   : File  (required, any image MIME type)
side_image   : File  (required, any image MIME type)
```

**Response 200** — `application/json`:
```json
{
  "success": true,
  "order_id": "7",
  "message": "Delivery images saved successfully with Order ID 7"
}
```

**Response 400** — `application/json`:
```json
{
  "success": false,
  "error": "All three images (front, back, side) are required."
}
```

> Note: `order_id` in the success response is a **string** (even though it is an integer in the DB).

---

#### `POST /submit_return_images`
Runs the full AI fraud detection pipeline for a given order. This is a **long-running synchronous call** — expect 10–60+ seconds. The frontend must show a loading/processing state during this time.

**Request** — `Content-Type: multipart/form-data`:
```
order_id     : string  (required — the integer Order ID as a string)
front_image  : File    (required)
back_image   : File    (required)
side_image   : File    (required)
```

**Response 200** — `application/json`:
```json
{
  "success": true,
  "order_id": "7",
  "status": "RETURN_ACCEPTED" | "VLM Accepted" | "Human Review" | "Rejected",
  "front_score": 0.823,
  "back_score": 0.751,
  "side_score": 0.612,
  "avg_score": 0.741,
  "front_review": "string or null",
  "back_review": "string or null",
  "side_review": "string or null",
  "main_review": "string or null"
}
```

Score fields (`front_score`, `back_score`, `side_score`, `avg_score`) are floats in the range `[0.0, 1.0]` — the raw cosine similarity. They may be `null` if the pipeline short-circuited before VLM analysis.

Review fields (`front_review`, `back_review`, `side_review`, `main_review`) are plain text strings (may contain markdown-style section headers like `## FINAL JUDGEMENT`). They are `null` when `status` is `RETURN_ACCEPTED` (VLM was not invoked).

**Response 400** — `application/json`:
```json
{
  "success": false,
  "error": "Order ID is required."
}
```

---

#### `GET /api/status/<order_id>`
Fetches the full stored record for a single order. `<order_id>` is an integer in the URL path.

**Response 200**:
```json
{
  "success": true,
  "order": {
    "Order_ID": 7,
    "Similarity_Score": 0.741,
    "front_score": 0.823,
    "back_score": 0.751,
    "side_score": 0.612,
    "avg_score": 0.741,
    "front_review": "string or null",
    "back_review": "string or null",
    "side_review": "string or null",
    "main_review": "string or null",
    "Status": "RETURN_ACCEPTED" | "VLM Accepted" | "Human Review" | "Rejected" | null
  }
}
```

**Response 404**:
```json
{
  "success": false,
  "error": "Order 99 not found."
}
```

> Note: `Similarity_Score` and `avg_score` are currently the same value — `avg_score` is the quality-weighted average cosine similarity computed during return analysis and is written to both columns. Treat them as equivalent.

---

#### `GET /api/orders`
Returns the 50 most recent processed orders for the dashboard table, ordered by `Order_ID DESC`.

**Response 200**:
```json
{
  "success": true,
  "orders": [
    {
      "Order_ID": 7,
      "Similarity_Score": 0.741,
      "avg_score": 0.741,
      "Status": "RETURN_ACCEPTED"
    }
  ]
}
```

> Note: This endpoint only returns 4 fields per order, not the full record. Use `/api/status/<id>` for the full record.

---

### Real-Time / Streaming
**None.** There is no WebSocket, SSE, or polling. The return analysis endpoint blocks until complete. The frontend should display an indeterminate loading state while waiting.

### Auth Mechanism
**None.** No tokens, no cookies, no OAuth. The app is fully public. Do not build any auth UI or gating.

---

## 4. STATE & BUSINESS LOGIC

### Client-Side Validation Rules

These must be enforced before any API call is made:

**Delivery form (`POST /submit_delivery_image`)**:
- All three files (front, back, side) must be selected. If any is missing, show an error and do not submit.

**Return form (`POST /submit_return_images`)**:
- The Order ID field must be non-empty (trimmed). If missing, show an error.
- All three files (front, back, side) must be selected. If any is missing, show an error and do not submit.

**Lookup form (`GET /api/status/<id>`)**:
- The Order ID field must be non-empty (trimmed). If missing, do not submit.

### Status → Verdict Mapping

The frontend maps the raw `status` string from the API to a human-readable verdict label. This is a **required business rule** — do not display the raw status string directly to users:

| API `status` value | Display label | Meaning |
|---|---|---|
| `RETURN_ACCEPTED` | "Return Accepted" | Passed embedding similarity threshold; no VLM needed |
| `VLM Accepted` | "Return Accepted" | VLM agents confirmed product match |
| `Human Review` | "Requires Human Review" | Evidence is ambiguous |
| `Rejected` | "Return Rejected" | VLM agents found convincing fraud evidence |

### Dashboard Stats Calculation

The dashboard computes four stats from the `/api/orders` response entirely in the browser:

| Stat | Calculation |
|---|---|
| Total Orders Analyzed | `orders.length` |
| Returns Auto-Accepted | Count of orders where `Status === 'RETURN_ACCEPTED' OR Status === 'VLM Accepted'` |
| Flagged for Review | Count of orders where `Status === 'Human Review' OR Status === 'Rejected'` |
| Avg Pipeline Confidence | Mean of `avg_score` across all orders where `avg_score !== null`, displayed as a percentage |

### Score Display Format

All similarity scores are stored and transmitted as floats in `[0.0, 1.0]`. Display them as percentages with one decimal place, e.g. `0.741` → `"74.1%"`. When a score is `null`, display `"—"`.

### Similarity Score Thresholds (for UI color-coding or labeling)

These thresholds are used by the backend but should also be reflected in the UI where scores are displayed:

| Score range | Meaning |
|---|---|
| ≥ 0.75 | High similarity (safe) |
| 0.55 – 0.75 | Moderate similarity (borderline) |
| < 0.55 | Low similarity (suspicious) |

The hard accept/reject threshold in the backend is **0.60** — returns above this never go to VLM.

### Processing State

When either the delivery or return form is submitted, the UI must enter a full-screen blocking loading state. It must remain active until the API call resolves (success or error). For the return endpoint specifically, this may take well over 30 seconds.

### Results Navigation

After a successful return analysis, the frontend should automatically navigate/switch to the results view, passing all fields from the API response into it. The results view is not accessible via normal tab navigation — it appears only after a successful return submission or can be dismissed to return to the dashboard.

### File Preview

After a user selects or drops an image file into an upload zone, a preview of the selected image should be shown within that upload zone before submission. Drag-and-drop must be supported in addition to click-to-browse.

---

## 5. CONSTRAINTS

### Required Stack

The backend is Python/Flask and renders a single Jinja2 template (`templates/index.html`). The frontend must be delivered as:
- One HTML file at `templates/index.html` (referenced by Flask's `render_template('index.html')`)
- CSS at `static/app.css` (referenced via Flask's `url_for('static', filename='app.css')`)
- JavaScript at `static/app.js` (referenced via Flask's `url_for('static', filename='app.js')`)

Flask's URL patterns for static files must be respected: `{{ url_for('static', filename='...') }}` in the HTML template.

**No build step, no bundler, no npm.** Vanilla HTML, CSS, and JavaScript only. The files are served directly by Flask with no compilation step.

### Browser/Device Support

No explicit requirements are documented. Target modern desktop browsers (Chrome, Firefox, Edge, Safari — last 2 major versions). Mobile responsiveness is desirable but not the primary use case (this is an internal ops tool used on desktops at warehouses).

### Known Issues That Must NOT Be Replicated

1. **Static Unsplash images in the How It Works section**: The existing template hardcodes public Unsplash URLs for illustrative images. These are external dependencies that could break. Either use locally generated/stored assets or remove the images entirely from that section.

2. **`order_id` type inconsistency**: The `/submit_delivery_image` endpoint returns `order_id` as a string. The `/submit_return_images` endpoint accepts `order_id` as a form string field but the DB stores it as an integer. When passing Order ID to `/api/status/<order_id>`, the backend casts it with `int(order_id)`. The frontend must send order IDs as plain numeric strings without leading zeros.

3. **No `results` tab in the nav**: The results view (`#results`) is not included in the navigation tabs and is not navigable by the user directly. It is only shown programmatically after a successful return analysis. The nav tabs must not include a "Results" tab.

4. **`Similarity_Score` vs `avg_score` in the orders table**: The `/api/orders` response includes both `Similarity_Score` and `avg_score`. The existing frontend displayed both as separate columns labeled "Visual Match Score" and "Avg VLM Confidence" respectively. In practice they hold the same value. The rebuild may choose to display only one.

5. **`add_similarity_data` is called before VLM**: The backend inserts a row into the DB with `PASSED TO VLM FOR REVIEW` status before VLM runs, then updates it afterward via `add_review_data`. If the backend crashes mid-pipeline, an order may be stuck in `PASSED TO VLM FOR REVIEW` status in the DB — this is a backend bug, not a frontend concern, but the frontend should handle unknown `Status` values gracefully (don't crash; display the raw string if unmapped).

---

## 6. DATABASE SCHEMA (for reference)

The backend uses SQLite (`request.db`). The frontend never queries the DB directly — only through the REST API — but this schema defines what data exists and what the API can return:

```sql
CREATE TABLE IF NOT EXISTS Orders (
    Order_ID       INTEGER PRIMARY KEY,
    Similarity_Score REAL,   -- same as avg_score; set during return analysis
    front_score    REAL,     -- per-view cosine similarity, front angle
    back_score     REAL,     -- per-view cosine similarity, back angle
    side_score     REAL,     -- per-view cosine similarity, side angle
    avg_score      REAL,     -- quality-weighted average of front/back/side
    front_review   TEXT,     -- VLM agent text for front view (null if skipped)
    back_review    TEXT,     -- VLM agent text for back view (null if skipped)
    side_review    TEXT,     -- VLM agent text for side view (null if skipped)
    main_review    TEXT,     -- final judge LLM synthesis text (null if skipped)
    Status         TEXT      -- verdict string (see mapping table above)
);
```

Note: **Delivery registration does not create a DB row.** An `Orders` row is only created when return images are submitted. The Order ID for delivery is generated as `MAX(Order_ID) + 1` at registration time and is not persisted until a return is processed.
