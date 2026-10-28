#!/usr/bin/env python3
"""
Local push-to-talk dictation for macOS (Apple Silicon).

Hold the hotkey -> speak -> release -> text is transcribed locally with
Whisper (MLX) and inserted into whatever field currently has focus.

Usage:
    python dictate.py                       # hold Right Option to talk
    python dictate.py --lang uk --enter     # force Ukrainian, auto-press Enter
    python dictate.py --mode type           # type characters instead of paste
    python dictate.py --model mlx-community/whisper-small-mlx   # faster/lighter
"""

from __future__ import annotations

import argparse
import collections
import os
import queue
import re
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from pynput import keyboard

SAMPLE_RATE = 16_000
MAX_SECONDS = 60

# macOS virtual key codes. We press keys by code, not by character, so that
# Cmd+V works even when the active keyboard layout is Ukrainian/Russian.
VK_V = 9
VK_RETURN = 36

# Phrases Whisper tends to hallucinate on silence / noise.
HALLUCINATIONS = (
    "дякую за перегляд",
    "дякую за увагу",
    "субтитри",
    "продолжение следует",
    "спасибо за просмотр",
    "субтитры",
    "редактор субтитров",
    "thanks for watching",
    "thank you for watching",
    "subscribe",
)

# Whole-utterance outputs Whisper produces from breath/noise. Dropped only
# when they are the *entire* result.
HALLUCINATIONS_EXACT = {"thank you", "thanks", "you", "bye", "дякую", "спасибо"}

# Kept deliberately short and content-free: Whisper tends to "continue" the
# prompt, so meaningful phrases here leak into the transcript.
LANG_PROMPTS = {
    "uk": "Привіт. Пишу українською.",
}

RECORDINGS_DIR = os.path.expanduser("~/Library/Application Support/Wisper/recordings")
KEEP_RECORDINGS = 30


