# Vani

Vani is a local personal assistant app with a Python package, LiveKit voice entrypoint, local UI, memory, messaging, browser, and desktop-control tools.

Start with [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md) when you need to find ownership.

## Run

```bash
bin/run_vani.sh
```

The launcher now runs the package entrypoint:

```bash
python -m vani.launcher
```

`bin/run_vani.sh` and `bin/run_vani.bat` set `PYTHONPATH` to `src/` before launching.

## Project Structure

```text
src/vani/              main Python package
src/vani/app.py        local server, UI open, LiveKit worker entrypoint
src/vani/launcher.py   process manager, hotkey, autostart
src/vani/reasoning.py  main tool router
src/vani/prompts.py    prompt assembly and live context
src/vani/memory/       memory, book learning, conversation storage
src/vani/messaging/    WhatsApp, Telegram, notifications
src/vani/browser/      browser control and search
src/vani/tools/        file, window, keyboard, mouse helpers
src/vani/services/     weather and text-chat services
src/vani/ui/           source UI HTML
assets/                videos, images, vendored browser JS
docs/                  architecture, setup, audit, archive
requirements/          dependency pins by platform
scripts/               utility/debug scripts
bin/                   runnable launch scripts
tests/                 test and smoke checks
modes/                 prompt mode text files
```

The ideal source folder is `src/vani`. Do not add new production modules at the repository root.

## Runtime Data

These are runtime/user data and should not be deleted during cleanup:

```text
.env
conversations/
book_memory_store/
vani_session.session
KMS/logs/
```

`_ui_patched.html` is generated from `src/vani/ui/ui.html` at launch and is not the UI source of truth.

## Verification

Useful checks:

```bash
PYTHONPATH=src python -m compileall src scripts tests
PYTHONPATH=src pytest
```

Dependency files live in `requirements/`:

```text
requirements/base.txt
requirements/mac.txt
requirements/windows.txt
```
