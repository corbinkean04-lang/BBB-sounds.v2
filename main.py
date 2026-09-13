"""
BBB Sounds - Android soundboard
Rewritten from the original Tkinter/winsound PC app using Kivy so it can be
packaged into an .apk with buildozer.

Notes on what changed vs. the PC version:
- tkinter -> Kivy (tkinter/winsound don't exist on Android)
- winsound playback -> kivy.core.audio.SoundLoader (cross platform)
- Windows file dialog -> Kivy popup + Android storage permission request
- The "send audio into your game's microphone" feature relied on a Windows
  virtual audio cable driver and is not available on stock Android, so it
  has been removed. Sounds play locally on the device.
"""
import os
import json
import shutil
from pathlib import Path

from kivy.app import App
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

# --- Palette (matches the original red / black / white theme) ---
BG = (8 / 255, 8 / 255, 8 / 255, 1)
PANEL = (18 / 255, 18 / 255, 18 / 255, 1)
RED = (0.898, 0.035, 0.078, 1)
WHITE = (1, 1, 1, 1)
MUTED = (0.667, 0.667, 0.667, 1)

APP_NAME = "BBB Sounds"
AUDIO_EXTS = (".wav", ".mp3", ".ogg", ".m4a", ".flac")


def data_dir() -> Path:
    """Writable per-app storage directory (works on Android and desktop)."""
    base = Path(App.get_running_app().user_data_dir)
    sounds = base / "sounds"
    sounds.mkdir(parents=True, exist_ok=True)
    return base


def sounds_dir() -> Path:
    d = data_dir() / "sounds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "sounds.json"


class BgMixin:
    """Simple helper to give a plain Kivy widget a solid background color."""

    def set_bg(self, widget, color):
        with widget.canvas.before:
            Color(*color)
            widget._bg_rect = Rectangle(pos=widget.pos, size=widget.size)
        widget.bind(
            pos=lambda w, v: setattr(w._bg_rect, "pos", v),
            size=lambda w, v: setattr(w._bg_rect, "size", v),
        )


class SoundCard(BoxLayout, BgMixin):
    def __init__(self, app, sound_entry, **kwargs):
        super().__init__(orientation="vertical", padding=dp(10), spacing=dp(6), **kwargs)
        self.app = app
        self.entry = sound_entry
        self.set_bg(self, PANEL)
        self.size_hint_y = None
        self.height = dp(150)

        play_btn = Button(
            text="[b]PLAY[/b]",
            markup=True,
            background_color=RED,
            background_normal="",
            color=WHITE,
            size_hint_y=None,
            height=dp(48),
        )
        play_btn.bind(on_release=lambda *_: self.app.play_sound(self.entry))
        self.add_widget(play_btn)

        name_label = Label(
            text=self.entry["name"],
            color=WHITE,
            bold=True,
            size_hint_y=None,
            height=dp(28),
            shorten=True,
            shorten_from="right",
        )
        self.add_widget(name_label)

        row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        loop_box = BoxLayout(size_hint_x=0.6)
        cb = CheckBox(active=self.entry.get("loop", False), color=RED)
        cb.bind(active=lambda cb_, val: self.app.set_loop(self.entry, val))
        loop_box.add_widget(cb)
        loop_box.add_widget(Label(text="Loop", color=MUTED))
        row.add_widget(loop_box)

        remove_btn = Button(
            text="X",
            size_hint_x=0.4,
            background_color=(0.13, 0.13, 0.13, 1),
            background_normal="",
            color=(0.75, 0.75, 0.75, 1),
        )
        remove_btn.bind(on_release=lambda *_: self.app.remove_sound(self.entry))
        row.add_widget(remove_btn)
        self.add_widget(row)


