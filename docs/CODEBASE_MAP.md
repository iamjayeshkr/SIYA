# Vani Codebase Map

Use this file when you do not know where to look.

## Start Here

| Need | File or folder |
|---|---|
| Launch the app | `bin/run_vani.sh` |
| Process manager / hotkey / autostart | `src/vani/launcher.py` |
| Local HTTP server, UI open, LiveKit room setup | `src/vani/app.py` |
| Main tool router / assistant actions | `src/vani/reasoning.py` |
| Prompt/personality/time context | `src/vani/prompts.py`, `src/vani/prompt_manager.py`, `modes/` |
| Frontend source | `src/vani/ui/ui.html` |
| Generated frontend with LiveKit token | `_ui_patched.html` |

Do not edit `_ui_patched.html` as the source of truth. It is generated from `src/vani/ui/ui.html` at launch.

## Package Layout

```text
src/vani/
  app.py                 local UI server and LiveKit worker entrypoint
  launcher.py            process manager, tray, hotkey, autostart
  reasoning.py           legacy tool router
  prompts.py             prompt assembly and dynamic context
  prompt_manager.py      prompt mode loader
  config.py              project/package/asset paths
  memory/
    book_memory.py
    context_cache.py
    conversation_writer.py
    learning_memory.py
    memory_loop.py
    memory_store.py
  messaging/
    client.py
  browser/
    control.py
    search.py
  tools/
    file_opener.py
    keyboard_mouse.py
    window_control.py
  audio/
    priority.py
    talking_tom.py
  services/
    text_chat.py
    weather.py
  ui/
    ui.html
```

## Feature Locations

| Feature | Owner |
|---|---|
| Book/PDF upload endpoint | `src/vani/app.py` -> `/analyze_document` |
| Book extraction/retrieval | `src/vani/memory/book_memory.py` |
| Text chat routing | `src/vani/services/text_chat.py` |
| Voice/tool routing | `src/vani/reasoning.py` |
| LiveKit worker entrypoint | `src/vani/app.py` -> `entrypoint()` |
| Browser control | `src/vani/browser/control.py` |
| Google search/date-time helper | `src/vani/browser/search.py` |
| File/folder opening | `src/vani/tools/file_opener.py` |
| Window/app switching | `src/vani/tools/window_control.py` |
| Keyboard/mouse control | `src/vani/tools/keyboard_mouse.py` |
| WhatsApp/Telegram/macos notifications | `src/vani/messaging/client.py` |
| Weather | `src/vani/services/weather.py` |
| Name pronunciation | `src/vani/name_pronunciation.py` |

## Assets

```text
assets/video/      mp4/webm video assets
assets/images/     png/gif/webp image assets
assets/vendor/     browser vendor files, including LiveKit client JS
```

The app serves these assets from the local HTTP server, so UI references like `/talking1.mp4` still work.

## Requirements

```text
requirements/base.txt       shared dependency pins
requirements/mac.txt        macOS dependency pins used by bin/run_vani.sh
requirements/windows.txt    Windows dependency pins used by bin/run_vani.bat
```

## Runtime / Generated Files

These are runtime/user data. Do not delete them during structure cleanup:

```text
.env
conversations/
book_memory_store/
vani_session.session
KMS/logs/
```

These are generated/cache/build outputs and should stay ignored:

```text
__pycache__/
*.pyc
_ui_patched.html
*.class
```

## Archived Legacy Files

Legacy Java/test artifacts are preserved under `docs/archive/legacy/` instead of being deleted.

## Naming Rules

Use these rules for new files:

```text
lower_snake_case.py
lower_snake_case.md
no abbreviations like CTRL
no typos like opner / whether
production Python code lives under src/vani/
debug utilities live under scripts/
dependency pins live under requirements/
tests live under tests/
```
