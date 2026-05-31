# YouTube Shorts Auto-Pipeline — VIRAL EDITION v2
# =======================================================
# UPGRADES APPLIED:
# ✅ U1: Loop structure — last sentence mirrors the hook. Rule 8 injected into Groq.
#         YouTube counts replays as views. 100%+ retention = strongest distribution signal.
#
# ✅ U2: Word-by-word highlighted captions via edge_tts WordBoundary events.
#         communicate.stream() replaces communicate.save() for precise word timing.
#         Each word flashes yellow as spoken — the format that drove TikTok/Shorts explosion.
#         ~30% completion rate boost.
#
# ✅ U3: Google Trends hot-topic injection via pytrends (free, no API key).
#         Top 5 trending searches in your niche prepended to Groq prompt.
#         Your videos are algorithmically hot before they're even published.
#
# ✅ U4: Engagement bait line on every script.
#         Rule added: "Include a specific comment prompt before the final CTA."
#         Comment velocity is a direct rank signal.
#
# ✅ U5: Upload cadence support — NICHE + channel name are env-var driven.
#         Run 3 GitHub Actions workflows (channel_psych.yml / channel_history.yml /
#         channel_money.yml) each passing its own NICHE env var + YouTube token secret.
#         Cron times staggered; 3 channels × 3 posts/day = 9 Shorts/day, zero intervention.
#
# ✅ U6: Affiliate link injection into video descriptions.
#         Niche-keyed affiliate link map. Rotates per upload. No extra API needed.
#
# Still 100% FREE — Groq, edge_tts, Pexels, pytrends, GitHub Actions.

import os
import json
import asyncio
import math
import random
import re
import base64
import requests
from pathlib import Path
from datetime import datetime
import numpy as np
import PIL.Image

if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

from PIL import Image, ImageDraw, ImageFont
import edge_tts
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    CompositeAudioClip,
    ColorClip,
    concatenate_videoclips,
)
from moviepy.audio.AudioClip import AudioClip
import moviepy.video.fx.all as vfx
from moviepy.video.fx.all import crop

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION  (all overridable via environment variables)
# ═══════════════════════════════════════════════════════════════

GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY      = os.getenv("PEXELS_API_KEY")
CLIENT_SECRET_JSON  = os.getenv("CLIENT_SECRET_JSON")   # base64 of client_secret.json
TOKEN_JSON          = os.getenv("TOKEN_JSON")            # base64 of token.json

# Niche is picked randomly each run from the three highest-performing categories.
# Override by setting the NICHE env var (e.g. in a workflow or locally).
_NICHE_POOL = [
    "mind-blowing psychology facts",
    "shocking money and finance secrets",
    "dark history facts nobody teaches",
]
NICHE = os.getenv("NICHE") or random.choice(_NICHE_POOL)

VOICE = "AUTO"
VOICE_CANDIDATES = [
    "en-GB-RyanNeural",
    "en-IN-PrabhatNeural",
    "en-US-GuyNeural",
    "en-AU-WilliamNeural",
]
TTS_RATE  = "+8%"
TTS_PITCH = "-1Hz"

WIDTH, HEIGHT = 1080, 1920
FPS = 30

OUTPUT_DIR = Path("shorts_output")
TOPICS_LOG = Path("used_topics.json")
UPLOAD_LOG = Path("upload_log.json")
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── U6: Affiliate link map (add your own IDs) ──────────────
# Format: niche keyword → (display label, URL)
AFFILIATE_LINKS = {
    "science":    ("📚 Grab this science kit", "https://amzn.to/science-kit"),
    "psychology": ("🧠 Best psychology books", "https://amzn.to/psych-books"),
    "history":    ("📖 Top history reads",     "https://amzn.to/history-reads"),
    "money":      ("💰 Start investing free",  "https://zerodha.com/?ref=YOUR_REF"),
    "finance":    ("💰 Start investing free",  "https://zerodha.com/?ref=YOUR_REF"),
    "health":     ("🧘 Try Headspace free",    "https://headspace.com/?ref=YOUR_REF"),
    "fitness":    ("🏋️ My workout plan",       "https://amzn.to/fitness-plan"),
    "tech":       ("⚙️ Best tech gadgets",     "https://amzn.to/tech-gadgets"),
    "space":      ("🚀 Space fan merch",        "https://amzn.to/space-merch"),
}

