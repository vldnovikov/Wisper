#!/usr/bin/env python3
"""
Re-transcribe a saved Wisper recording with several settings to see what
actually helps.

    python retest.py                 # latest recording in ./recordings
    python retest.py path/to.wav

Writes the report next to the recording (<name>.retest.txt) and prints it.
"""

from __future__ import annotations

import os
import sys
import time
import wave

import numpy as np

import dictate as d

HERE = os.path.dirname(os.path.abspath(__file__))


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == d.SAMPLE_RATE and w.getsampwidth() == 2
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def audio_stats(a: np.ndarray) -> str:
    dur = len(a) / d.SAMPLE_RATE
    rms = float(np.sqrt(np.mean(a**2)))
    peak = float(np.max(np.abs(a)))
    clip = float(np.mean(np.abs(a) > 0.99)) * 100
    spec = np.abs(np.fft.rfft(a)) ** 2
    freqs = np.fft.rfftfreq(len(a), 1 / d.SAMPLE_RATE)
    total = spec[freqs > 80].sum() + 1e-12
    hi = spec[freqs > 3800].sum() / total * 100
    # Bluetooth headset mics (HFP) are band-limited to ~4 kHz (or 8 kHz)
    band = "⚠️ схоже на вузькосмуговий мікрофон (Bluetooth?)" if hi < 0.5 else "ok"
    return (f"duration={dur:.2f}s rms={rms:.4f} peak={peak:.3f} clipped={clip:.2f}% "
            f"energy>3.8kHz={hi:.2f}% ({band})")


def main() -> None:
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        rec = d.RECORDINGS_DIR
        wavs = sorted(f for f in os.listdir(rec) if f.endswith(".wav")) if os.path.isdir(rec) else []
        if not wavs:
            sys.exit("Записів ще немає. Перезапусти Wisper (Вийти → open /Applications/Wisper.app), "
                     "надиктуй фразу і запусти retest.py знову.")
        path = os.path.join(rec, wavs[-1])

    audio = load_wav(path)
    lines = [f"File: {path}", audio_stats(audio)]
    sidecar = path[:-4] + ".txt"
    if os.path.exists(sidecar):
        lines.append("Original: " + open(sidecar, encoding="utf-8").read().strip().replace("\n", " | "))
    lines.append("")

    uk_prompt = d.LANG_PROMPTS["uk"]
    variants = [
        ("large", ["uk"], None, "uk, без підказки"),
        ("large", ["uk"], uk_prompt, "uk, коротка підказка"),
        ("large", [], None, "автодетект, без підказки"),
        ("large", ["uk", "en"], None, "uk+en вибір, без підказки"),
        ("turbo", ["uk"], None, "turbo, uk, без підказки"),
    ]

    import mlx_whisper  # noqa: F401

    original_prompts = dict(d.LANG_PROMPTS)
    for model, langs, prompt, label in variants:
        d.LANG_PROMPTS.clear()
        if prompt:
            d.LANG_PROMPTS["uk"] = prompt
        t = d.Transcriber(d.MODEL_ALIASES[model], langs, None)
        t.transcribe(np.zeros(d.SAMPLE_RATE, dtype=np.float32))  # load/warm up
        t0 = time.time()
        text, lang = t.transcribe(audio)
        dt = time.time() - t0
        line = f"[{model:5} | {label:28}] {dt:4.2f}s [{lang}] {text}"
        print(line, flush=True)
        lines.append(line)
    d.LANG_PROMPTS.update(original_prompts)

    # Cloud engines (only if an OpenAI key is available). Costs ~$0.003-0.006/min.
    import cloud

    key = cloud.get_key("openai")
    if key:
        for model in ("gpt-4o-transcribe", "gpt-transcribe", "gpt-4o-mini-transcribe"):
            t0 = time.time()
            try:
                text = cloud.openai_transcribe(audio, model, key)
            except Exception as e:
                text = f"ERROR: {e}"
            line = f"[cloud | {model:28}] {time.time() - t0:4.2f}s {text}"
            print(line, flush=True)
            lines.append(line)
    else:
        lines.append("(cloud engines skipped: no OpenAI key)")

    out = path[:-4] + ".retest.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines[:3]))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
