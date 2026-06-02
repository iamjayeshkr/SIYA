"""
Android Buildozer entrypoint.
Delegates to mobile Android app shell.
"""

from mobile.android.main import VaniMobileApp


if __name__ == "__main__":
    VaniMobileApp().run()