def _get_affiliate_line(niche: str) -> str:
    """Return a matching affiliate line for the niche, or a generic fallback."""
    niche_lower = niche.lower()
    for key, (label, url) in AFFILIATE_LINKS.items():
        if key in niche_lower:
            return f"\n\n{label} → {url}"
    return "\n\n📌 My recommended tools → https://linktr.ee/YOUR_HANDLE"


# ═══════════════════════════════════════════════════════════════
# FONT LOADER
# ═══════════════════════════════════════════════════════════════

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════════
# TEXT RENDERING
# ═══════════════════════════════════════════════════════════════

def _render_text_image(
    text: str,
    canvas_w: int,
    font_size: int,
    text_color: tuple,
    stroke_color: tuple = (0, 0, 0),
    stroke_width: int = 3,
    max_width_px: int = None,
    bg_color: tuple = None,
    padding: int = 20,
) -> np.ndarray:
    max_width_px = max_width_px or (canvas_w - 80)
    font = _load_font(font_size)
    words = text.split()
    lines, current = [], ""
    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)

    for word in words:
        test = (current + " " + word).strip()
        bb = dd.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_width_px:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_bboxes = [dd.textbbox((0, 0), ln, font=font) for ln in lines]
    line_h  = max((bb[3] - bb[1]) for bb in line_bboxes) + 6
    block_w = max((bb[2] - bb[0]) for bb in line_bboxes)

    img_w = block_w + padding * 2 + stroke_width * 2
    img_h = line_h * len(lines) + padding * 2 + stroke_width * 2
    img   = Image.new("RGBA", (img_w, img_h), bg_color or (0, 0, 0, 0))
    draw  = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        lw = bb[2] - bb[0]
        x  = (img_w - lw) // 2
        y  = padding + stroke_width + i * line_h
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(*stroke_color, 255))
        draw.text((x, y), line, font=font, fill=(*text_color, 255))

    return np.array(img)


def _text_clip(
    text: str,
    duration: float,
    font_size: int,
    text_color: tuple,
    position,
    stroke_color: tuple = (0, 0, 0),
    stroke_width: int = 3,
    bg_color: tuple = None,
    start: float = 0.0,
    opacity: float = 1.0,
) -> ImageClip:
    arr = _render_text_image(
        text, WIDTH, font_size, text_color, stroke_color, stroke_width, bg_color=bg_color
    )
    return (
        ImageClip(arr)
        .set_duration(duration)
        .set_position(position)
        .set_start(start)
        .set_opacity(opacity)
    )


# ═══════════════════════════════════════════════════════════════
# MARKER STRIPPING
# ═══════════════════════════════════════════════════════════════

