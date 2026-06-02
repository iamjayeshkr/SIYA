# Structure Migration Notes

Main code now lives in `src/vani`.

## File Mapping

| Old/root file or folder | New location |
|---|---|
| `vani_app.py` | `src/vani/app.py` |
| `vani_launcher.py` | `src/vani/launcher.py` |
| `vani_reasoning.py` / `jarvis_reasoning.py` | `src/vani/reasoning.py` |
| `vani_prompts.py` / `Jarvis_prompts.py` | `src/vani/prompts.py` |
| `prompt_manager.py` | `src/vani/prompt_manager.py` |
| `context_cache.py` | `src/vani/memory/context_cache.py` |
| `learning_memory.py` | `src/vani/memory/learning_memory.py` |
| `memory_loop.py` | `src/vani/memory/memory_loop.py` |
| `memory_store.py` | `src/vani/memory/memory_store.py` |
| `vani_conversation_writer.py` | `src/vani/memory/conversation_writer.py` |
| `vani_core/features/book_memory.py` | `src/vani/memory/book_memory.py` |
| `vani_core/services/text_chat.py` | `src/vani/services/text_chat.py` |
| `jarvis_get_whether.py` / `vani_weather.py` | `src/vani/services/weather.py` |
| `vani_messaging.py` | `src/vani/messaging/client.py` |
| `vani_browser_ctrl.py` / `vani_browser_control.py` | `src/vani/browser/control.py` |
| `Jarvis_google_search.py` / `vani_google_search.py` | `src/vani/browser/search.py` |
| `Jarvis_file_opner.py` / `vani_file_opener.py` | `src/vani/tools/file_opener.py` |
| `Jarvis_window_CTRL.py` / `vani_window_control.py` | `src/vani/tools/window_control.py` |
| `keyboard_mouse_CTRL.py` / `keyboard_mouse_control.py` | `src/vani/tools/keyboard_mouse.py` |
| `vani_audio_priority.py` | `src/vani/audio/priority.py` |
| `vani_talking_tom.py` | `src/vani/audio/talking_tom.py` |
| `vani_name_pronunciation.py` | `src/vani/name_pronunciation.py` |
| `ui.html` | `src/vani/ui/ui.html` |
| `livekit-client.umd.min.js` | `assets/vendor/livekit-client.umd.min.js` |
| `opening2.mp4`, `talking1.mp4`, `vani_avatar.mp4`, `listening_optimized.mp4` | `assets/video/` |
| `listening.gif`, `vani_idle.png` | `assets/images/` |
| `audit.md`, `setup.md`, `requirements.md`, `productionReady/` | `docs/` |
| `requirements.txt` | `requirements/base.txt` |
| `requirements_mac.txt` | `requirements/mac.txt` |
| `requirements_windows.txt` | `requirements/windows.txt` |
| `run_vani.sh` | `bin/run_vani.sh` |
| `run_vani.bat` | `bin/run_vani.bat` |
| `debug_whatsapp.py`, `generate_audit.py` | `scripts/` |
| `test_optimization.py` | `tests/test_optimization.py` |
| `Test.java`, `Vani.java`, `test.html` | `docs/archive/legacy/` |

## Files Intentionally Not Moved

These contain user/runtime data and stayed at the project root:

```text
conversations/
book_memory_store/
vani_session.session
KMS/logs/
.env
```

## Verification Run

```bash
venv311/bin/python -m compileall src scripts tests
PYTHONPATH=src venv311/bin/python tests/test_optimization.py
PYTHONPATH=src venv311/bin/python -m vani.app --help
PYTHONPATH=src venv311/bin/python -m vani.launcher --help
```
