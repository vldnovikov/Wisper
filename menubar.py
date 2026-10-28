#!/usr/bin/env python3
"""
Wisper — menu-bar app around dictate.py.

Run directly:   python menubar.py
Or build an app: ./build_app.sh   (creates /Applications/Wisper.app)
"""

from __future__ import annotations

import json
import os
import site
import subprocess
import sys
import threading
from pathlib import Path

# When started by Wisper.app's native launcher, the venv isn't active:
# add its site-packages (processing .pth files) explicitly.
if os.environ.get("WISPER_SITE"):
    site.addsitedir(os.environ["WISPER_SITE"])
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Inside Wisper.app sys.executable is the launcher binary; anything that
# re-runs "python" (multiprocessing, tqdm locks) must get the real interpreter.
if os.environ.get("WISPER_PYTHON"):
    sys.executable = os.environ["WISPER_PYTHON"]
    import multiprocessing

    multiprocessing.set_executable(sys.executable)


def _single_instance_or_exit() -> None:
    import fcntl

    lock_path = Path.home() / "Library/Application Support/Wisper/wisper.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    global _LOCK_FILE
    _LOCK_FILE = open(lock_path, "w")
    try:
        fcntl.flock(_LOCK_FILE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[Wisper] another instance is already running — exiting", flush=True)
        sys.exit(0)

# Hide the Python rocket from the Dock: must happen before NSApplication starts.
try:
    from Foundation import NSBundle

    _info = NSBundle.mainBundle().infoDictionary()
    if _info is not None:
        _info["LSUIElement"] = "1"
except Exception:
    pass

import rumps

import dictate as d

if os.environ.get("WISPER_SELFTEST"):
    import mlx_whisper  # noqa: F401  (heaviest dependency)

    print(f"[selftest] OK: python {sys.version.split()[0]}, executable {sys.executable}")
    sys.exit(0)

APP_NAME = "Wisper"
CONFIG_PATH = Path.home() / "Library/Application Support/Wisper/settings.json"
LOG_PATH = Path.home() / "Library/Logs/Wisper.log"
LAUNCH_AGENT = Path.home() / "Library/LaunchAgents/com.vnovikov.wisper.plist"

DEFAULTS = {
    "model": "large",
    "lang": "uk,en",
    "enter": False,
    "mode": "paste",
    "sounds": True,
    "key": "alt_r",
}

ICONS = {
    "loading": "⏳",
    "idle": "🎙",
    "recording": "🔴",
    "busy": "💭",
    "error": "⚠️",
}

LANG_OPTIONS = [
    ("Українська + English", "uk,en"),
    ("Тільки українська", "uk"),
    ("Only English", "en"),
    ("Будь-яка мова", ""),
]
MODEL_OPTIONS = [
    ("Turbo — швидка", "turbo"),
    ("Large — точніша, повільніша", "large"),
]
KEY_OPTIONS = [
    ("Правий Option ⌥", "alt_r"),
    ("Правий Control ⌃", "ctrl_r"),
    ("Правий Command ⌘", "cmd_r"),
    ("F13", "f13"),
]
KEY_LABEL = {v: k for k, v in KEY_OPTIONS}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(CONFIG_PATH.read_text()))
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(s, indent=2, ensure_ascii=False))


def request_accessibility_prompt() -> None:
    """Shows the system dialog and adds the app to the Accessibility list."""
    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception as e:
        d.log(f"AX prompt failed: {e}")


def open_privacy_pane(pane: str) -> None:
    subprocess.Popen(
        ["open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"]
    )


class WisperApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(APP_NAME, title=ICONS["loading"], quit_button=None)
        self.s = load_settings()
        self.s["model"] = "large"  # only the large model is used

        args = d.build_parser().parse_args([])
        args.model = d.MODEL_ALIASES.get(self.s["model"], self.s["model"])
        args.lang = self.s["lang"]
        args.enter = self.s["enter"]
        args.mode = self.s["mode"]
        args.sounds = self.s["sounds"]
        args.key = self.s["key"]
        self.engine = d.App(args)

        # --- menu ---------------------------------------------------------- #
        self.status_item = rumps.MenuItem("Завантаження моделі…")
        self.perm_item = rumps.MenuItem("⚠️ Немає дозволу Accessibility — натисни",
                                        callback=self.fix_accessibility)
        self.last_item = rumps.MenuItem("Скопіювати останній текст", callback=self.copy_last)

        self.lang_menu = rumps.MenuItem("Мова")
        for label, value in LANG_OPTIONS:
            item = rumps.MenuItem(label, callback=self._make_cb(self.set_lang, value))
            item.state = int(value == self.s["lang"])
            self.lang_menu.add(item)

        self.key_menu = rumps.MenuItem("Клавіша")
        for label, value in KEY_OPTIONS:
            item = rumps.MenuItem(label, callback=self._make_cb(self.set_key, value))
            item.state = int(value == self.s["key"])
            self.key_menu.add(item)

        self.enter_item = rumps.MenuItem("Натискати Enter після вставки", callback=self.toggle_enter)
        self.enter_item.state = int(self.s["enter"])
        self.type_item = rumps.MenuItem("Друкувати посимвольно (замість Cmd+V)",
                                        callback=self.toggle_type)
        self.type_item.state = int(self.s["mode"] == "type")
        self.sounds_item = rumps.MenuItem("Звуки", callback=self.toggle_sounds)
        self.sounds_item.state = int(self.s["sounds"])

        self.login_item = rumps.MenuItem("Запускати при вході в систему", callback=self.toggle_login)
        self.login_item.state = int(LAUNCH_AGENT.exists())

        self.menu = [
            self.status_item,
            self.perm_item,
            None,
            self.last_item,
            None,
            self.lang_menu,
            self.key_menu,
            self.enter_item,
            self.type_item,
            self.sounds_item,
            None,
            self.login_item,
            rumps.MenuItem("Словник…", callback=self.open_dictionary),
            rumps.MenuItem("Відкрити лог", callback=self.open_log),
            rumps.MenuItem("Вийти", callback=lambda _: rumps.quit_application()),
        ]

        self._last_state = None
        self._last_trusted = None
        self._timer = rumps.Timer(self._tick, 0.15)
        self._timer.start()
        threading.Thread(target=self._boot, daemon=True).start()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_cb(fn, value):
        return lambda sender: fn(sender, value)

    def _save(self) -> None:
        save_settings(self.s)

    def _boot(self) -> None:
        d.log("=== Wisper started ===")
        if not d.accessibility_trusted():
            request_accessibility_prompt()
        self.engine.log_permissions(host=APP_NAME)
        if not d.input_monitoring_granted():
            d.log("⚠️  Input Monitoring: NOT granted (hotkey won't be seen)")
        self.engine.start()
        self.engine.load_model()

    # UI updates only from the main thread (timer).
    def _tick(self, _) -> None:
        state = self.engine.state
        if state != self._last_state:
            self._last_state = state
            self.title = ICONS.get(state, "🎙")
            key = KEY_LABEL.get(self.s["key"], self.s["key"])
            self.status_item.title = {
                "loading": "Завантаження моделі…",
                "idle": f"Готово — тримай {key}",
                "recording": "Запис… (Esc — скасувати)",
                "busy": "Розпізнаю…",
                "error": "Помилка — дивись лог",
            }.get(state, state)

        ax = d.accessibility_trusted()
        im = d.input_monitoring_granted()
        perms = (ax, im)
        if perms != self._last_trusted:
            was = self._last_trusted
            self._last_trusted = perms
            if ax and im:
                self.perm_item.title = "✅ Дозволи: OK"
            else:
                missing = [n for n, ok in (("Accessibility", ax), ("Input Monitoring", im)) if not ok]
                self.perm_item.title = f"⚠️ Немає дозволу: {', '.join(missing)} — натисни"
            # Permission just granted while running -> the old event tap is dead,
            # recreate it so the hotkey starts working without a relaunch.
            if was is not None and ax and im and was != perms:
                d.log("Permissions granted — restarting hotkey listener")
                self.engine.start_listener()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_only(menu: rumps.MenuItem, sender: rumps.MenuItem) -> None:
        for item in menu.values():
            item.state = int(item is sender)

    def set_lang(self, sender, value: str) -> None:
        self._check_only(self.lang_menu, sender)
        self.s["lang"] = value
        self._save()
        self.engine.set_languages(value)

    def set_model(self, sender, value: str) -> None:
        if value == self.s["model"]:
            return
        self._check_only(self.model_menu, sender)
        self.s["model"] = value
        self._save()
        threading.Thread(target=self.engine.load_model, args=(value,), daemon=True).start()

    def set_key(self, sender, value: str) -> None:
        self._check_only(self.key_menu, sender)
        self.s["key"] = value
        self._save()
        self.engine.args.key = value
        self.engine.hotkey = d.resolve_hotkey(value)
        self._last_state = None  # refresh status text
        d.log(f"Hotkey: {value}")

    def toggle_enter(self, sender) -> None:
        sender.state = int(not sender.state)
        self.s["enter"] = bool(sender.state)
        self.engine.inserter.press_enter = self.s["enter"]
        self._save()

    def toggle_type(self, sender) -> None:
        sender.state = int(not sender.state)
        self.s["mode"] = "type" if sender.state else "paste"
        self.engine.inserter.mode = self.s["mode"]
        self._save()

    def toggle_sounds(self, sender) -> None:
        sender.state = int(not sender.state)
        self.s["sounds"] = bool(sender.state)
        self.engine.args.sounds = self.s["sounds"]
        self._save()

    def toggle_login(self, sender) -> None:
        app_path = os.environ.get("WISPER_APP")
        if LAUNCH_AGENT.exists():
            subprocess.run(["launchctl", "unload", str(LAUNCH_AGENT)], capture_output=True)
            LAUNCH_AGENT.unlink()
            sender.state = 0
            return
        if not app_path:
            rumps.alert("Wisper", "Автозапуск працює тільки коли Wisper запущено як застосунок "
                                  "(Wisper.app), а не з терміналу.")
            return
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.vnovikov.wisper</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/open</string><string>-a</string><string>{app_path}</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
""")
        sender.state = 1

    def fix_accessibility(self, _) -> None:
        ax, im = d.accessibility_trusted(), d.input_monitoring_granted()
        if ax and im:
            rumps.alert("Wisper", "Усі дозволи вже є ✅")
            return
        if not ax:
            request_accessibility_prompt()
            open_privacy_pane("Privacy_Accessibility")
        else:
            try:
                import Quartz

                Quartz.CGRequestListenEventAccess()
            except Exception:
                pass
            open_privacy_pane("Privacy_ListenEvent")
        rumps.alert(
            "Wisper",
            "Увімкни Wisper у списку Accessibility (і в Input Monitoring).\n"
            "Якщо Wisper вже там — видали його (−) і додай знову (+).\n"
            "Потім перезапусти Wisper.",
        )

    def copy_last(self, _) -> None:
        if self.engine.last_text:
            self.engine.inserter._set_clipboard(self.engine.last_text)

    def open_dictionary(self, _) -> None:
        self.engine.dictionary.ensure_exists()
        subprocess.Popen(["open", "-t", self.engine.dictionary.path])

    def open_log(self, _) -> None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.touch(exist_ok=True)
        subprocess.Popen(["open", "-a", "Console", str(LOG_PATH)])


if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.exit("macOS only.")
    _single_instance_or_exit()
    WisperApp().run()
