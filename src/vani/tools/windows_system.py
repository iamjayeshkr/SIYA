"""
vani/tools/windows_system.py
Low-level Windows optimization, system settings changes, process force control, and command execution.
"""

import ctypes
import os
import sys
import re
import subprocess
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

def is_admin() -> bool:
    """Check if the current process is running with Administrator privileges on Windows."""
    if sys.platform != "win32":
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def _clean_temp_dir(path: str) -> float:
    """Recursively delete all files and subdirectories in path without deleting the path itself.
    Returns the total size of deleted files in MB.
    """
    import shutil
    deleted_bytes = 0
    if not os.path.exists(path) or not os.path.isdir(path):
        return 0.0
    try:
        items = os.listdir(path)
    except PermissionError:
        logger.warning(f"[WINDOWS_SYSTEM] Permission denied for path: {path}")
        return 0.0
    except Exception as e:
        logger.warning(f"[WINDOWS_SYSTEM] Error listing path: {path} - {e}")
        return 0.0

    for item in items:
        item_path = os.path.join(path, item)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                try:
                    deleted_bytes += os.path.getsize(item_path)
                except Exception:
                    pass
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                # Calculate size of subfolder before deleting
                for root, _, files in os.walk(item_path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            deleted_bytes += os.path.getsize(fp)
                        except Exception:
                            pass
                shutil.rmtree(item_path, ignore_errors=True)
        except Exception:
            pass
    return deleted_bytes / (1024 * 1024)

def _run_powershell(script: str) -> tuple[int, str, str]:
    """Helper to run a PowerShell script synchronously and return (code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command execution timed out."
    except Exception as e:
        return -1, "", str(e)

@tool
async def windows_system_control(action: str, query: str = "") -> str:
    """
    Perform Windows system optimizations, retrieve system status, modify settings,
    force open/close processes, or run low-level PowerShell commands.

    Args:
        action: One of 'system_status', 'optimize', 'change_setting', 'execute_command', 'force_close_app', 'force_open_app'.
        query: Specific parameters or script details needed for the chosen action.
    """
    if sys.platform != "win32":
        return "❌ Ye tool sirf Windows operating system par chal sakta hai."

    act = action.lower().strip()
    admin_active = is_admin()

    # ── 1. SYSTEM STATUS ──
    if act == "system_status":
        script = (
            "$cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average | Select-Object -ExpandProperty Average; "
            "$os = Get-CimInstance Win32_OperatingSystem; "
            "$ram_total = $os.TotalVisibleMemorySize; "
            "$ram_free = $os.FreePhysicalMemory; "
            "$ram_used_pct = [math]::Round((($ram_total - $ram_free) / $ram_total) * 100); "
            "$disk = Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\"; "
            "$disk_free = [math]::Round($disk.FreeSpace / 1GB, 2); "
            "$disk_total = [math]::Round($disk.Size / 1GB, 2); "
            "Write-Output \"CPU:$cpu|RAM:$ram_used_pct|DiskFree:$disk_free|DiskTotal:$disk_total\""
        )
        code, stdout, stderr = _run_powershell(script)
        if code != 0 or not stdout:
            return f"❌ System status check nahi ho paya: {stderr or 'Unknown error'}"

        parts = stdout.split("|")
        stats = {}
        for part in parts:
            if ":" in part:
                k, v = part.split(":", 1)
                stats[k] = v

        admin_status = "Admin Mode (Elevated) ✅" if admin_active else "User Mode (Standard) ⚠️"
        cpu_val = stats.get("CPU", "Unknown")
        ram_val = stats.get("RAM", "Unknown")
        disk_free = stats.get("DiskFree", "Unknown")
        disk_total = stats.get("DiskTotal", "Unknown")

        return (
            f"💻 **Windows System Status:**\n"
            f"- **Privilege Level:** {admin_status}\n"
            f"- **CPU Usage:** {cpu_val}%\n"
            f"- **RAM Usage:** {ram_val}%\n"
            f"- **Disk Space (C:):** {disk_free} GB free out of {disk_total} GB"
        )

    # ── 2. OPTIMIZE WINDOWS ──
    elif act == "optimize":
        cleared_mb = 0.0
        
        # Clean User Temp
        user_temp = os.environ.get("TEMP")
        if user_temp:
            cleared_mb += _clean_temp_dir(user_temp)
            
        # Clean System Temp
        sys_temp = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Temp")
        cleared_mb += _clean_temp_dir(sys_temp)
        
        # Clear Prefetch (only if admin)
        if admin_active:
            prefetch_dir = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Prefetch")
            cleared_mb += _clean_temp_dir(prefetch_dir)

        # Clear Recycle Bin & Flush DNS via PowerShell (fast commands, no file recursing)
        powershell_script = (
            "Clear-RecycleBin -Force -Confirm:$false -ErrorAction SilentlyContinue; "
            "Clear-DnsClientCache -ErrorAction SilentlyContinue; "
            "ipconfig /flushdns | Out-Null;"
        )
        
        # Run PowerShell tasks with a 5s timeout limit
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell_script],
                capture_output=True,
                text=True,
                timeout=5
            )
        except Exception:
            pass  # Fail gracefully on individual tasks if they lock up
        
        cleared_mb = round(cleared_mb, 2)
        admin_note = "" if admin_active else " (Prefetch folder cleaning skipped, run as Admin for full cleanup)"
        return (
            f"🧹 **Windows Optimization Complete!**\n"
            f"- **Recycle Bin & Temp files** clean ho gaye.\n"
            f"- **DNS cache** flush kar di gayi hai.\n"
            f"- **Space Cleared:** {cleared_mb} MB system storage free ki gayi.{admin_note}"
        )

    # ── 3. CHANGE SETTING ──
    elif act == "change_setting":
        q = query.lower().strip()
        
        # Dark / Light Theme
        if "dark" in q or "theme black" in q:
            script = (
                "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'AppsUseLightTheme' -Value 0 -Force; "
                "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'SystemUsesLightTheme' -Value 0 -Force"
            )
            code, _, stderr = _run_powershell(script)
            return "✅ Windows Dark Theme enable ho gaya." if code == 0 else f"❌ Registry modify karne mein error: {stderr}"
        
        elif "light" in q or "theme white" in q:
            script = (
                "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'AppsUseLightTheme' -Value 1 -Force; "
                "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'SystemUsesLightTheme' -Value 1 -Force"
            )
            code, _, stderr = _run_powershell(script)
            return "✅ Windows Light Theme enable ho gaya." if code == 0 else f"❌ Registry modify karne mein error: {stderr}"

        # Power plans
        elif "power" in q or "plan" in q or "performance" in q or "saver" in q:
            # High Performance: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c
            # Balanced: 381b4222-f694-41f0-9685-ff5bb260df2e
            # Power Saver: a1841308-3541-4fab-bc81-f71556f20b4a
            if "performance" in q or "high" in q:
                guid = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
                name = "High Performance"
            elif "saver" in q or "low" in q:
                guid = "a1841308-3541-4fab-bc81-f71556f20b4a"
                name = "Power Saver"
            else:
                guid = "381b4222-f694-41f0-9685-ff5bb260df2e"
                name = "Balanced"

            code, _, stderr = _run_powershell(f"powercfg /setactive {guid}")
            return f"🔋 Power plan ko **{name}** par set kar diya." if code == 0 else f"❌ Power plan set nahi hua: {stderr}"

        # Monitor Brightness
        elif "brightness" in q or "chamkila" in q or "bright" in q or "brigt" in q:
            # Check for relative up/down
            if "down" in q or "kam" in q or "ghata" in q or "decrease" in q:
                get_script = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness"
                _, current_str, _ = _run_powershell(get_script)
                try:
                    curr = int(current_str) if current_str.isdigit() else 50
                except Exception:
                    curr = 50
                val = max(0, curr - 10)
            elif "up" in q or "badha" in q or "increase" in q or "tez" in q:
                get_script = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue).CurrentBrightness"
                _, current_str, _ = _run_powershell(get_script)
                try:
                    curr = int(current_str) if current_str.isdigit() else 50
                except Exception:
                    curr = 50
                val = min(100, curr + 10)
            else:
                match = re.search(r"(\d+)", q)
                val = int(match.group(1)) if match else 50
                val = max(0, min(100, val))

            # Modern Invoke-CimMethod command (more compatible on Win 10/11 than Get-WmiObject)
            script = f"Invoke-CimMethod -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -MethodName WmiSetBrightness -Arguments @{{Timeout = 1; Brightness = {val}}} -ErrorAction SilentlyContinue"
            code, _, stderr = _run_powershell(script)
            
            # Fallback to older Get-WmiObject if Invoke-CimMethod returns non-zero
            if code != 0:
                fallback_script = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue).WmiSetBrightness(1, {val})"
                code, _, stderr = _run_powershell(fallback_script)
                
            if code == 0:
                return f"🔆 Screen brightness को **{val}%** kar diya."
            else:
                return f"❌ Brightness change nahi ho payi: WMI method unsupported on this display hardware."

        # Screen Sleep Timeout
        elif "sleep" in q or "timeout" in q or "turn off screen" in q:
            match = re.search(r"(\d+)", q)
            minutes = int(match.group(1)) if match else 15
            seconds = minutes * 60
            script = f"powercfg /change monitor-timeout-ac {minutes}; powercfg /change standby-timeout-ac {minutes}"
            code, _, stderr = _run_powershell(script)
            return f"💤 Screen sleep timeout ko **{minutes} minutes** par set kar diya." if code == 0 else f"❌ Sleep setting change nahi ho paya: {stderr}"

        # Net adapter toggling (requires Admin)
        elif "wifi" in q or "wi-fi" in q or "internet adapter" in q:
            if not admin_active:
                return "❌ Network adapter switch karne ke liye Siya ko Administrator privileges chahiye. Kripya app ko Admin mode mein chalayein."
            
            if "disable" in q or "off" in q or "band" in q:
                script = "Disable-NetAdapter -Name 'Wi-Fi' -Confirm:$false"
                status = "Disable"
            else:
                script = "Enable-NetAdapter -Name 'Wi-Fi' -Confirm:$false"
                status = "Enable"
                
            code, _, stderr = _run_powershell(script)
            return f"🌐 Wi-Fi adapter ko successfully **{status}** kar diya." if code == 0 else f"❌ Network adapter toggle control fail: {stderr}"

        else:
            return "⚠️ Samjha nahi kaunsi setting change karni hai. Aap 'dark theme', 'light theme', 'brightness 80', 'sleep timeout 10', ya 'power saver' try kar sakte hain."

    # ── 4. EXECUTE CUSTOM COMMAND ──
    elif act == "execute_command":
        if not query:
            return "❌ Command script specify nahi ki gayi."
        
        # Security restrictions
        q_lower = query.lower()
        unsupported = ["format ", "rmdir /s", "del /s", "drop database", "shutdown /s /t 0"]
        if any(term in q_lower for term in unsupported):
            return f"❌ Security validation failed: Low level override script matches restricted operations."

        code, stdout, stderr = _run_powershell(query)
        result_str = stdout if code == 0 else f"{stdout}\n[Error code {code}]: {stderr}"
        if not result_str.strip():
            result_str = "Command run successfully with empty output."
        return f"⚙️ **PowerShell Output:**\n```\n{result_str[:800]}\n```"

    # ── 5. FORCE CLOSE APP ──
    elif act == "force_close_app":
        if not query:
            return "❌ Process/App name specify nahi kiya."
        
        # Clean process name (e.g. Notepad.exe -> Notepad)
        proc_name = query.replace(".exe", "").strip()
        script = f"Stop-Process -Name '{proc_name}' -Force -ErrorAction SilentlyContinue; if ($?) {{ 'OK' }} else {{ 'FAIL' }}"
        
        # Fallback to Taskkill if powershell fails or process not found directly
        code, stdout, _ = _run_powershell(script)
        if stdout == "OK":
            return f"✅ '{proc_name}' ko force close (kill) kar diya."
        
        # Try Taskkill as secondary
        taskkill_cmd = f"taskkill /f /im {proc_name}.exe /t"
        proc = subprocess.run(taskkill_cmd, shell=True, capture_output=True, text=True)
        if proc.returncode == 0:
            return f"✅ '{proc_name}' process kill ho gaya."
        
        # Try matching window title
        taskkill_title = f"taskkill /f /fi \"WINDOWTITLE eq {query}*\" /t"
        proc_title = subprocess.run(taskkill_title, shell=True, capture_output=True, text=True)
        if proc_title.returncode == 0:
            return f"✅ '{query}' window band ho gayi."

        return f"❌ '{query}' process active nahi mili ya band nahi ho payi."

    # ── 6. FORCE OPEN APP ──
    elif act == "force_open_app":
        if not query:
            return "❌ App name/path specify nahi kiya."
        
        # Check if run as admin is requested in query
        as_admin = "admin" in query.lower()
        cleaned_path = re.sub(r"\b(as admin|admin mode|run as admin)\b", "", query, flags=re.I).strip()
        
        if as_admin:
            script = f"Start-Process -FilePath '{cleaned_path}' -Verb RunAs -ErrorAction SilentlyContinue; if ($?) {{ 'OK' }} else {{ 'FAIL' }}"
        else:
            script = f"Start-Process -FilePath '{cleaned_path}' -ErrorAction SilentlyContinue; if ($?) {{ 'OK' }} else {{ 'FAIL' }}"
            
        code, stdout, stderr = _run_powershell(script)
        if stdout == "OK":
            priv = " (Elevated as Admin)" if as_admin else ""
            return f"✅ '{cleaned_path}' successfully open kar diya{priv}."
        
        # Fallback using standard shell launch
        try:
            os.startfile(cleaned_path)
            return f"✅ '{cleaned_path}' open ho gaya."
        except Exception as e:
            return f"❌ '{cleaned_path}' launch nahi ho paya: {stderr or str(e)}"

    return f"❌ Action '{action}' support nahi hai."
