# Deploying ReturnGuard

## Should you deploy it?

Yes. A live link lets a recruiter try the demo in 30 seconds (Deliver → "Use the blue speaker", Return → "Black speaker
swapped in") instead of reading about it. Put the link at the top of the GitHub README and next to the project on your resume.

## Where

| Option | Free? | Fits the models? | Verdict |
|---|---|---|---|
| **Hugging Face Spaces (Docker)** | Yes: CPU Basic, 2 vCPU, 16 GB RAM | Yes: DINOv2-base + U²-Net need ~2 GB | **Recommended** |
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

1. Create a free account at <https://huggingface.co>, then **New Space**:
   - Space name: `returnguard` · License: your choice · **SDK: Docker** (Blank template) · Hardware: **CPU basic (free)**.
2. In the Space: **Settings → Variables and secrets**
   - Secret `GOOGLE_API_KEY` = your new Gemini key
   - Variable `RG_RATE_LIMIT_PER_HOUR` = `10`
   - Variable `RG_LLM_MIN_INTERVAL_S` = `4`
   - Secret `RG_SECRET_KEY` = any long random string (keeps visitors signed in across restarts; generate one with
     `python -c "import secrets; print(secrets.token_hex(32))"`)
3. Push the code. The Space is its own git repo and needs a README with Space metadata, so push a copy of the project
   with [`deploy/huggingface/README.md`](deploy/huggingface/README.md) as its README (Git Bash):

   ```bash
   # from the ReturnGuard folder; replace <hf-user>
   git clone https://huggingface.co/spaces/<hf-user>/returnguard ../returnguard-space
   git archive HEAD | tar -x -C ../returnguard-space          # committed files only: no .env, data or caches
   cp deploy/huggingface/README.md ../returnguard-space/README.md
   cd ../returnguard-space
   git add -A && git commit -m "Deploy ReturnGuard" && git push
   ```

   When git asks for a password, use a Hugging Face **access token** with write permission (Settings → Access Tokens).
   `git archive` only includes committed files, so commit your latest changes first.
4. The first build takes ~10–15 minutes: it installs CPU PyTorch and bakes DINOv2 and U²-Net into the image. Watch
   **Logs → Build**. When it shows *Running*, open the Space and check `https://<hf-user>-returnguard.hf.space/api/health`
   returns `{"status": "ok", "llm_configured": true}`.
5. Run the demo once yourself (Deliver → blue speaker, Return → black speaker) and add the link to your README and resume.

**If the push is rejected for binary files**, track images with Git LFS in the Space repo and push again:
`git lfs install && git lfs track "*.png" "*.jpg" "*.jpeg" && git add .gitattributes && git add -A && git commit --amend --no-edit && git push`.

## Updating the deployment

Repeat step 3: commit in the main repo, `git archive HEAD | tar -x -C ../returnguard-space`, re-copy the Space README, commit and push.
The Space rebuilds automatically.

## Running the container locally (optional)

The Dockerfile has not been built on the development machine (Docker wasn't installed there), so Hugging Face's build
log is the first real test. To try it locally with Docker Desktop:

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
