# Deploying ReturnGuard

## Should you deploy it?

Yes. A live link lets a recruiter try the demo in 30 seconds (Deliver → "Use the blue speaker", Return → "Black speaker
swapped in") instead of reading about it. Put the link at the top of the GitHub README and next to the project on your resume.

## Where

| Option | Free? | Fits the models? | Verdict |
|---|---|---|---|
| **Hugging Face Spaces (Gradio SDK)** | Yes: CPU Basic, 2 vCPU, 16 GB RAM | Yes: DINOv2-base + U²-Net need ~2 GB | **Recommended** |
| Google Cloud Run | Generous free tier; card required | Yes with 4 GiB memory; ~30 s cold start | Good second choice |
| Render / Railway free plans | 512 MB RAM or usage credit only | No: PyTorch alone exceeds 512 MB | Not suitable |
| Vercel / Netlify | Serverless functions only | No | Not suitable |

Trade-offs of the free Space: it sleeps after a period of inactivity (first visit then takes ~1 minute to wake), and its
disk is ephemeral, so the SQLite database and uploads reset on restart. Both are fine for a portfolio demo.

## Before you deploy

1. **Rotate your Gemini key.** Create a fresh key in [Google AI Studio](https://aistudio.google.com/apikey) for the
   deployment and delete any key that has been pasted into chats or files. Never commit `.env`.
2. **Protect the quota.** A public demo can be spammed. Set `RG_RATE_LIMIT_PER_HOUR` (deliveries + returns per visitor).
   The free Gemini tier also has a small *daily* limit; if the demo hits it, ReturnGuard fails safe (returns go to
   human review), but you can raise headroom by enabling billing with a budget cap, or by pointing
   `RG_LLM_MODEL` at a cheaper model your key lists in Google AI Studio (re-run `scripts/evaluate.py` after switching).
3. **Uploaded photos.** Visitors upload images to your server. The footer already says decisions are decision support;
   consider adding "don't upload personal photos" to the Deliver/Return pages.

## Hugging Face Spaces, step by step

Hugging Face now charges for the Docker SDK, so the free route is the **Gradio SDK**. A Gradio Space simply runs a
Python file and serves whatever listens on port 7860, so [`deploy/huggingface/space_app.py`](deploy/huggingface/space_app.py)
starts the Flask app with gunicorn there. Gradio itself is installed but not used.

1. Create a free account at <https://huggingface.co>, then **New Space**:
   - Space name: `returnguard` · License: your choice · **SDK: Gradio** (Blank template) · Hardware: **CPU basic (free)**.
   - After it's created, open the Space's `README.md` and note its `sdk_version`. If it differs from the one in
     [`deploy/huggingface/README.md`](deploy/huggingface/README.md), copy it across.
2. In the Space: **Settings → Variables and secrets**
   - Secret `GOOGLE_API_KEY` = your new Gemini key
   - Variable `RG_RATE_LIMIT_PER_HOUR` = `10`
   - Variable `RG_LLM_MIN_INTERVAL_S` = `4`
   - Secret `RG_SECRET_KEY` = any long random string (keeps visitors signed in across restarts; generate one with
     `python -c "import secrets; print(secrets.token_hex(32))"`)
3. Build the upload folder and upload it:

   ```bash
   pip install -U huggingface_hub
   hf auth login                                   # paste a Hugging Face access token with write permission
   python deploy/huggingface/prepare_space.py      # writes build/hf_space
   hf upload <hf-user>/returnguard build/hf_space . --repo-type space
   ```

   `prepare_space.py` copies only files that are staged or committed in git (no `.env`, `data/`, caches or private
   notes), adds the Space README, `space_app.py` and `packages.txt`, and leaves the Pillow, NumPy and Pydantic versions
   free so pip can match them with Gradio's own requirements. `hf upload` handles images for you (no Git LFS needed).
4. The first build takes ~10–15 minutes (PyTorch is large). Watch **Logs → Build**, then **Logs → Container**. The first
   request after a start downloads DINOv2 and U²-Net (~300 MB), so allow a minute. Then check
   `https://<hf-user>-returnguard.hf.space/api/health` returns `{"status": "ok", "llm_configured": true}`.
5. Run the demo once yourself (Deliver → blue speaker, Return → black speaker) and add the link to your README and resume.

**If the build fails on a version conflict**, the log names the package: remove its version pin in
`build/hf_space/requirements.txt` and upload again.

## Updating the deployment

Stage or commit your changes, then repeat step 3. The Space rebuilds automatically.

## Running the container locally (optional)

The Dockerfile is kept for Cloud Run or any Docker host. It has not been built on the development machine (Docker
wasn't installed there). To try it locally with Docker Desktop:

```bash
docker build -t returnguard .
docker run -p 7860:7860 -e GOOGLE_API_KEY=your-key returnguard   # http://localhost:7860
```

## Google Cloud Run (alternative)

```bash
gcloud run deploy returnguard --source . --region asia-south1 --memory 4Gi --cpu 2 \
  --timeout 300 --max-instances 1 --allow-unauthenticated \
  --set-env-vars RG_RATE_LIMIT_PER_HOUR=10 --set-secrets GOOGLE_API_KEY=gemini-key:latest
```

Use `--max-instances 1`: returns are processed by an in-process background thread, so the poll for a result must reach
the same instance. Moving to a task queue (see *Scalability* in the README) removes this limit.
