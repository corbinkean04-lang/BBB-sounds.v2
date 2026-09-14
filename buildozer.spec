[app]
title = BBB Sounds
package.name = bbbsounds
package.domain = org.bbbsounds

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0

requirements = python3,kivy==2.3.0

orientation = portrait
fullscreen = 0

# Android permissions needed to read/import audio files from device storage
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO

android.api = 34
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
