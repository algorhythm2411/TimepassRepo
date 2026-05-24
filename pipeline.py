# YouTube Shorts Auto-Pipeline (v2 — Natural Narration + Viral Script Edition)
# =============================================================================
#
#   ✅ Original fixes retained from v1:
#       FIX 1: TTS markers stripped via regex before generation
#       FIX 2: Procedural lofi background music (no external API)
#       FIX 3: Clean fade-in/out captions (broken animation removed)
#       FIX 4: CI-safe base64 OAuth (no browser needed)
#
#   🆕 New in v2:
#       IMPROVE 1 — NATURAL NARRATION
#           • Sentence-by-sentence TTS generation (no more rushed single blob)
#           • Controlled silence gaps between sentences via pause_hints
#           • Pause types: hook(0.8s), tension(0.65s), pre_reveal(0.95s),
#             reveal(0.7s), normal(0.42s), cta(0.0s)
#           • TTS rate reduced from +8% → +3% (less rushed)
#           • Returns exact sentence timestamps → perfectly synced captions
#
#       IMPROVE 2 — VIRAL SCRIPT PROMPT
#           • 9-line formula: hook→anchor→tension→facts→reveal→connection→cta
#           • Banned weak words, power word list, hook templates
#           • Each sentence gets a named role that drives TTS pause length
#           • Title formula with power words + emoji
#           • pause_hints field in JSON drives audio pacing automatically
#
# Still 100% FREE — no new API keys required

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
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════

GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
PEXELS_API_KEY     = os.getenv("PEXELS_API_KEY")
CLIENT_SECRET_JSON = os.getenv("CLIENT_SECRET_JSON")   # base64-encoded client_secret.json
TOKEN_JSON         = os.getenv("TOKEN_JSON")            # base64-encoded token.json

NICHE = "amazing science facts"

VOICE = "AUTO"
VOICE_CANDIDATES = [
    "en-GB-RyanNeural",
    "en-IN-PrabhatNeural",
    "en-US-GuyNeural",
    "en-AU-WilliamNeural",
]

# ── TTS pacing ────────────────────────────────────────────────
TTS_RATE   = "+3%"     # was +8% in v1 — less rushed, more human
TTS_PITCH  = "-2Hz"    # slightly lower = more authoritative voice

# ── Natural pause durations (seconds) per sentence role ──────
PAUSE_HOOK        = 0.80   # after hook — let it land
PAUSE_TENSION     = 0.65   # after tension line — build suspense
PAUSE_PRE_REVEAL  = 0.95   # before the reveal — maximum suspense
PAUSE_REVEAL      = 0.70   # after reveal — let it hit
PAUSE_NORMAL      = 0.42   # standard between sentences
PAUSE_CTA         = 0.00   # nothing after the final CTA

PAUSE_MAP = {
    "hook":       PAUSE_HOOK,
    "tension":    PAUSE_TENSION,
    "pre_reveal": PAUSE_PRE_REVEAL,
    "reveal":     PAUSE_REVEAL,
    "normal":     PAUSE_NORMAL,
    "cta":        PAUSE_CTA,
}

SR_TTS = 44100   # sample rate for TTS audio stitching

WIDTH, HEIGHT = 1080, 1920
FPS = 30

