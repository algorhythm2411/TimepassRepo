# YouTube Shorts Auto-Pipeline — Setup Guide
### Post one original Short per hour, completely free.

---

## What This Pipeline Does

```
Groq LLM            edge-tts             Pexels API          MoviePy              YouTube API
(Free Script)  →  (Free Voiceover)  →  (Free Footage)  →  (Assembles Video)  →  (Uploads)
```

Every hour, automatically, with zero cost.

---

## Step 1 — Install Python & Dependencies

```bash
# Make sure Python 3.9+ is installed
python --version

# Install all required libraries
pip install -r requirements.txt
```

---

## Step 2 — Get Your Free API Keys

### A) Groq API (Script Generation — Free)
1. Go to **https://console.groq.com**
2. Sign up (free, no card needed)
3. Click **API Keys** → **Create API Key**
4. Copy the key

### B) Pexels API (Stock Footage — Free)
1. Go to **https://www.pexels.com/api/**
2. Sign up → **Your API Key** tab
3. Copy the key

### C) YouTube Data API (Upload — Free)
1. Go to **https://console.cloud.google.com**
2. Create a new project (e.g., "YT Shorts Bot")
3. Go to **APIs & Services** → **Enable APIs**
4. Search and enable: **YouTube Data API v3**
5. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
6. Application type: **Desktop App**
7. Download the JSON file → rename it **client_secret.json**
8. Put `client_secret.json` in the same folder as `pipeline.py`

> **YouTube Quota Note:** Free tier allows ~6 uploads/day.  
> For 24/day (1/hour), go to:  
> APIs & Services → YouTube Data API v3 → Quotas → **Request higher quota** (free, takes 1-2 days approval)

---

## Step 3 — Set Your API Keys

**Option A — Environment variables (recommended):**
```bash
# Linux / Mac
export GROQ_API_KEY="your_groq_key_here"
export PEXELS_API_KEY="your_pexels_key_here"

# Windows (Command Prompt)
set GROQ_API_KEY=your_groq_key_here
set PEXELS_API_KEY=your_pexels_key_here
```

**Option B — Edit pipeline.py directly:**
```python
GROQ_API_KEY   = "your_groq_key_here"
PEXELS_API_KEY = "your_pexels_key_here"
```

---

## Step 4 — Choose Your Niche

Edit this line in `pipeline.py`:
```python
NICHE = "amazing science facts"
```

**High-performing niches for facts channels:**
- `"amazing animal facts"`
- `"indian history facts"`
- `"space and astronomy facts"`
- `"psychology and human behavior facts"`
- `"python programming tips"`  ← tech niche, great RPM
- `"stock market and investing basics"`  ← highest RPM niche

**Pick ONE niche and stick with it.** YouTube's algorithm rewards consistency.

---

## Step 5 — Test Without Uploading First

```bash
python -c "
from pipeline import run_pipeline
run_pipeline(upload=False)   # generates video, skips upload
"
```

Check the `shorts_output/` folder for your first Short. Watch it!  
If it looks good → proceed to Step 6.

---

## Step 6 — First Real Upload (OAuth Setup)

```bash
python -c "
from pipeline import run_pipeline
run_pipeline(upload=True)
"
```

A browser window will open → sign in with your YouTube channel account → Allow.  
A `token.json` file is saved. Future uploads happen automatically (no browser needed).

---

## Step 7 — Start the Scheduler

```bash
python scheduler.py
```

This will post one Short immediately, then one every hour, forever.

**To run it in the background and close the terminal:**

```bash
# Linux / Mac
nohup python scheduler.py > scheduler.log 2>&1 &
echo "Scheduler PID: $!"

# Check the log anytime:
tail -f scheduler.log
```

---

## Step 8 — Run it 24/7 for Free

Your PC must stay on for the scheduler. For always-on free hosting:

### Oracle Cloud Free Tier (Best Option — Always Free)
1. Sign up at **https://cloud.oracle.com** (free, needs card but never charged)
2. Create a free **AMD Compute VM** (1 OCPU, 1GB RAM — always free tier)
3. SSH into it, install Python, copy your files
4. Run `nohup python scheduler.py &`

### GitHub Actions (Alternative — 2000 min/month free)
Use the included `github-actions-workflow.yml` to trigger every hour via cron.

---

## Monetization Roadmap

| Milestone | What to do |
|---|---|
| **0 → 1,000 subs** | Focus on quality + consistency. Keep the pipeline running. |
| **1,000 subs + 10M Shorts views/90 days** | Apply for **YouTube Partner Program (YPP)** |
| **After YPP** | Shorts ads + Super Thanks start earning |
| **5,000+ subs** | Reach out to brands in your niche for **sponsorships** (₹5,000–₹50,000/video) |
| **10,000+ subs** | Add **affiliate links** in description (Amazon, courses, etc.) |
| **50,000+ subs** | Launch your own digital product (₹499–₹999 e-book, course) |

**Realistic timeline:** 3-6 months of consistent posting to reach YPP.  
**Realistic income after YPP:** ₹5,000–₹30,000/month from ads alone.  
**Path to ₹1 lakh/month:** Ads + sponsorships + affiliate, typically at 50,000+ subscribers.

---

## Tips to Maximize Growth

1. **Niche down hard** — "facts" is too broad. "Secrets of ancient Indian temples" is much better.
2. **Check your analytics weekly** — double down on whatever's getting the most views.
3. **Post consistently** — the pipeline handles this for you!
4. **Add a logo/watermark** to `pipeline.py` for brand recognition.
5. **Translate** — run the same pipeline in Hindi (`hi-IN-SwaraNeural` voice) for a separate channel.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `moviepy` font error | Install `fonts-dejavu`: `sudo apt install fonts-dejavu` (Linux) |
| `edge-tts` not working | `pip install --upgrade edge-tts` |
| YouTube quota exceeded | Request higher quota in Google Cloud Console |
| `client_secret.json` not found | Download OAuth credentials from Google Cloud Console |
| Black video output | Stock clips failed to download — check your Pexels API key |

---

## File Structure

```
your-folder/
├── pipeline.py           ← Main pipeline (edit NICHE here)
├── scheduler.py          ← Runs pipeline every hour
├── requirements.txt      ← Python dependencies
├── client_secret.json    ← YouTube OAuth (you download this)
├── token.json            ← Auto-created after first login
├── used_topics.json      ← Auto-created: tracks topics to avoid repeats
├── upload_log.json       ← Auto-created: log of all uploads
└── shorts_output/        ← Auto-created: generated videos
```
