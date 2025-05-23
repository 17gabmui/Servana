#!/usr/bin/env python3
import subprocess
import shutil
import os
import sys

# Configuration
SCRIPT_NAME   = "servana3.py"
ICON_PATH     = "servana_icon_pixelated.ico"
APP_NAME      = "Servana"
SPEC_FILE     = f"{os.path.splitext(SCRIPT_NAME)[0]}.spec"
BUILD_DIR     = "build"
DIST_DIR      = "dist"

def clean():
    """Remove previous build artifacts."""
    for path in (BUILD_DIR, DIST_DIR, SPEC_FILE):
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
    print("✅ Cleaned previous build artifacts.")

def build():
    """Invoke PyInstaller to create the executable."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        f"--icon={ICON_PATH}",
        f"--name={APP_NAME}",
        SCRIPT_NAME
    ]
    print("⚙️  Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"✅ Build succeeded! Executable is at {os.path.join(DIST_DIR, APP_NAME + ('.exe' if os.name=='nt' else ''))}")

if __name__ == "__main__":
    try:
        clean()
        build()
    except subprocess.CalledProcessError:
        print("❌ Build failed.", file=sys.stderr)
        sys.exit(1)
