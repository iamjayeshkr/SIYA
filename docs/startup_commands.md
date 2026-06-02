# Vani Startup Commands

Run these from the project folder:

```bash
cd "/Users/rudra/Documents/Vanni---My-Personal-Assistant-main 5"
```

## Manual Launch

```bash
bin/run_vani.sh
```

Starts Vani using the local virtual environment. The script now launches through `python -m vani.launcher`, so if Vani is already running it will not start a duplicate copy.

## Wake Command

```bash
bin/wake_vani.sh
```

Use this command from a macOS Shortcut, Automator action, terminal alias, or any external hotword tool for the phrase "wake up Vani". It starts or focuses Vani and prints:

```text
hmm bolo Rudra
```

## Always-On Wake Listener

```bash
bin/listen_vani_wake.sh
```

Runs a lightweight macOS background listener using the native speech command recognizer. It listens for phrases like:

```text
wake up Vani
hey Vani
Vani sun
utho Vani
activate Vani
```

When it hears a wake phrase, it starts or focuses Vani and says:

```text
hmm bolo Rudra
```

Install it as a login background service:

```bash
PYTHONPATH=src venv311/bin/python -m vani.wake_listener --install
```

Remove it:

```bash
PYTHONPATH=src venv311/bin/python -m vani.wake_listener --uninstall
```

## Install Auto-Startup

```bash
PYTHONPATH=src venv311/bin/python -m vani.launcher --install
```

Installs the macOS LaunchAgent:

```text
/Users/rudra/Library/LaunchAgents/com.rudra.vani.plist
```

After this, Vani starts automatically when the user logs in.

## Auto-Startup Runtime Command

```bash
PYTHONPATH=src venv311/bin/python -m vani.launcher --autostart
```

This is the command used by the LaunchAgent at login. It checks whether Vani is already running before launching. If Vani is already active, it exits without starting another instance.

## Uninstall Auto-Startup

```bash
PYTHONPATH=src venv311/bin/python -m vani.launcher --uninstall
```

Removes the LaunchAgent so Vani no longer starts automatically at login.

## Check LaunchAgent Status

```bash
launchctl print gui/$(id -u)/com.rudra.vani
```

Shows whether the LaunchAgent is loaded/running and which command it is using.

## View Startup Logs

```bash
tail -n 80 ~/Library/Logs/vani_launcher.log
tail -n 80 ~/Library/Logs/vani_launcher_err.log
```

Shows normal launcher output and startup errors from the LaunchAgent.

## Already-Running Check

```bash
venv311/bin/python - <<'PY'
import vani.launcher as vani_launcher
print(vani_launcher.is_vani_running())
PY
```

Prints `True` when Vani appears to be running. The launcher checks local child processes, the `127.0.0.1:5500` UI server port, and existing `vani.app` processes.

## Force Stop Current Vani Processes

```bash
lsof -ti:5500 | xargs kill -9
```

Stops the process currently listening on the local Vani UI port. Use only when Vani is stuck and normal quit/stop is not working.

## Greeting Behavior

Vani does not greet immediately on startup. After the first detected user voice input, she says:

```text
Welcome boss
```

This happens once per session.
