# Deployment Guide

Since the backend now serves the dashboard directly (same FastAPI app, one
server), deploying this live is now a **single service** — no separate
frontend hosting needed.

**Reality check first:** this makes the project live and demoable to anyone
with the URL. It does **not** connect it to any real payment network — see
the disclaimer in the README. This is a public demo, not a financial product.

---

## Deploy to Render (free tier)

Render is used here because it supports WebSockets and long-running
processes on its free tier — most serverless platforms (Vercel/Netlify
functions) don't support the persistent WebSocket connection this app needs
for the live feed.

1. Push this repo to GitHub if you haven't already:
   ```bash
   git init
   git add .
   git commit -m "CBDC fraud detection system"
   git branch -M main
   git remote add origin https://github.com/<your-username>/cbdc-fraud-detection.git
   git push -u origin main
   ```

2. Go to [render.com](https://render.com) → sign up / log in with GitHub.

3. **New → Web Service** → connect your `cbdc-fraud-detection` repo.

4. Render should auto-detect `render.yaml` in the repo root and pre-fill
   everything. If not, set manually:
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free

5. Click **Create Web Service**. First deploy takes a few minutes (installs
   scikit-learn, pandas, etc.).

6. Once live, you'll get one URL, e.g.
   `https://cbdc-fraud-detection.onrender.com` — **that single URL is now
   both your dashboard and your API.** Open it directly in a browser and the
   full dashboard loads, connected and working, no extra config needed.

That's it — one service, one URL, dashboard and API both live.

---

## Known limitations of the free tier

- **Spins down after ~15 minutes of inactivity.** The first request after
  that can take 10–30 seconds to wake the server back up. If you're demoing
  it live, open the URL a minute or two before you actually need it so it's
  already warm.
- **Ephemeral filesystem.** The SQLite database resets on redeploy or after
  extended inactivity — fine for a portfolio demo (wallets reseed on
  startup), but don't rely on it for persistent data. For real persistence,
  swap SQLite for Render's free PostgreSQL add-on (changes needed are in
  `backend/main.py`'s `get_db()` / `init_db()` functions).

---

## Verify it's actually working once deployed

1. Open your Render URL directly.
2. Check the connection dot turns green ("Live").
3. Click **Start background traffic** — transactions should appear in the feed.
4. Try the **Send money** form and confirm you get an approved/held result.

If the dot stays red on the deployed version: open browser DevTools (F12) →
Console, and check for errors. Since everything is now same-origin, this
should be far less likely than it was locally with two separate servers —
if it still happens, it's most likely the free tier still spinning up
(wait 30 seconds and refresh).

---

## Alternatives to Render

- **Railway** ([railway.app](https://railway.app)) — same single-service
  flow, also supports WebSockets.
- **Fly.io** — more control, still has a free allowance, requires their CLI.
- Avoid Vercel/Netlify for this project — they're serverless and don't
  support the persistent WebSocket connection the live feed needs.