OUTPUT_DIR  = Path("shorts_output")
TOPICS_LOG  = Path("used_topics.json")
UPLOAD_LOG  = Path("upload_log.json")
OUTPUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════
#  FONT LOADER
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
#  TEXT RENDERING
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
    line_h = max((bb[3] - bb[1]) for bb in line_bboxes) + 6
    block_w = max((bb[2] - bb[0]) for bb in line_bboxes)
    block_h = line_h * len(lines)

    img_w = block_w + padding * 2 + stroke_width * 2
    img_h = block_h + padding * 2 + stroke_width * 2

    img = Image.new("RGBA", (img_w, img_h), bg_color or (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=font)
        lw = bb[2] - bb[0]
        x = (img_w - lw) // 2
        y = padding + stroke_width + i * line_h
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
#  MARKER STRIPPING FOR TTS AND DISPLAY
# ═══════════════════════════════════════════════════════════════

def _clean_for_tts(text: str) -> str:
    text = re.sub(r'\[PAUSE\]', '...', text)
    text = re.sub(r'\[[A-Z_0-9]+\]', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _clean_for_display(text: str) -> str:
    text = re.sub(r'\[[A-Z_0-9]+\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ═══════════════════════════════════════════════════════════════
#  VOICEOVER — sentence-by-sentence with natural pauses
# ═══════════════════════════════════════════════════════════════

async def _tts_async(text: str, path: Path, voice: str):
    communicate = edge_tts.Communicate(text, voice, rate=TTS_RATE, pitch=TTS_PITCH)
    await communicate.save(str(path))


def _audio_clip_to_array(clip: AudioFileClip) -> np.ndarray:
    """Read an AudioFileClip into a (N, 2) float32 stereo numpy array."""
    dur    = clip.duration
    t      = np.arange(int(dur * SR_TTS)) / SR_TTS
    frames = clip.get_frame(t)
    if frames.ndim == 1:
        frames = np.column_stack([frames, frames])
    return frames.astype(np.float32)


def _silence_array(duration_sec: float) -> np.ndarray:
    """Return a (N, 2) float32 stereo silence array."""
    n = max(1, int(duration_sec * SR_TTS))
    return np.zeros((n, 2), dtype=np.float32)


def generate_voiceover(script_data: dict, path: Path) -> tuple:
    """
    Generates natural-sounding TTS by processing each sentence individually,
    then stitching with role-driven silence gaps between them.

    Returns:
        (voice_used: str, sentence_start_times: list[float])

    The start times are exact timestamps (seconds) for each sentence in the
    final audio file — used for perfectly synced captions in assemble_video().

    Pause after each sentence is driven by pause_hints from the script JSON:
        hook       → 0.80s  (let the hook land)
        tension    → 0.65s  (build suspense)
        pre_reveal → 0.95s  (maximum suspense before reveal line)
        reveal     → 0.70s  (let the reveal hit)
        normal     → 0.42s  (standard between sentences)
        cta        → 0.00s  (end of video — no trailing silence)
    """
    sentences   = script_data["script"]
    pause_hints = script_data.get("pause_hints", ["normal"] * len(sentences))

    # Pad hints defensively if LLM returned fewer than sentences
    while len(pause_hints) < len(sentences):
        pause_hints.append("normal")

    voices   = [VOICE] if VOICE != "AUTO" else VOICE_CANDIDATES
    last_err = None

    for voice in voices:
        try:
            segments     = []
            start_times  = []
            current_time = 0.0

            for i, sentence in enumerate(sentences):
                clean = _clean_for_tts(sentence)
                if not clean.strip():
                    start_times.append(current_time)
                    continue

                # Generate TTS for this sentence alone
                tmp = OUTPUT_DIR / f"_tmp_sent_{i}.mp3"
                asyncio.run(_tts_async(clean, tmp, voice))

                # Load, convert to numpy, close immediately to free memory
                ac  = AudioFileClip(str(tmp))
                arr = _audio_clip_to_array(ac)
                ac.close()
                tmp.unlink(missing_ok=True)

                start_times.append(current_time)
                segments.append(arr)
                current_time += len(arr) / SR_TTS

                # Add natural pause after this sentence (skip after last sentence)
                if i < len(sentences) - 1:
                    hint      = pause_hints[i]
                    pause_dur = PAUSE_MAP.get(hint, PAUSE_NORMAL)
                    if pause_dur > 0:
                        segments.append(_silence_array(pause_dur))
                        current_time += pause_dur

            # Stitch all sentence audio + pauses into one contiguous array
            full_audio = np.concatenate(segments, axis=0)
            total_dur  = len(full_audio) / SR_TTS

            # Write to the output path via a temporary AudioClip
            def make_frame(t):
                t_a = np.atleast_1d(np.asarray(t, dtype=float))
                idx = np.clip((t_a * SR_TTS).astype(int), 0, len(full_audio) - 1)
                return full_audio[idx] if t_a.shape[0] > 1 else full_audio[idx[0]]

            out_clip = AudioClip(make_frame, duration=total_dur, fps=SR_TTS)
            out_clip.write_audiofile(str(path), fps=SR_TTS, verbose=False, logger=None)
            out_clip.close()

            print(f"    ✅ Voice: {voice} | {len(sentences)} sentences | {total_dur:.1f}s total")
            return voice, start_times

        except Exception as e:
            last_err = e
            print(f"    ⚠ Voice failed: {voice} — {e}")
            for tmp in OUTPUT_DIR.glob("_tmp_sent_*.mp3"):
                tmp.unlink(missing_ok=True)

    raise RuntimeError(f"All TTS voices failed: {last_err}")


# ═══════════════════════════════════════════════════════════════
#  SCRIPT GENERATION — viral 9-line formula
# ═══════════════════════════════════════════════════════════════

def generate_script() -> dict:
    used      = json.loads(TOPICS_LOG.read_text()) if TOPICS_LOG.exists() else []
    avoid_str = ", ".join(used[-40:]) if used else "none"

    prompt = f"""You are the world's top viral YouTube Shorts scriptwriter for {NICHE}.
Your videos average 2M+ views. You deeply understand dopamine loops, curiosity gaps, and scroll psychology.

CHANNEL NICHE: {NICHE}
AVOID (already used): {avoid_str}

════ THE 9-LINE VIRAL FORMULA ════
Each line has a fixed ROLE. Never swap them.

Line 1  HOOK        — Stops the scroll. One shocking claim. Counter-intuitive, forbidden, or paradoxical.
Line 2  ANCHOR      — Back it up fast. A real number, institution, or date. Builds credibility instantly.
Line 3  TENSION     — "But here's where it gets insane..." Opens a new curiosity gap immediately.
Line 4  FACT 1      — First layer of the core revelation. Concrete and specific.
Line 5  FACT 2      — Escalate. More specific and more surprising than line 4.
Line 6  FACT 3      — The deepest cut. The detail almost nobody knows.
Line 7  REVEAL      — The punchline or holy-sh*t moment. Most jaw-dropping sentence in the script.
Line 8  CONNECTION  — Make it personal. Connect to the viewer's body, daily life, or immediate surroundings.
Line 9  CTA         — "Follow for a mind-blowing fact every day!"

════ SENTENCE RULES ════
- MAX 11 words per sentence. Under 7 words = power punch — use them often.
- RHYTHM alternates: Short. Medium sentence that builds. Short. LONGER REVEAL. Short.
- Start at least 3 sentences with a number or a shocking stat.
- BANNED WORDS (too vague/weak): fascinating, interesting, amazing, incredible, unbelievable, simply, remarkable
- USE INSTEAD: exact numbers, specific names, named scientists/institutions, concrete comparisons, precise dates
- Every sentence must make the viewer MORE curious than the one before.
- The hook must work if shown alone as a thumbnail quote.
- Each sentence under 11 words — if it is longer, split it.

════ HOOK TEMPLATES — pick the strongest for this topic ════
• "You've been [doing X] wrong your entire life."
• "In [N seconds/minutes], [shocking thing] happens inside your [body/brain/home]."
• "Scientists at [real institution] found something that breaks [a rule everyone knows]."
• "[Famous/common thing] is actually [the shocking opposite of what people believe]."
• "[N]% of people will never know this about [subject]."
• "This [object/fact] was [banned/hidden/classified] until [specific year]."
• "[Shocking number] of [things] [verb] every [time unit]. Nobody talks about it."

════ PAUSE HINTS — one per sentence, drives audio pacing ════
These values control the silence gap inserted AFTER each sentence in the final audio:
  hook        → 0.80s (let the hook land — most important gap in the video)
  tension     → 0.65s (suspense before the next revelation)
  pre_reveal  → 0.95s (use this on the sentence BEFORE line 7 — maximum suspense)
  reveal      → 0.70s (let the reveal land before moving on)
  normal      → 0.42s (standard conversational gap)
  cta         → 0.00s (end of video — no trailing silence needed)

Default pattern: ["hook","normal","tension","normal","normal","pre_reveal","reveal","normal","cta"]
You may adjust if the script rhythm demands it, but keep "hook" first and "cta" last.

════ TITLE FORMULA ════
Structure: [Power word] + [Subject] + [Verb] + [Shocking outcome]
Power words to use: Secret, Hidden, Banned, Never, Actually, Real, Deadly, Illegal, Impossible, Disturbing
Must contain: 1 exact number OR 1 power word, 1-2 relevant emojis, under 58 characters total.

BAD TITLE: "Amazing Ocean Facts 🌊"  ← too generic, no hook
GOOD TITLE: "The Ocean Sound That Kills Instantly 🌊💀"  ← specific, shocking, curiosity gap

════ DESCRIPTION ════
Under 200 characters. Punchy. Include 2-3 searchable keywords naturally. End with a question or hook.

Return ONLY valid JSON — no markdown fences, no preamble, no trailing text:
{{
  "title": "power-word title with 1-2 emojis, under 58 chars",
  "topic": "3-word topic",
  "hook": "line 1 verbatim",
  "script": [
    "line1 (hook)",
    "line2 (anchor)",
    "line3 (tension)",
    "line4 (fact 1)",
    "line5 (fact 2)",
    "line6 (fact 3)",
    "line7 (reveal)",
    "line8 (connection)",
    "line9 (cta)"
  ],
  "pause_hints": ["hook","normal","tension","normal","normal","pre_reveal","reveal","normal","cta"],
  "search_keywords": ["keyword1", "keyword2", "keyword3"],
  "description": "punchy YT description with keywords, under 200 chars",
  "tags": ["tag1","tag2","tag3","tag4","tag5"]
}}"""

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model":       "llama-3.3-70b-versatile",
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.85,
            "max_tokens":  1100,
        },
        timeout=30,
    )
    resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"].strip()
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
#  PROCEDURAL LOFI BACKGROUND MUSIC
# ═══════════════════════════════════════════════════════════════

def generate_background_music(duration: float) -> AudioClip:
    sr   = 44100
    bpm  = random.choice([80, 85, 90, 95])
    beat = 60.0 / bpm
    n    = int(duration * sr)
    buf  = np.zeros(n, dtype=np.float64)

    root   = random.choice([130.81, 138.59, 146.83, 155.56, 164.81])
    ratios = [1.0, 1.189, 1.335, 1.587, 1.782, 2.0, 2.378]
    scale  = [root * r for r in ratios]

    rng = np.random.default_rng(random.randint(0, 99999))

    # ── Kick drum (beats 1 & 3) ───────────────────────────────────────────
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
        kick  = np.sin(phase) * np.exp(-t_k * 13) * 0.40
        buf[idx:idx + L] += kick

    # ── Snare (beats 2 & 4) ──────────────────────────────────────────────
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

    # ── Hi-hat (8th notes) ───────────────────────────────────────────────
    eighth = beat / 2
    for i in range(int(duration / eighth) + 2):
        idx = int(i * eighth * sr)
        L   = min(int(0.05 * sr), n - idx)
        if L <= 0:
            continue
        t_h = np.arange(L) / sr
        vol = 0.07 if i % 2 == 0 else 0.035
        buf[idx:idx + L] += rng.standard_normal(L) * np.exp(-t_h * 110) * vol

    # ── Bass line ─────────────────────────────────────────────────────────
    bass_pat = [scale[0] / 2, scale[0] / 2, scale[2] / 2, scale[1] / 2,
                scale[0] / 2, scale[3] / 2, scale[1] / 2, scale[0] / 2]
    for i in range(int(duration / beat) + 2):
        freq = bass_pat[i % len(bass_pat)]
        idx  = int(i * beat * sr)
        L    = min(int(beat * 0.87 * sr), n - idx)
        if L <= 0:
            continue
        t_b  = np.arange(L) / sr
        env  = np.exp(-t_b * 3.5) * (1 - np.exp(-t_b * 80))
        bass = (
            np.sin(2 * np.pi * freq * t_b) * 0.70
            + np.sin(2 * np.pi * freq * 2 * t_b) * 0.30
        ) * env * 0.22
        buf[idx:idx + L] += bass

    # ── Chord pad ─────────────────────────────────────────────────────────
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
            buf[idx:idx + L] += np.sin(2 * np.pi * freq * t_c) * env * 0.045
            buf[idx:idx + L] += np.sin(2 * np.pi * freq * 1.0022 * t_c) * env * 0.018

    # ── Melody ────────────────────────────────────────────────────────────
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

    # ── Vinyl crackle ─────────────────────────────────────────────────────
    buf += rng.standard_normal(n) * 0.0025

    # ── Fades + normalize ─────────────────────────────────────────────────
    fade = int(sr * 2.5)
    buf[:fade]  *= np.linspace(0, 1, fade)
    buf[-fade:] *= np.linspace(1, 0, fade)

    peak = np.max(np.abs(buf))
    if peak > 1e-6:
        buf = buf / peak * 0.28

    stereo = np.column_stack([buf, buf]).astype(np.float32)

    def make_frame(t):
        t_a    = np.atleast_1d(np.asarray(t, dtype=float))
        idx    = np.clip((t_a * sr).astype(int), 0, n - 1)
        frames = stereo[idx]
        return frames[0] if np.isscalar(t) else frames

    return AudioClip(make_frame, duration=duration, fps=sr)


# ═══════════════════════════════════════════════════════════════
#  STOCK FOOTAGE
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
            print(f"    ⚠ Could not download clip {i}: {e}")

    return paths


# ═══════════════════════════════════════════════════════════════
#  MOTION HELPERS
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
#  VIDEO ASSEMBLY — captions now use exact sentence timestamps
# ═══════════════════════════════════════════════════════════════

def assemble_video(
    script_data: dict,
    audio_path: Path,
    stock_paths: list,
    output_path: Path,
    sentence_start_times: list,   # exact timestamps from generate_voiceover()
):
    narration  = AudioFileClip(str(audio_path))
    total_dur  = narration.duration
    sentences  = script_data["script"]
    n_clips    = max(len(stock_paths), 1)
    seg_dur    = total_dur / n_clips

    # ── Background stock footage ──────────────────────────────────────────
    bg_clips = []
    for i, sp in enumerate(stock_paths):
        try:
            vc = VideoFileClip(sp, audio=False)
            vc = _fit_to_916(vc)
            vc = _motionize_clip(
                vc, seg_dur,
                seed=hash((script_data["topic"], i)) & 0xFFFFFFFF,
            )
            vc = vc.fx(vfx.loop, duration=seg_dur) if vc.duration < seg_dur \
                 else vc.subclip(0, seg_dur)
            bg_clips.append(vc)
        except Exception as e:
            print(f"    ⚠ Skipping clip {i}: {e}")

    if not bg_clips:
        color = random.choice([(15, 30, 60), (40, 10, 40), (10, 50, 30)])
        bg_clips = [ColorClip((WIDTH, HEIGHT), color=color).set_duration(total_dur)]

    background = (
        concatenate_videoclips(bg_clips, method="compose")
        .set_duration(total_dur)
    )

    # ── Readability overlay ───────────────────────────────────────────────
    overlay = (
        ColorClip((WIDTH, HEIGHT), color=(0, 0, 0))
        .set_opacity(0.32)
        .set_duration(total_dur)
    )

    # ── Top branding bar ──────────────────────────────────────────────────
    brand_bar = (
        ColorClip((WIDTH, 120), color=(25, 25, 35))
        .set_opacity(0.85)
        .set_position((0, 0))
        .set_duration(total_dur)
    )
    brand_clip = _text_clip(
        f"  {NICHE.upper()}  ",
        duration=total_dur,
        font_size=40,
        text_color=(255, 220, 50),
        stroke_width=2,
        stroke_color=(200, 150, 0),
        position=("center", 30),
    )

    # ── Captions — timed to actual sentence durations ─────────────────────
    # Uses exact timestamps from generate_voiceover() instead of equal-time
    # guessing, so captions flash precisely when each sentence is spoken.
    caption_clips = []

    for i, sentence in enumerate(sentences):
        display_text = _clean_for_display(sentence)
        font_size    = 74 if i == 0 else 62
        base_y       = HEIGHT // 2 - 120

        t_start = sentence_start_times[i] if i < len(sentence_start_times) else 0.0
        t_end   = (sentence_start_times[i + 1]
                   if i + 1 < len(sentence_start_times)
                   else total_dur)
        dur = max(t_end - t_start, 0.3)   # at least 0.3s visible

        cap = _text_clip(
            display_text,
            duration=dur,
            font_size=font_size,
            text_color=(255, 255, 255),
            stroke_color=(0, 0, 0),
            stroke_width=4,
            position=("center", base_y),
            start=t_start,
        )
        cap = cap.fx(vfx.fadein, 0.06).fx(vfx.fadeout, 0.06)
        caption_clips.append(cap)

    # ── Bottom CTA bar ────────────────────────────────────────────────────
    cta_color = random.choice([(220, 50, 50), (50, 150, 220), (100, 200, 80)])
    cta_bar   = (
        ColorClip((WIDTH, 150), color=cta_color)
        .set_opacity(0.90)
        .set_position((0, HEIGHT - 150))
        .set_duration(total_dur)
    )
    cta_clip = _text_clip(
        "FOLLOW for a new fact every day!",
        duration=total_dur,
        font_size=44,
        text_color=(255, 255, 255),
        stroke_width=2,
        stroke_color=(0, 0, 0),
        position=("center", HEIGHT - 130),
    )

    layers = [background, overlay, brand_bar, brand_clip,
              *caption_clips, cta_bar, cta_clip]

    # ── Audio mix ─────────────────────────────────────────────────────────
    print("    🎵 Generating lofi background music...")
    bg_music      = generate_background_music(total_dur)
    bg_audio      = bg_music.volumex(0.30)
    narration_vol = narration.volumex(1.0)
    audio_mix     = CompositeAudioClip([narration_vol, bg_audio])

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
        for obj in [final, audio_mix, narration_vol, narration, bg_music] + bg_clips:
            try:
                obj.close()
            except Exception:
                pass

    return output_path


# ═══════════════════════════════════════════════════════════════
#  YOUTUBE UPLOAD (CI-safe, base64 secrets, no browser)
# ═══════════════════════════════════════════════════════════════

def upload_to_youtube(video_path: Path, script_data: dict) -> str:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    TOKEN  = Path("token.json")
    CLIENT = Path("client_secret.json")

    # Write credential files from base64-encoded env vars
    if CLIENT_SECRET_JSON:
        CLIENT.write_bytes(base64.b64decode(CLIENT_SECRET_JSON))
    if TOKEN_JSON:
        TOKEN.write_bytes(base64.b64decode(TOKEN_JSON))

    if not CLIENT.exists():
        raise FileNotFoundError(
            "client_secret.json not found and CLIENT_SECRET_JSON env var is empty.\n"
            "Add the base64-encoded contents as a GitHub secret."
        )
    if not TOKEN.exists():
        raise FileNotFoundError(
            "token.json not found and TOKEN_JSON env var is empty.\n"
            "Run the OAuth flow locally once, then base64-encode token.json\n"
            "and store it as the TOKEN_JSON GitHub secret."
        )

    # Load and refresh credentials (no browser needed in CI)
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json())
        else:
            raise RuntimeError(
                "Token is missing, invalid, or has no refresh token.\n"
                "Re-run the OAuth flow locally and update the TOKEN_JSON secret."
            )

    yt   = build("youtube", "v3", credentials=creds)
    tags = script_data["tags"] + ["Shorts", "YouTubeShorts", NICHE.replace(" ", "")]
    desc = script_data["description"] + "\n\n#Shorts #YouTubeShorts " + " ".join(
        f"#{t.replace(' ', '')}" for t in script_data["tags"][:6]
    )

    body = {
        "snippet": {
            "title":       script_data["title"],
            "description": desc,
            "tags":        list(dict.fromkeys(tags)),
            "categoryId":  "27",
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids":             False,
        },
    }

    media    = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request  = yt.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    ⬆ Uploading... {int(status.progress() * 100)}%", end="\r")

    vid_id = response["id"]
    print(f"    ✅ Live: https://www.youtube.com/shorts/{vid_id}")
    return vid_id


