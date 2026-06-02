[app]
title = Vani
package.name = vani
package.domain = com.rudra
source.dir = ../..
source.include_exts = py,txt,json,html,png,jpg,md
version = 1.0.0
requirements = python3,kivy,requests,plyer,speechrecognition
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,RECORD_AUDIO
android.api = 33
android.minapi = 26
android.archs = arm64-v8a,armeabi-v7a
presplash.filename =
icon.filename =

[buildozer]
log_level = 2
warn_on_root = 1
