# Step 1 Complete: Fixed Missing `pyautogui` Import in `keyboard_mouse_control.py`

## Changes Made:
1. **Dynamic Import Declaration**:
   Defined a global `pyautogui` variable initialized to `None`, and implemented a thread-safe dynamic resolver helper `_ensure_pyautogui()` to import `pyautogui` lazily on demand.
2. **Lazy Volume Control Fix**:
   Updated `control_volume` to invoke `_ensure_pyautogui().press(keys[action])` instead of the top-level name, preventing NameError on Windows environment volume sweeps.
3. **Lazy Swipe Gesture Fix**:
   Patched the `swipe_gesture` function to query `_ensure_pyautogui()` before retrieving screen dimensions (`size()`), mouse coordinates, and drawing paths (`moveTo()`, `dragTo()`).

## Verification Result:
* Dynamic imports eliminate top-level hardware accessibility detection loops during script initialization (avoiding macOS accessibility crashes on workers).
* Safe execution on target environments without raising `NameError` for missing global names.