def _clean_for_tts(text: str) -> str:
    text = re.sub(r'\[PAUSE\]', '...', text)
    text = re.sub(r'\[[A-Z_0-9]+\]', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def _clean_for_display(text: str) -> str:
    text = re.sub(r'\[[A-Z_0-9]+\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


# ═══════════════════════════════════════════════════════════════
# U2 — WORD-BY-WORD TTS WITH WordBoundary TIMING
# ═══════════════════════════════════════════════════════════════

async def _tts_stream_with_boundaries(text: str, audio_path: Path, voice: str):
    """
    Stream TTS and collect per-word offset events.
    Returns a list of dicts: [{word, offset_ms, duration_ms}, ...]
    offset values are in 100-nanosecond units from edge_tts — we convert to seconds.
    """
    communicate = edge_tts.Communicate(text, voice, rate=TTS_RATE, pitch=TTS_PITCH)
    word_boundaries = []
    audio_bytes = bytearray()

    async for event in communicate.stream():
        if event["type"] == "audio":
            audio_bytes.extend(event["data"])
        elif event["type"] == "WordBoundary":
            word_boundaries.append({
                "word":        event["text"],
                "offset_s":    event["offset"]   / 10_000_000,   # 100ns → seconds
                "duration_s":  event["duration"] / 10_000_000,
            })

    audio_path.write_bytes(bytes(audio_bytes))
    return word_boundaries


def generate_voiceover_with_boundaries(script_lines: list, path: Path):
    """
    Returns (voice_used, word_boundaries_list).
    word_boundaries: [{word, offset_s, duration_s}, ...]
    """
    full_text  = " ".join(line.strip() for line in script_lines if line.strip())
    clean_text = _clean_for_tts(full_text)
    voices     = [VOICE] if VOICE != "AUTO" else VOICE_CANDIDATES
    last_err   = None

    for voice in voices:
        try:
            boundaries = asyncio.run(
                _tts_stream_with_boundaries(clean_text, path, voice)
            )
            print(f"  ✅ Voice: {voice} | {len(boundaries)} word events captured")
            return voice, boundaries
        except Exception as e:
            last_err = e
            print(f"  ⚠ Voice failed: {voice} — {e}")

    raise RuntimeError(f"All TTS voices failed: {last_err}")


# ═══════════════════════════════════════════════════════════════
# U3 — GOOGLE TRENDS HOT-TOPIC INJECTION (free, no key needed)
# ═══════════════════════════════════════════════════════════════

def _fetch_trending_topics(niche: str, n: int = 5) -> list:
    """
    Pull top trending search terms related to `niche` from Google Trends.
    Returns a list of up to n strings. Falls back gracefully if pytrends fails.
    """
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=330)   # tz=330 = IST; harmless globally
        pytrends.build_payload([niche], cat=0, timeframe="now 1-d", geo="")
        related  = pytrends.related_queries()
        rising   = related.get(niche, {}).get("rising")
        if rising is not None and not rising.empty:
            topics = rising["query"].head(n).tolist()
            print(f"  🔥 Trending topics: {topics}")
            return topics
        # fallback to top queries
        top = related.get(niche, {}).get("top")
        if top is not None and not top.empty:
            return top["query"].head(n).tolist()
    except Exception as e:
        print(f"  ⚠ pytrends failed (continuing without trends): {e}")
    return []


# ═══════════════════════════════════════════════════════════════
# SCRIPT GENERATION  (U1 loop rule + U3 trends + U4 engagement)
# ═══════════════════════════════════════════════════════════════

def generate_script() -> dict:
    used       = json.loads(TOPICS_LOG.read_text()) if TOPICS_LOG.exists() else []
    avoid_str  = ", ".join(used[-40:]) if used else "none"

    # U3: fetch hot trending topics and prepend them to the prompt
    trending        = _fetch_trending_topics(NICHE)
    trending_clause = (
        f"These are RIGHT NOW trending Google searches related to this niche — "
        f"try to angle your topic around one of them for maximum discoverability: "
        f"{', '.join(trending)}. " if trending else ""
    )

    prompt = f"""You are a viral YouTube Shorts scriptwriter specialising in {NICHE}.
Write a HIGHLY ENGAGING, PUNCHY YouTube Shorts script optimised for retention and replays.

{trending_clause}

Rules:
1. Exactly 7-9 short punchy sentences.
2. First sentence MUST be a shocking hook that stops scrolling instantly (under 10 words).
3. Every sentence under 14 words.
4. Use curiosity gaps, concrete shocking details, and relentless fast pacing.
5. Easy to narrate naturally in 20-35 seconds total.
6. Include ONE specific comment prompt before the final CTA — e.g. "Comment MIND if this broke your brain." This drives comment velocity.
7. Second-to-last sentence: the comment prompt. Final sentence: "Follow for a new fact every hour!"
8. LOOP RULE — the final sentence must echo or mirror the first sentence's energy and core word/phrase, so viewers who replay immediately feel the video seamlessly loop. End mid-thought if needed so the curiosity pulls them back to the start.
9. Avoid these already-used topics: {avoid_str}

Return ONLY valid JSON (no markdown, no code fences):
{{
  "title": "catchy title with emoji, under 60 chars",
  "topic": "3-word topic",
  "hook": "sentence 1 (the shocking hook)",
  "script": ["sentence1", "sentence2", ...],
  "search_keywords": ["keyword1", "keyword2", "keyword3"],
  "description": "engaging YT description under 200 chars with keywords",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":       "llama-3.3-70b-versatile",
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.88,
            "max_tokens":  900,
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # strip markdown fences if model wraps anyway
    if raw.startswith("```"):
        raw = raw.split("```", 1)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()

    data = json.loads(raw)

    used.append(data["topic"])
    TOPICS_LOG.write_text(json.dumps(used[-200:], indent=2))
    return data


# ═══════════════════════════════════════════════════════════════
# PROCEDURAL LOFI BACKGROUND MUSIC
# ═══════════════════════════════════════════════════════════════

def generate_background_music(duration: float) -> AudioClip:
    sr  = 44100
    bpm = random.choice([80, 85, 90, 95])
    beat = 60.0 / bpm
    n   = int(duration * sr)
    buf = np.zeros(n, dtype=np.float64)

    root   = random.choice([130.81, 138.59, 146.83, 155.56, 164.81])
    ratios = [1.0, 1.189, 1.335, 1.587, 1.782, 2.0, 2.378]
    scale  = [root * r for r in ratios]
    rng    = np.random.default_rng(random.randint(0, 99999))

    # Kick (beats 1 & 3)
    for i in range(int(duration / beat) + 2):
        if i % 4 not in [0, 2]:
            continue
        idx = int(i * beat * sr)
        L   = min(int(0.28 * sr), n - idx)
        if L <= 0:
            continue
        t_k   = np.arange(L) / sr
        f_env = 80 * np.exp(-t_k * 30) + 36
        phase = 2 * np.pi * np.cumsum(f_env) / sr
        buf[idx:idx + L] += np.sin(phase) * np.exp(-t_k * 13) * 0.40

    # Snare (beats 2 & 4)
    for i in range(int(duration / beat) + 2):
        if i % 4 not in [1, 3]:
            continue
        idx = int(i * beat * sr)
        L   = min(int(0.14 * sr), n - idx)
        if L <= 0:
            continue
        t_s   = np.arange(L) / sr
        noise = rng.standard_normal(L)
        tone  = np.sin(2 * np.pi * 190 * t_s)
        env   = np.exp(-t_s * 28)
        buf[idx:idx + L] += (0.55 * noise + 0.45 * tone) * env * 0.18

    # Hi-hat (8th notes)
    eighth = beat / 2
    for i in range(int(duration / eighth) + 2):
        idx = int(i * eighth * sr)
        L   = min(int(0.05 * sr), n - idx)
        if L <= 0:
            continue
        t_h = np.arange(L) / sr
        vol = 0.07 if i % 2 == 0 else 0.035
        buf[idx:idx + L] += rng.standard_normal(L) * np.exp(-t_h * 110) * vol

    # Bass
    bass_pat = [scale[0]/2, scale[0]/2, scale[2]/2, scale[1]/2,
                scale[0]/2, scale[3]/2, scale[1]/2, scale[0]/2]
    for i in range(int(duration / beat) + 2):
        freq = bass_pat[i % len(bass_pat)]
        idx  = int(i * beat * sr)
        L    = min(int(beat * 0.87 * sr), n - idx)
        if L <= 0:
            continue
        t_b = np.arange(L) / sr
        env  = np.exp(-t_b * 3.5) * (1 - np.exp(-t_b * 80))
        bass = (
            np.sin(2 * np.pi * freq * t_b) * 0.70
            + np.sin(2 * np.pi * freq * 2 * t_b) * 0.30
        ) * env * 0.22
        buf[idx:idx + L] += bass

    # Chord pad
    chord_prog = [
        [scale[0], scale[2], scale[4]],
        [scale[1], scale[3], scale[5]],
        [scale[2], scale[4], scale[6]],
        [scale[0], scale[2], scale[4]],
    ]
    chord_dur = beat * 4
    for i in range(int(duration / chord_dur) + 2):
        chord = chord_prog[i % len(chord_prog)]
        idx   = int(i * chord_dur * sr)
        L     = min(int(chord_dur * sr), n - idx)
        if L <= 0:
            continue
        t_c = np.arange(L) / sr
        fi  = np.clip(t_c / 0.35, 0, 1)
        fo  = np.clip((chord_dur - t_c) / 0.45, 0, 1)
        env = fi * fo
        for freq in chord:
            buf[idx:idx + L] += np.sin(2 * np.pi * freq * t_c)           * env * 0.045
            buf[idx:idx + L] += np.sin(2 * np.pi * freq * 1.0022 * t_c) * env * 0.018

    # Melody
    mel_pat = [0, 2, 4, 2, 1, 3, 2, 0, 4, 2, 0, 3]
    for i in range(int(duration / beat) + 2):
        freq = scale[mel_pat[i % len(mel_pat)]]
        idx  = int(i * beat * sr)
        L    = min(int(beat * 0.70 * sr), n - idx)
        if L <= 0:
            continue
        t_m = np.arange(L) / sr
        env = np.exp(-t_m * 8.5) * (1 - np.exp(-t_m * 45))
        mel = (
            np.sin(2 * np.pi * freq * t_m) * 0.55
            + np.sin(2 * np.pi * freq * 2 * t_m) * 0.30
            + np.sin(2 * np.pi * freq * 3 * t_m) * 0.15
        ) * env * 0.065
        buf[idx:idx + L] += mel

    # Vinyl crackle
    buf += rng.standard_normal(n) * 0.0025

    # Fades + normalise
    fade = int(sr * 2.5)
    buf[:fade]  *= np.linspace(0, 1, fade)
    buf[-fade:] *= np.linspace(1, 0, fade)
    peak = np.max(np.abs(buf))
    if peak > 1e-6:
        buf = buf / peak * 0.28

    stereo = np.column_stack([buf, buf]).astype(np.float32)

    def make_frame(t):
        t_a   = np.atleast_1d(np.asarray(t, dtype=float))
        idx   = np.clip((t_a * sr).astype(int), 0, n - 1)
        frames = stereo[idx]
        return frames[0] if np.isscalar(t) else frames

    return AudioClip(make_frame, duration=duration, fps=sr)


# ═══════════════════════════════════════════════════════════════
# STOCK FOOTAGE
# ═══════════════════════════════════════════════════════════════

def fetch_stock_clips(keywords: list, target_count: int = 5) -> list:
    links = []
    for keyword in keywords[:3]:
        for orientation in ["portrait", "landscape"]:
            if len(links) >= target_count:
                break
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": keyword, "per_page": 6,
                        "orientation": orientation, "size": "medium"},
                timeout=15,
            )
            if r.status_code != 200:
                continue
            for video in r.json().get("videos", []):
                chosen = None
                for f in sorted(video["video_files"],
                                key=lambda x: x.get("width", 0), reverse=True):
                    if f.get("width", 0) <= 1080 and f.get("file_type") == "video/mp4":
                        chosen = f["link"]
                        break
                if chosen:
                    links.append(chosen)
                if len(links) >= target_count:
                    break

    paths = []
    for i, url in enumerate(links[:target_count]):
        dest = OUTPUT_DIR / f"stock_{i}.mp4"
        if dest.exists():
            paths.append(str(dest))
            continue
        try:
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
            paths.append(str(dest))
        except Exception as e:
            print(f"  ⚠ Could not download clip {i}: {e}")
    return paths


# ═══════════════════════════════════════════════════════════════
# MOTION HELPERS
# ═══════════════════════════════════════════════════════════════

def _motionize_clip(clip, seg_dur: float, seed: int):
    rng  = random.Random(seed)
    mode = rng.choice(["zoom_in", "zoom_out", "pan_left", "pan_right",
                        "pan_up", "pan_down", "drift", "dynamic"])
    base_scale = rng.uniform(1.10, 1.20)

    if mode == "zoom_in":
        clip = clip.resize(lambda t: base_scale + 0.08 * (t / max(seg_dur, 0.1)))
    elif mode == "zoom_out":
        clip = clip.resize(lambda t: base_scale - 0.08 * (t / max(seg_dur, 0.1)))
    elif mode == "dynamic":
        clip = clip.resize(
            lambda t: base_scale + 0.08 * math.sin(2 * math.pi * t / max(seg_dur, 0.1))
        )
    else:
        clip = clip.resize(base_scale)

    amp_x = rng.randint(20, 80)
    amp_y = rng.randint(15, 50)
    freq  = rng.uniform(0.08, 0.25)
    phase = rng.uniform(0, 2 * math.pi)

    if mode in ["pan_left", "pan_right", "drift", "dynamic"]:
        def pos(t):
            p = t / max(seg_dur, 0.1)
            x = int(amp_x * math.sin(2 * math.pi * freq * t + phase))
            if mode == "pan_left":
                x -= int(25 * p)
            elif mode == "pan_right":
                x += int(25 * p)
            else:
                x += int(15 * math.sin(2 * math.pi * 0.06 * t + phase / 2))
            y = int(amp_y * math.cos(2 * math.pi * freq * 0.85 * t + phase / 2))
            return (x, y)
        clip = clip.set_position(pos)
    elif mode == "pan_up":
        clip = clip.set_position(
            lambda t: (0, int(amp_y * math.sin(2 * math.pi * freq * t + phase)
                               - 20 * (t / max(seg_dur, 0.1))))
        )
    elif mode == "pan_down":
        clip = clip.set_position(
            lambda t: (0, int(amp_y * math.sin(2 * math.pi * freq * t + phase)
                               + 20 * (t / max(seg_dur, 0.1))))
        )

    clip = clip.fx(vfx.fadein, 0.10).fx(vfx.fadeout, 0.10)
    return clip


def _fit_to_916(clip):
    cw, ch = clip.size
    target = WIDTH / HEIGHT
    if cw / ch > target:
        clip = crop(clip, width=int(ch * target), height=ch, x_center=cw / 2)
    else:
        clip = crop(clip, width=cw, height=int(cw / target), y_center=ch / 2)
    return clip.resize((WIDTH, HEIGHT))


# ═══════════════════════════════════════════════════════════════
# U2 — WORD-BY-WORD CAPTION BUILDER
# ═══════════════════════════════════════════════════════════════

def _build_word_caption_clips(
    word_boundaries: list,
    total_dur: float,
    base_y: int = None,
) -> list:
    """
    Build one ImageClip per word using the WordBoundary timing from edge_tts.
    The active word is rendered in bright yellow; surrounding context words
    are rendered in white at reduced opacity — TikTok-style karaoke captions.
    """
    if not word_boundaries:
        return []

    base_y    = base_y or (HEIGHT // 2 - 80)
    font_size = 72
    clips     = []

    # Group words into caption "chunks" of ~4 words so the display isn't
    # just one word floating in isolation
    CHUNK = 4
    for chunk_start in range(0, len(word_boundaries), CHUNK):
        chunk = word_boundaries[chunk_start: chunk_start + CHUNK]
        chunk_text = " ".join(w["word"] for w in chunk)

        # For each word inside this chunk render two clips:
        #   1. The full chunk in white (always visible during the chunk)
        #   2. The active word in yellow on top, duration = word's own timing
        chunk_start_s = chunk[0]["offset_s"]
        chunk_end_s   = (
            chunk[-1]["offset_s"] + chunk[-1]["duration_s"]
            if chunk_start + CHUNK < len(word_boundaries)
            else total_dur
        )
        chunk_dur = max(chunk_end_s - chunk_start_s, 0.05)

        # White background chunk
        white_arr = _render_text_image(
            chunk_text, WIDTH,
            font_size=font_size,
            text_color=(255, 255, 255),
            stroke_color=(0, 0, 0),
            stroke_width=4,
        )
        white_clip = (
            ImageClip(white_arr)
            .set_duration(chunk_dur)
            .set_position(("center", base_y))
            .set_start(chunk_start_s)
            .set_opacity(0.70)
        )
        clips.append(white_clip)

        # Per-word yellow highlight
        for w in chunk:
            word_dur = max(w["duration_s"], 0.04)
            yellow_arr = _render_text_image(
                w["word"], WIDTH,
                font_size=font_size + 8,        # slightly bigger for pop
                text_color=(255, 230, 0),        # YouTube yellow
                stroke_color=(180, 100, 0),
                stroke_width=5,
            )
            yellow_clip = (
                ImageClip(yellow_arr)
                .set_duration(word_dur)
                .set_position(("center", base_y - 4))  # slight lift for emphasis
                .set_start(w["offset_s"])
                .set_opacity(1.0)
            )
            clips.append(yellow_clip)

    return clips


# ═══════════════════════════════════════════════════════════════
# VIDEO ASSEMBLY
# ═══════════════════════════════════════════════════════════════

def assemble_video(
    script_data: dict,
    audio_path: Path,
    stock_paths: list,
    output_path: Path,
    word_boundaries: list = None,
):
    narration = AudioFileClip(str(audio_path))
    total_dur = narration.duration

    sentences = script_data["script"]
    n_clips   = max(len(stock_paths), 1)
    seg_dur   = total_dur / n_clips

    # ── Background stock footage ──────────────────────────────────
    bg_clips = []
    for i, sp in enumerate(stock_paths):
        try:
            vc = VideoFileClip(sp, audio=False)
            vc = _fit_to_916(vc)
            vc = _motionize_clip(
                vc, seg_dur,
                seed=hash((script_data["topic"], i)) & 0xFFFFFFFF,
            )
            vc = (
                vc.fx(vfx.loop, duration=seg_dur)
                if vc.duration < seg_dur
                else vc.subclip(0, seg_dur)
            )
            bg_clips.append(vc)
        except Exception as e:
            print(f"  ⚠ Skipping clip {i}: {e}")

    if not bg_clips:
        color = random.choice([(15, 30, 60), (40, 10, 40), (10, 50, 30)])
        bg_clips = [ColorClip((WIDTH, HEIGHT), color=color).set_duration(total_dur)]

    background = (
        concatenate_videoclips(bg_clips, method="compose")
        .set_duration(total_dur)
    )

    # ── Dark overlay ───────────────────────────────────────────────
    overlay = (
        ColorClip((WIDTH, HEIGHT), color=(0, 0, 0))
        .set_opacity(0.32)
        .set_duration(total_dur)
    )

    # ── Top branding bar ───────────────────────────────────────────
    brand_bar = (
        ColorClip((WIDTH, 120), color=(25, 25, 35))
        .set_opacity(0.85)
        .set_position((0, 0))
        .set_duration(total_dur)
    )
    brand_clip = _text_clip(
        f" {NICHE.upper()} ",
        duration=total_dur,
        font_size=40,
        text_color=(255, 220, 50),
        stroke_width=2,
        stroke_color=(200, 150, 0),
        position=("center", 30),
    )

    # ── U2: Word-by-word captions (or fallback to block captions) ──
    if word_boundaries:
        caption_clips = _build_word_caption_clips(
            word_boundaries, total_dur, base_y=HEIGHT // 2 - 120
        )
        print(f"  ✅ Word-by-word captions: {len(caption_clips)} clips built")
    else:
        # Graceful fallback: block captions timed per sentence
        time_per_sent = total_dur / len(sentences)
        caption_clips = []
        for i, sentence in enumerate(sentences):
            display_text = _clean_for_display(sentence)
            cap = _text_clip(
                display_text,
                duration=time_per_sent,
                font_size=72 if i == 0 else 62,
                text_color=(255, 255, 255),
                stroke_color=(0, 0, 0),
                stroke_width=4,
                position=("center", HEIGHT // 2 - 120),
                start=i * time_per_sent,
            )
            cap = cap.fx(vfx.fadein, 0.08).fx(vfx.fadeout, 0.08)
            caption_clips.append(cap)

    # ── Bottom CTA bar ─────────────────────────────────────────────
    cta_color = random.choice([(220, 50, 50), (50, 150, 220), (100, 200, 80)])
    cta_bar   = (
        ColorClip((WIDTH, 150), color=cta_color)
        .set_opacity(0.90)
        .set_position((0, HEIGHT - 150))
        .set_duration(total_dur)
    )
    cta_clip = _text_clip(
        "FOLLOW for a new fact every hour!",
        duration=total_dur,
        font_size=44,
        text_color=(255, 255, 255),
        stroke_width=2,
        stroke_color=(0, 0, 0),
        position=("center", HEIGHT - 130),
    )

    layers = [background, overlay, brand_bar, brand_clip,
              *caption_clips, cta_bar, cta_clip]

    # ── Audio mix ──────────────────────────────────────────────────
    print("  🎵 Generating lofi background music...")
    bg_music      = generate_background_music(total_dur)
    audio_mix     = CompositeAudioClip([narration.volumex(1.0), bg_music.volumex(0.30)])

    final = CompositeVideoClip(layers, size=(WIDTH, HEIGHT)).set_audio(audio_mix)

    try:
        final.write_videofile(
            str(output_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(OUTPUT_DIR / "_tmp_audio.m4a"),
            remove_temp=True,
            threads=4,
            verbose=False,
            logger=None,
        )
    finally:
        for obj in [final, audio_mix, narration, bg_music] + bg_clips:
            try:
                obj.close()
            except Exception:
                pass

    return output_path


# ═══════════════════════════════════════════════════════════════
# YOUTUBE UPLOAD  (U6: affiliate link in description)
# ═══════════════════════════════════════════════════════════════

def upload_to_youtube(video_path: Path, script_data: dict) -> str:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    TOKEN  = Path("token.json")
    CLIENT = Path("client_secret.json")

    if CLIENT_SECRET_JSON:
        CLIENT.write_bytes(base64.b64decode(CLIENT_SECRET_JSON))
    if TOKEN_JSON:
        TOKEN.write_bytes(base64.b64decode(TOKEN_JSON))

    if not CLIENT.exists():
        raise FileNotFoundError(
            "client_secret.json missing. Add CLIENT_SECRET_JSON GitHub secret."
        )
    if not TOKEN.exists():
        raise FileNotFoundError(
            "token.json missing. Run OAuth locally once, then add TOKEN_JSON secret."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
        else:
            raise RuntimeError("Token invalid. Re-run OAuth and update TOKEN_JSON secret.")

    yt   = build("youtube", "v3", credentials=creds)
    tags = script_data["tags"] + ["Shorts", "YouTubeShorts", NICHE.replace(" ", "")]

    # U6: append niche-matched affiliate link
    affiliate_line = _get_affiliate_line(NICHE)
    desc = (
        script_data["description"]
        + "\n\n#Shorts #YouTubeShorts "
        + " ".join(f"#{t.replace(' ', '')}" for t in script_data["tags"][:6])
        + affiliate_line
    )

    body = {
        "snippet": {
            "title":       script_data["title"],
            "description": desc,
            "tags":        list(dict.fromkeys(tags)),
            "categoryId":  "27",
        },
        "status": {
            "privacyStatus":            "public",
            "selfDeclaredMadeForKids":  False,
            "madeForKids":              False,
        },
    }

    media   = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = yt.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  ⬆ Uploading... {int(status.progress() * 100)}%", end="\r")

    vid_id = response["id"]
    print(f"  ✅ Live: https://www.youtube.com/shorts/{vid_id}")
    return vid_id


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def run_pipeline(upload: bool = True):
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path  = OUTPUT_DIR / f"voice_{ts}.mp3"
    video_path  = OUTPUT_DIR / f"short_{ts}.mp4"

    print(f"\n{'═' * 62}")
    print(f"🎬 YouTube Shorts Pipeline — VIRAL EDITION v2 — {ts}")
    print(f"   NICHE: {NICHE}")
    print(f"{'═' * 62}")

    try:
        # 1. Script (with trends + loop rule + engagement bait)
        print("\n📝 Generating script (trends + loop + engagement bait)...")
        data = generate_script()
        print(f"   Title : {data['title']}")
        print(f"   Topic : {data['topic']}")
        print(f"   Hook  : {data['hook'][:70]}...")
        print(f"   Loop  : {data['script'][-1][:60]}...")

        # 2. TTS with word boundary streaming
        print("\n🎙 Generating voiceover with word-boundary timing...")
        voice_used, word_boundaries = generate_voiceover_with_boundaries(
            data["script"], audio_path
        )
        print(f"   Saved : {audio_path} | Voice: {voice_used}")

        # 3. Stock footage
        print("\n🎥 Fetching stock footage (Pexels)...")
        clips = fetch_stock_clips(data["search_keywords"], target_count=6)
        print(f"   Got {len(clips)} clips")

        # 4. Video assembly
        print("\n🎞 Assembling video (word-by-word captions)...")
        assemble_video(data, audio_path, clips, video_path,
                       word_boundaries=word_boundaries)
        print(f"   Saved : {video_path}")

        # 5. Upload
        vid_id = None
        if upload:
            print("\n📤 Uploading to YouTube...")
            vid_id = upload_to_youtube(video_path, data)

        # 6. Log
        logs = json.loads(UPLOAD_LOG.read_text()) if UPLOAD_LOG.exists() else []
        logs.append({
            "timestamp": ts,
            "niche":     NICHE,
            "title":     data["title"],
            "video_id":  vid_id,
            "file":      str(video_path),
        })
        UPLOAD_LOG.write_text(json.dumps(logs, indent=2))

        # Cleanup
        audio_path.unlink(missing_ok=True)
        for p in OUTPUT_DIR.glob("stock_*.mp4"):
            p.unlink(missing_ok=True)

        print(f"\n🎉 Done! → {video_path.name}")
        print(f"   100% free — Groq + edge_tts + Pexels + pytrends ✨")
        return vid_id

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    run_pipeline(upload=True)