def save_recording(audio: np.ndarray, text: str, meta: str) -> str | None:
    """Keep recent takes for debugging (python retest.py)."""
    import wave

    try:
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = os.path.join(RECORDINGS_DIR, stamp)
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        with wave.open(base + ".wav", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(f"{meta}\n{text}\n")
        files = sorted(x for x in os.listdir(RECORDINGS_DIR) if x.endswith(".wav"))
        for old in files[:-KEEP_RECORDINGS]:
            for ext in (".wav", ".txt"):
                try:
                    os.remove(os.path.join(RECORDINGS_DIR, old[:-4] + ext))
                except OSError:
                    pass
        return base + ".wav"
    except Exception as e:
        log(f"Could not save recording: {e}")
        return None

DICTIONARY_PATH = os.path.expanduser("~/Library/Application Support/Wisper/dictionary.txt")

DICTIONARY_TEMPLATE = """\
# Особистий словник Wisper. Зміни підхоплюються одразу, перезапуск не потрібен.
#
# 1) Слова-підказки — по одному на рядок. Whisper бачить їх перед розпізнаванням
#    і частіше пише правильно (назви, імена, терміни, сленг).
# 2) Заміни — "що розпізналось => як має бути". Застосовуються до готового тексту,
#    без урахування регістру, лише цілими словами.
#
# Рядки з # — коментарі.

Wispr
Whisper
Mac
League of Legends

Віспар => Wispr
Віспара => Wispr
Віспер => Wispr
"""


class Dictionary:
    """vocab hints + post-replacements from a plain-text file (hot-reloaded)."""

    MAX_VOCAB = 40  # Whisper prompt is limited (~224 tokens)

    def __init__(self, path: str = DICTIONARY_PATH) -> None:
        self.path = path
        self._mtime = None
        self.vocab: list[str] = []
        self.replacements: list[tuple[re.Pattern, str]] = []

    def ensure_exists(self) -> None:
        if not os.path.exists(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(DICTIONARY_TEMPLATE)

    def refresh(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.vocab, self.replacements, self._mtime = [], [], None
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        vocab, repl = [], []
        with open(self.path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=>" in line:
                    src, dst = (x.strip() for x in line.split("=>", 1))
                    if src:
                        pat = re.compile(rf"(?<!\w){re.escape(src)}(?!\w)", re.IGNORECASE)
                        repl.append((pat, dst))
                        if dst and dst not in vocab:
                            vocab.append(dst)
                elif line not in vocab:
                    vocab.append(line)
        self.vocab = vocab[: self.MAX_VOCAB]
        self.replacements = repl
        log(f"Dictionary: {len(self.vocab)} words, {len(repl)} replacements")

    def apply(self, text: str) -> str:
        for pat, dst in self.replacements:
            text = pat.sub(lambda m, d=dst: d, text)
        return text


MODEL_ALIASES = {
    "turbo": "mlx-community/whisper-large-v3-turbo",  # ~1.6 GB, fastest of the large ones
    "large": "mlx-community/whisper-large-v3-mlx",    # ~3 GB, most accurate, ~2-4x slower
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}

ENV_UTF8 ={**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def play(sound: str, enabled: bool) -> None:
    if enabled:
        subprocess.Popen(
            ["afplay", "-v", "0.25", f"/System/Library/Sounds/{sound}.aiff"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def resolve_hotkey(name: str):
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        valid = ", ".join(k.name for k in keyboard.Key)
        sys.exit(f"Unknown hotkey '{name}'. Valid names: {valid}")


def is_hallucination(text: str) -> bool:
    norm = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if not norm or norm in HALLUCINATIONS_EXACT:
        return True
    return len(norm) < 60 and any(h in norm for h in HALLUCINATIONS)


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #
class Recorder:
    """
    always_on=True keeps the mic stream open and remembers the last `preroll`
    seconds, so the first syllable spoken right as the key goes down isn't
    lost (opening a stream takes 100-300 ms; Bluetooth mics even longer).
    macOS will show the orange mic indicator the whole time.
    """

    BLOCK = 1024

    def __init__(self, always_on: bool = True, preroll: float = 0.3) -> None:
        self.always_on = always_on
        self._frames: list[np.ndarray] = []
        self._ring: collections.deque[np.ndarray] = collections.deque(
            maxlen=max(1, int(SAMPLE_RATE * preroll / self.BLOCK) + 1)
        )
        self._capturing = False
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        if always_on:
            try:
                self._open()
            except Exception as e:
                log(f"Mic open failed (will retry on key press): {e}")

    def _open(self) -> None:
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=self.BLOCK,
            callback=self._callback,
        )
        self._stream.start()

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        block = indata[:, 0].copy()
        with self._lock:
            if self._capturing:
                if len(self._frames) * self.BLOCK < SAMPLE_RATE * MAX_SECONDS:
                    self._frames.append(block)
            else:
                self._ring.append(block)

    def start(self) -> None:
        if self._stream is None or not self._stream.active:
            self._close()
            self._open()
        with self._lock:
            if self._capturing:
                return  # re-pressed during post-roll: continue the same take
            self._frames = list(self._ring) if self.always_on else []
            self._ring.clear()
            self._capturing = True

    def stop(self) -> np.ndarray:
        with self._lock:
            self._capturing = False
            frames, self._frames = self._frames, []
        if not self.always_on:
            self._close()
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32)


# --------------------------------------------------------------------------- #
# Speech-to-text
# --------------------------------------------------------------------------- #
class Transcriber:
    """
    languages: list of allowed language codes.
      - one language  -> always transcribe in it
      - several       -> detect language, but choose only among the allowed ones
      - empty         -> full Whisper auto-detect (any of ~100 languages)
    """

    def __init__(self, model: str, languages: list[str], prompt: str | None) -> None:
        import mlx.core as mx
        import mlx_whisper  # imported lazily: heavy
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
        from mlx_whisper.transcribe import ModelHolder

        self._mx = mx
        self._mw = mlx_whisper
        self._mel = log_mel_spectrogram
        self._pad = pad_or_trim
        self._n_frames = N_FRAMES
        self._n_samples = N_SAMPLES
        self._holder = ModelHolder
        self.model = model
        self.languages = languages
        self.prompt = prompt
        self.last_lang_probs: dict[str, float] = {}
        self.last_raw_top: list[tuple[str, float]] = []
        self.vocab: list[str] = []

    def _detect_language(self, audio: np.ndarray) -> str:
        mx = self._mx
        # Same model instance mlx_whisper.transcribe() uses (cached, fp16).
        model = self._holder.get_model(self.model, mx.float16)
        mel = self._mel(audio, n_mels=model.dims.n_mels, padding=self._n_samples)
        segment = self._pad(mel, self._n_frames, axis=-2).astype(mx.float16)
        _, probs = model.detect_language(segment)
        # The first language in --lang is the primary one. Probability mass of
        # every language NOT in the list (Whisper often hears Ukrainian as
        # ru/be/pl/bg…, especially on short phrases) goes to the primary
        # language. So a secondary language (en) wins only when the model is
        # actually confident about it.
        primary = self.languages[0]
        scores = {l: float(probs.get(l, 0.0)) for l in self.languages}
        scores[primary] += sum(
            float(p) for l, p in probs.items() if l not in self.languages
        )
        self.last_lang_probs = scores
        self.last_raw_top = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        return max(scores, key=scores.get)

    def transcribe(self, audio: np.ndarray) -> tuple[str, str | None]:
        if len(self.languages) == 1:
            language = self.languages[0]
        elif len(self.languages) > 1:
            language = self._detect_language(audio)
        else:
            language = None

        kwargs = dict(
            path_or_hf_repo=self.model,
            temperature=0.0,
            condition_on_previous_text=False,
            verbose=None,
        )
        if language:
            kwargs["language"] = language
        # Whisper treats the prompt as "previous text" and keeps its spelling.
        # A Ukrainian prompt stops it from drifting into Russian orthography
        # (четыре vs чотири) on short, ambiguous phrases.
        vocab = ", ".join(self.vocab) + "." if self.vocab else None
        prompt = " ".join(
            p for p in (LANG_PROMPTS.get(language or ""), vocab, self.prompt) if p
        )
        if prompt:
            kwargs["initial_prompt"] = prompt
        result = self._mw.transcribe(audio, **kwargs)
        return result.get("text", "").strip(), result.get("language", language)

    def warmup(self) -> None:
        # Loads/downloads the model and compiles kernels so the first real
        # dictation isn't slow.
        self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))


# --------------------------------------------------------------------------- #
# Text insertion
# --------------------------------------------------------------------------- #
_AX_LIB = None


def accessibility_trusted() -> bool:
    """True if this process (really: the terminal app hosting it) may post
    synthetic keyboard events. Without it macOS silently drops them."""
    global _AX_LIB
    if _AX_LIB is None:
        import ctypes

        _AX_LIB = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        _AX_LIB.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(_AX_LIB.AXIsProcessTrusted())


def input_monitoring_granted() -> bool:
    """Input Monitoring permission (needed to see the hotkey)."""
    try:
        import Quartz

        return bool(Quartz.CGPreflightListenEventAccess())
    except Exception:
        return True  # can't check -> don't block


# macOS virtual key codes (ANSI positions) for the "game" typing mode.
_US_KEYS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38,
    "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "`": 50, " ": 49,
}
_US_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8",
    "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";",
    '"': "'", "<": ",", ">": ".", "?": "/", "~": "`",
}
# Ukrainian ЙЦУКЕН: Cyrillic letter -> the Latin key at the same position.
_UK_POS = dict(zip(
    "йцукенгшщзхїфівапролджєячсмитьбю",
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.",
))
_FALLBACK_VK = 106  # F16: harmless if an app reads only key codes


def key_for_char(ch: str) -> tuple[int, bool]:
    """(virtual key code, needs shift) for one character; best effort."""
    low = ch.lower()
    if low in _UK_POS:
        return _US_KEYS[_UK_POS[low]], ch != low
    if low in _US_KEYS:
        return _US_KEYS[low], ch != low
    if ch in _US_SHIFTED:
        return _US_KEYS[_US_SHIFTED[ch]], True
    return _FALLBACK_VK, False


GAME_APP_HINTS = ("league of legends", "leagueoflegends", "riotgames", "riot client")


def frontmost_app() -> tuple[str, str]:
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(app.localizedName() or ""), str(app.bundleIdentifier() or "")
    except Exception:
        return "", ""


class Inserter:
    def __init__(self, mode: str, press_enter: bool) -> None:
        import Quartz  # comes with pynput (pyobjc-framework-Quartz)

        self.Q = Quartz
        self.mode = mode
        self.press_enter = press_enter
        self.game_mode_auto = True
        self.source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

    def _post_key(self, vk: int, cmd: bool = False) -> None:
        Q = self.Q
        flags = Q.kCGEventFlagMaskCommand if cmd else 0
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(self.source, vk, down)
            Q.CGEventSetFlags(ev, flags)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)

    def _type_unicode(self, text: str) -> None:
        Q = self.Q
        # CGEventKeyboardSetUnicodeString handles at most ~20 UTF-16 units.
        for i in range(0, len(text), 16):
            chunk = text[i:i + 16]
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(self.source, 0, down)
                Q.CGEventSetFlags(ev, 0)
                Q.CGEventKeyboardSetUnicodeString(ev, len(chunk.encode("utf-16-le")) // 2, chunk)
                Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)

    def _type_game(self, text: str, delay: float = 0.012) -> None:
        """One real key press per character (key code + unicode + shift),
        slowly. Games often ignore pastes and unicode-only events."""
        Q = self.Q
        for ch in text:
            if ch == "\n":
                continue
            vk, shift = key_for_char(ch)
            flags = Q.kCGEventFlagMaskShift if shift else 0
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(self.source, vk, down)
                Q.CGEventSetFlags(ev, flags)
                Q.CGEventKeyboardSetUnicodeString(ev, len(ch.encode("utf-16-le")) // 2, ch)
                Q.CGEventPost(Q.kCGHIDEventTap, ev)
                time.sleep(delay)

    @staticmethod
    def _get_clipboard() -> str:
        return subprocess.run(
            ["pbpaste"], capture_output=True, env=ENV_UTF8
        ).stdout.decode("utf-8", errors="replace")

    @staticmethod
    def _set_clipboard(text: str) -> None:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=ENV_UTF8)

    def insert(self, text: str) -> None:
        if not accessibility_trusted():
            # Keystrokes would be silently dropped; leave the text on the
            # clipboard so the user can at least Cmd+V it manually.
            self._set_clipboard(text)
            log("⚠️  No Accessibility permission -> can't type. Text copied to clipboard (Cmd+V).")
            return

        name, bundle = frontmost_app()
        is_game = self.game_mode_auto and any(
            h in f"{name} {bundle}".lower() for h in GAME_APP_HINTS
        )
        mode = "game" if is_game else self.mode
        log(f"Insert -> {name or '?'} ({bundle or '?'}) via {mode}")

        if mode == "game":
            self._set_clipboard(text)  # fallback: Cmd+V by hand if typing is ignored
            self._type_game(text)
        elif mode == "type":
            self._type_unicode(text)
        else:
            previous = self._get_clipboard()
            self._set_clipboard(text)
            time.sleep(0.05)
            self._post_key(VK_V, cmd=True)
            time.sleep(0.3)  # let the target app read the clipboard
            self._set_clipboard(previous)

        if self.press_enter:
            time.sleep(0.05)
            self._post_key(VK_RETURN)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
class App:
    """Core engine. Used both by the CLI (run()) and the menu-bar app (start())."""

    def __init__(self, args: argparse.Namespace, on_state=None) -> None:
        self.args = args
        self.hotkey = resolve_hotkey(args.key)
        self.recorder = Recorder(always_on=getattr(args, "mic_always_on", True))
        self.inserter = Inserter(args.mode, args.enter)
        self.jobs: queue.Queue[np.ndarray] = queue.Queue()
        self.recording = False
        self.cancelled = False
        self.transcriber: Transcriber | None = None
        self.state = "loading"  # loading | idle | recording | busy | error
        self._on_state = on_state or (lambda s: None)
        self._model_lock = threading.Lock()
        self.last_text = ""
        self.dictionary = Dictionary(getattr(args, "dict", None) or DICTIONARY_PATH)
        self.dictionary.ensure_exists()

    def _set_state(self, state: str) -> None:
        self.state = state
        self._on_state(state)

    # -- settings that can change at runtime -------------------------------- #
    @staticmethod
    def parse_languages(spec: str) -> list[str]:
        return [l.strip() for l in spec.split(",") if l.strip()]

    def set_languages(self, spec: str) -> None:
        self.args.lang = spec
        if self.transcriber:
            self.transcriber.languages = self.parse_languages(spec)
        log(f"Languages: {spec or 'auto (any)'}")

    def load_model(self, model: str | None = None) -> None:
        """Blocking. Call from a background thread in the GUI."""
        with self._model_lock:
            if model:
                self.args.model = MODEL_ALIASES.get(model, model)
            self._set_state("loading")
            log(f"Loading model {self.args.model} (first run downloads it)…")
            t0 = time.time()
            try:
                languages = self.parse_languages(self.args.lang)
                log(f"Languages: {', '.join(languages) if languages else 'auto (any)'}")
                t = Transcriber(self.args.model, languages, self.args.prompt)
                t.warmup()
                self.transcriber = t
            except Exception as e:
                log(f"Model load error: {e}")
                self._set_state("error")
                return
            log(f"Model ready in {time.time() - t0:.1f}s")
            self._set_state("idle")

    # -- keyboard callbacks (must stay fast) -------------------------------- #
    def on_press(self, key) -> None:
        if key == self.hotkey and not self.recording:
            if self.transcriber is None:
                return  # still loading
            self.recording = True
            self.cancelled = False
            try:
                self.recorder.start()
            except Exception as e:  # mic busy / no permission
                self.recording = False
                log(f"Mic error: {e}")
                return
            self._set_state("recording")
            play("Tink", self.args.sounds)
        elif key == keyboard.Key.esc and self.recording:
            self.cancelled = True

    def on_release(self, key) -> None:
        if key == self.hotkey and self.recording:
            self.recording = False
            if self.cancelled:
                self.recorder.stop()
                log("Cancelled")
                play("Basso", self.args.sounds)
                self._set_state("idle")
                return
            play("Pop", self.args.sounds)
            self._set_state("busy")
            # Keep recording a bit after release: people let go of the key
            # while still finishing the last word.
            threading.Thread(target=self._finish_recording, daemon=True).start()

    def _finish_recording(self) -> None:
        time.sleep(self.args.postroll)
        if self.recording:  # key pressed again during post-roll: keep going
            return
        self.jobs.put(self.recorder.stop())

    # -- worker ------------------------------------------------------------- #
    def _process(self, audio: np.ndarray) -> None:
        seconds = len(audio) / SAMPLE_RATE
        if seconds < 0.3:
            log("Too short, skipped")
            return
        rms = float(np.sqrt(np.mean(audio**2)))
        if rms < self.args.min_rms:
            log(f"Too quiet (rms={rms:.4f}), skipped")
            return

        self.dictionary.refresh()
        t0 = time.time()
        with self._model_lock:
            self.transcriber.vocab = self.dictionary.vocab
            text, lang = self.transcriber.transcribe(audio)
        dt = time.time() - t0

        if is_hallucination(text):
            log(f"Dropped likely hallucination: {text!r}")
            return

        probs = self.transcriber.last_lang_probs
        probs_s = ""
        if len(probs) > 1:
            raw = ", ".join(f"{k}={v:.2f}" for k, v in self.transcriber.last_raw_top)
            probs_s = (
                " (" + ", ".join(f"{k}={v:.2f}" for k, v in probs.items())
                + f" | raw: {raw})"
            )
        fixed = self.dictionary.apply(text)
        if fixed != text:
            log(f"Dictionary fixed: {text!r} -> {fixed!r}")
            text = fixed
        log(f"{seconds:.1f}s audio -> {dt:.2f}s | [{lang}{probs_s}] {text}")
        peak = float(np.max(np.abs(audio)))
        save_recording(audio, text,
                       f"model={self.args.model} lang={lang}{probs_s} rms={rms:.4f} peak={peak:.3f}")
        self.last_text = text
        self.inserter.insert(text)

    def worker(self) -> None:
        while True:
            audio = self.jobs.get()
            try:
                self._process(audio)
            except Exception as e:
                log(f"Error: {e}")
            finally:
                if not self.recording and self.jobs.empty():
                    self._set_state("idle")

    def log_permissions(self, host: str = "your terminal app") -> None:
        if accessibility_trusted():
            log("Accessibility: OK")
        else:
            log("⚠️  Accessibility: NOT granted. Text will only be copied to clipboard.")
            log(f"   System Settings → Privacy & Security → Accessibility → add/enable {host},")
            log("   then quit it completely (Cmd+Q) and reopen.")

    def start_listener(self) -> keyboard.Listener:
        """(Re)creates the global hotkey listener. macOS refuses the event tap
        while permissions are missing, and an existing tap doesn't come alive
        after they're granted — so call this again once they are."""
        old = getattr(self, "listener", None)
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()
        return self.listener

    def start(self) -> keyboard.Listener:
        """Non-blocking: starts worker + global hotkey listener."""
        threading.Thread(target=self.worker, daemon=True).start()
        return self.start_listener()

    def run(self) -> None:
        """CLI mode (blocking)."""
        self.load_model()
        self.log_permissions()
        self.start()
        log(
            f"Ready. Hold [{self.args.key}] to talk, release to insert. "
            f"Esc while holding = cancel. Ctrl+C to quit."
        )
        while True:
            time.sleep(3600)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local push-to-talk dictation for macOS")
    p.add_argument("--key", default="alt_r",
                   help="hotkey to hold (pynput Key name): alt_r, ctrl_r, cmd_r, shift_r, f13… (default: alt_r = Right Option)")
    p.add_argument("--model", default="large",
                   help="turbo | large | medium | small, or any MLX Whisper repo on Hugging Face "
                        "(default: large)")
    p.add_argument("--lang", default="uk,en",
                   help="allowed languages, comma-separated. One = fixed language; "
                        "several = auto-pick among them; '' = any language. Default: uk,en")
    p.add_argument("--prompt", default=None,
                   help="initial prompt with vocabulary hints, e.g. 'ганк, мід, джангл, Xerath'")
    p.add_argument("--mode", choices=["paste", "type"], default="paste",
                   help="paste via clipboard (fast) or type character by character")
    p.add_argument("--enter", action="store_true", help="press Enter after inserting")
    p.add_argument("--min-rms", type=float, default=0.004,
                   help="skip recordings quieter than this (filters accidental presses)")
    p.add_argument("--dict", default=DICTIONARY_PATH,
                   help=f"personal dictionary file (default: {DICTIONARY_PATH})")
    p.add_argument("--postroll", type=float, default=0.35,
                   help="seconds to keep recording after the key is released (default 0.35)")
    p.add_argument("--mic-on-demand", dest="mic_always_on", action="store_false",
                   help="open the mic only while the key is held (no orange indicator, "
                        "but the first ~0.2 s may be cut)")
    p.add_argument("--no-sounds", dest="sounds", action="store_false",
                   help="disable start/stop sounds")
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.model = MODEL_ALIASES.get(args.model, args.model)

    if sys.platform != "darwin":
        sys.exit("This prototype is macOS-only.")

    try:
        App(args).run()
    except KeyboardInterrupt:
        print()
        log("Bye")


if __name__ == "__main__":
    main()
