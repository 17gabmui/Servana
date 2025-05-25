#!/usr/bin/env python3
from ui import ServanaApp

import sys

# only do this on Win when running as a .exe or from python.exe
if sys.platform.startswith("win"):
    try:
        import ctypes
        # detach this process from its console
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass

if __name__ == "__main__":
    app = ServanaApp()
    app.run()