# ═══════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def run_pipeline(upload: bool = True):
    ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = OUTPUT_DIR / f"voice_{ts}.mp3"
    video_path = OUTPUT_DIR / f"short_{ts}.mp4"

    print(f"\n{'═' * 60}")
    print(f"🎬  YouTube Shorts Pipeline v2 — {ts}")
    print(f"{'═' * 60}")

    try:
        # ── Step 1: Generate script ───────────────────────────────────────
        print("\n📝  Generating viral script (9-line formula)...")
        data = generate_script()
        print(f"    Title : {data['title']}")
        print(f"    Topic : {data['topic']}")
        print(f"    Hook  : {data['hook'][:70]}...")
        print(f"    Pauses: {data.get('pause_hints', [])}")

        # ── Step 2: Generate voiceover ────────────────────────────────────
        print("\n🎙   Generating voiceover (sentence-by-sentence, natural pacing)...")
        voice_used, sent_times = generate_voiceover(data, audio_path)
        print(f"    Saved : {audio_path}")
        print(f"    Caption timestamps: {[f'{t:.2f}s' for t in sent_times]}")

        # ── Step 3: Fetch stock footage ───────────────────────────────────
        print("\n🎥  Fetching stock footage (Pexels)...")
        clips = fetch_stock_clips(data["search_keywords"], target_count=6)
        print(f"    Got {len(clips)} clips")

        # ── Step 4: Assemble video ────────────────────────────────────────
        print("\n🎞   Assembling video...")
        assemble_video(data, audio_path, clips, video_path, sent_times)
        print(f"    Saved : {video_path}")

        # ── Step 5: Upload ────────────────────────────────────────────────
        vid_id = None
        if upload:
            print("\n📤  Uploading to YouTube...")
            vid_id = upload_to_youtube(video_path, data)

        # ── Log result ────────────────────────────────────────────────────
        logs = json.loads(UPLOAD_LOG.read_text()) if UPLOAD_LOG.exists() else []
        logs.append({
            "timestamp":   ts,
            "title":       data["title"],
            "topic":       data["topic"],
            "voice":       voice_used,
            "duration_s":  round(sent_times[-1], 2) if sent_times else None,
            "video_id":    vid_id,
            "file":        str(video_path),
        })
        UPLOAD_LOG.write_text(json.dumps(logs, indent=2))

        # ── Cleanup temp files ────────────────────────────────────────────
        audio_path.unlink(missing_ok=True)
        for p in OUTPUT_DIR.glob("stock_*.mp4"):
            p.unlink(missing_ok=True)
        for p in OUTPUT_DIR.glob("_tmp_sent_*.mp3"):
            p.unlink(missing_ok=True)

        print(f"\n🎉  Done! → {video_path.name}")
        print(f"    100% free — no paid APIs used ✨")
        return vid_id

    except Exception as e:
        print(f"\n❌  Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        # Cleanup any leftover temp sentence files
        for p in OUTPUT_DIR.glob("_tmp_sent_*.mp3"):
            p.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    run_pipeline(upload=True)