class BBBSoundsApp(App, BgMixin):
    title = APP_NAME

    def build(self):
        Window.clearcolor = BG
        self.sounds = []          # list of dicts: {name, path, loop}
        self.playing = {}         # name -> Sound object currently playing
        self.volume = 0.8
        self._request_android_permissions()
        self.load_library()

        root = BoxLayout(orientation="vertical")
        self.set_bg(root, BG)

        # Header
        header = BoxLayout(size_hint_y=None, height=dp(70), padding=dp(16))
        title_label = Label(
            text="[b][color=ffffff]BBB[/color][color=e50914] SOUNDS[/color][/b]",
            markup=True,
            font_size=dp(26),
            halign="left",
        )
        title_label.bind(size=lambda w, s: setattr(w, "text_size", s))
        header.add_widget(title_label)
        add_btn = Button(
            text="+ ADD SOUND",
            bold=True,
            size_hint=(None, None),
            size=(dp(150), dp(44)),
            background_color=RED,
            background_normal="",
            color=WHITE,
        )
        add_btn.bind(on_release=self.open_file_chooser)
        header.add_widget(add_btn)
        root.add_widget(header)

        subtitle = Label(
            text="LOCAL PLAYBACK ON THIS DEVICE",
            color=MUTED,
            size_hint_y=None,
            height=dp(24),
            font_size=dp(12),
        )
        root.add_widget(subtitle)

        # Controls bar
        controls = BoxLayout(
            size_hint_y=None, height=dp(64), padding=dp(12), spacing=dp(10)
        )
        self.set_bg(controls, PANEL)
        controls.add_widget(Label(text="VOLUME", color=WHITE, bold=True, size_hint_x=0.25))
        self.slider = Slider(min=0, max=100, value=80)
        self.slider.bind(value=self.on_volume_change)
        controls.add_widget(self.slider)
        self.vol_label = Label(text="80%", color=WHITE, size_hint_x=0.15)
        controls.add_widget(self.vol_label)
        stop_btn = Button(
            text="STOP ALL",
            size_hint_x=0.3,
            background_color=(0.13, 0.13, 0.13, 1),
            background_normal="",
            color=WHITE,
        )
        stop_btn.bind(on_release=lambda *_: self.stop_all())
        controls.add_widget(stop_btn)
        root.add_widget(controls)

        # Grid of sound cards
        scroll = ScrollView()
        self.grid = GridLayout(cols=2, spacing=dp(8), padding=dp(8), size_hint_y=None)
        self.grid.bind(minimum_height=self.grid.setter("height"))
        scroll.add_widget(self.grid)
        root.add_widget(scroll)

        self.render()
        return root

    # ---- Android runtime permissions ----
    def _request_android_permissions(self):
        try:
            from android.permissions import request_permissions, Permission
            request_permissions(
                [
                    Permission.READ_EXTERNAL_STORAGE,
                    Permission.WRITE_EXTERNAL_STORAGE,
                ]
            )
        except Exception:
            pass  # not running on Android (e.g. testing on desktop)

    # ---- Library persistence ----
    def load_library(self):
        cfg = config_path()
        if cfg.exists():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                self.sounds = [s for s in data if Path(s["path"]).exists()]
            except Exception:
                self.sounds = []

    def save_library(self):
        config_path().write_text(json.dumps(self.sounds), encoding="utf-8")

    def render(self):
        self.grid.clear_widgets()
        for entry in self.sounds:
            self.grid.add_widget(SoundCard(self, entry))
        if not self.sounds:
            self.grid.add_widget(
                Label(
                    text="No sounds yet.\nTap + ADD SOUND to import one.",
                    color=MUTED,
                    size_hint_y=None,
                    height=dp(120),
                )
            )

    # ---- Adding sounds ----
    def open_file_chooser(self, *_):
        content = BoxLayout(orientation="vertical")
        chooser = FileChooserListView(
            path=os.path.expanduser("~"),
            filters=["*" + e for e in AUDIO_EXTS],
        )
        content.add_widget(chooser)
        btn_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        select_btn = Button(text="Add", background_color=RED, background_normal="", color=WHITE)
        cancel_btn = Button(text="Cancel")
        btn_row.add_widget(select_btn)
        btn_row.add_widget(cancel_btn)
        content.add_widget(btn_row)

        popup = Popup(title="Choose audio files", content=content, size_hint=(0.9, 0.9))
        cancel_btn.bind(on_release=popup.dismiss)

        def do_select(*_):
            for src in chooser.selection:
                self.import_sound(src)
            popup.dismiss()

        select_btn.bind(on_release=do_select)
        popup.open()

    def import_sound(self, src_path):
        src = Path(src_path)
        if src.suffix.lower() not in AUDIO_EXTS:
            return
        dest = sounds_dir() / src.name
        i = 1
        while dest.exists():
            dest = sounds_dir() / f"{src.stem} ({i}){src.suffix}"
            i += 1
        try:
            shutil.copy(str(src), str(dest))
        except Exception as e:
            self._show_error(f"Could not import {src.name}\n{e}")
            return
        self.sounds.append({"name": dest.stem, "path": str(dest), "loop": False})
        self.save_library()
        self.render()

    # ---- Playback ----
    def play_sound(self, entry):
        self.stop_sound(entry)
        snd = SoundLoader.load(entry["path"])
        if snd is None:
            self._show_error(f"Could not play {entry['name']}")
            return
        snd.volume = self.volume
        snd.loop = bool(entry.get("loop", False))
        snd.play()
        self.playing[entry["name"]] = snd

    def stop_sound(self, entry):
        snd = self.playing.pop(entry["name"], None)
        if snd:
            snd.stop()

    def stop_all(self):
        for snd in list(self.playing.values()):
            snd.stop()
        self.playing.clear()

    def set_loop(self, entry, value):
        entry["loop"] = bool(value)
        self.save_library()
        snd = self.playing.get(entry["name"])
        if snd:
            snd.loop = bool(value)

    def remove_sound(self, entry):
        self.stop_sound(entry)
        try:
            os.remove(entry["path"])
        except Exception:
            pass
        self.sounds = [s for s in self.sounds if s is not entry]
        self.save_library()
        self.render()

    def on_volume_change(self, slider, value):
        self.volume = value / 100.0
        self.vol_label.text = f"{int(value)}%"
        for snd in self.playing.values():
            snd.volume = self.volume

    def _show_error(self, msg):
        Popup(
            title=APP_NAME,
            content=Label(text=msg),
            size_hint=(0.8, 0.4),
        ).open()


if __name__ == "__main__":
    BBBSoundsApp().run()








