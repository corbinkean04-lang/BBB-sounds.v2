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
