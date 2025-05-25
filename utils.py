# --- utils.py ---
import os
import sys
from PIL import Image, ImageTk

def resource_path(relative_path):
    """Resolve a resource path, supporting PyInstaller bundles."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

def _load_icon(path, size):
    """Load & resize an asset; return a PhotoImage or None on failure."""
    try:
        img = Image.open(resource_path(path)).resize(size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

def format_price(c):
    """Convert a copper value into 'Xg Ys Zc' format."""
    if c is None:
        return "—"
    return f"{c//10000}g {(c%10000)//100}s {c%100}c"

