"""
VANI Phase 9 — Cross-platform adapter layer.

Single source of truth for platform detection and OS-specific behavior.
Replaces scattered IS_MAC / IS_WIN checks throughout the codebase.

Usage:
    from vani.core.platform import _adapter
    _adapter.notify("Vani ready", "Voice conversation ready hai.")
    _adapter.open_browser("http://127.0.0.1:5500/ui")
"""
from __future__ import annotations
import sys
import os
import logging

logger = logging.getLogger("vani.platform")

# ── Platform flags ─────────────────────────────────────────────────────────────
IS_MAC    = sys.platform == "darwin"
IS_WIN    = sys.platform == "win32"
IS_LINUX  = sys.platform.startswith("linux")
IS_MOBILE = False   # Set to True by mobile bootstrap (future)
IS_WEB    = False   # Set to True by web adapter (future)


# ── Adapter classes ────────────────────────────────────────────────────────────

class PlatformAdapter:
    """Base adapter — desktop behavior by default (Linux / unknown)."""
    name = "desktop"

    def open_browser(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def open_app_browser(self, url: str) -> None:
        """Open browser in app/kiosk mode for the VANI UI."""
        self.open_browser(url)

    def get_screenshot(self):
        """Returns an mss screenshot or None if unavailable."""
        try:
            import mss
            with mss.mss() as sct:
                return sct.grab(sct.monitors[0])
        except Exception as e:
            logger.debug(f"[platform] screenshot unavailable: {e}")
            return None

    def notify(self, title: str, message: str) -> None:
        """Send a desktop notification. No-op on unsupported platforms."""
        pass

    def is_notification_enabled(self) -> bool:
        return os.getenv("VANI_MAC_NOTIFICATIONS", "1") == "1"


class MacAdapter(PlatformAdapter):
    name = "mac"

    def open_app_browser(self, url: str) -> None:
        """Tries Chrome in app mode, falls back to Safari, then webbrowser."""
        import subprocess
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(chrome_path):
            try:
                subprocess.Popen(
                    [chrome_path, f"--app={url}", "--window-size=420,680",
                     "--window-position=0,0", "--disable-extensions"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                logger.warning(f"[platform] Chrome launch failed: {e}")
        try:
            subprocess.Popen(["open", "-a", "Safari", url])
            return
        except Exception:
            pass
        super().open_browser(url)

    def notify(self, title: str, message: str) -> None:
        if not IS_MAC or not self.is_notification_enabled():
            return
        try:
            import subprocess, json
            script = (
                f'display notification {json.dumps(message)} '
                f'with title {json.dumps(title)}'
            )
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.debug(f"[platform] macOS notify failed: {e}")


class WindowsAdapter(PlatformAdapter):
    name = "windows"

    def open_app_browser(self, url: str) -> None:
        """Tries Chrome in app mode, falls back to webbrowser."""
        import subprocess
        chrome_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for chrome in chrome_candidates:
            if os.path.exists(chrome):
                try:
                    subprocess.Popen(
                        [chrome, f"--app={url}", "--window-size=420,680"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    return
                except Exception as e:
                    logger.warning(f"[platform] Chrome (Win) launch failed: {e}")
                    break
        super().open_browser(url)

    def notify(self, title: str, message: str) -> None:
        """Windows toast via win10toast if available, silent fallback."""
        try:
            from win10toast import ToastNotifier  # type: ignore
            ToastNotifier().show_toast(title, message, duration=4, threaded=True)
        except Exception:
            pass


class WebAdapter(PlatformAdapter):
    """Used when VANI runs as a web service (no local desktop)."""
    name = "web"

    def open_browser(self, url: str) -> None:
        logger.info(f"[platform:web] open_browser({url}) — no-op in web mode")

    def open_app_browser(self, url: str) -> None:
        self.open_browser(url)

    def get_screenshot(self):
        return None  # Not available in web context

    def notify(self, title: str, message: str) -> None:
        pass  # Handled via WebSocket push to browser UI


class LinuxAdapter(PlatformAdapter):
    name = "linux"

    def open_app_browser(self, url: str) -> None:
        """Try Chromium/Chrome in app mode, fall back to xdg-open."""
        import subprocess
        for binary in ("google-chrome", "chromium-browser", "chromium"):
            try:
                subprocess.Popen(
                    [binary, f"--app={url}", "--window-size=420,680"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except FileNotFoundError:
                continue
        try:
            subprocess.Popen(["xdg-open", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            super().open_browser(url)

    def notify(self, title: str, message: str) -> None:
        """Desktop notification via notify-send if available."""
        try:
            import subprocess
            subprocess.Popen(
                ["notify-send", title, message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


# ── Active adapter (singleton) ─────────────────────────────────────────────────

def _build_adapter() -> PlatformAdapter:
    if IS_WEB:
        return WebAdapter()
    if IS_MAC:
        return MacAdapter()
    if IS_WIN:
        return WindowsAdapter()
    if IS_LINUX:
        return LinuxAdapter()
    return PlatformAdapter()


_adapter: PlatformAdapter = _build_adapter()


# ── Convenience shim — keeps any old import working ───────────────────────────
def notify_mac(title: str, message: str) -> None:
    """
    Legacy shim for old _notify_mac() calls in app.py.
    Routes through the active adapter so it works on all platforms.
    """
    _adapter.notify(title, message)
