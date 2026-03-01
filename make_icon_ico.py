"""
One-time script: create assets/icon.ico from assets/icon.png for the PyInstaller EXE icon.
Windows uses .ico for the executable icon. Run from project root: python make_icon_ico.py
"""
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Install Pillow: pip install Pillow")
    raise

_project_root = Path(__file__).resolve().parent
# Prefer assets inside project; fallback to parent (e.g. ../assets)
png_path = _project_root / "assets" / "icon.png"
if not png_path.exists():
    png_path = _project_root.parent / "assets" / "icon.png"
ico_path = _project_root / "assets" / "icon.ico"

if not png_path.exists():
    print(f"Not found: {png_path}")
    raise SystemExit(1)

(_project_root / "assets").mkdir(parents=True, exist_ok=True)

img = Image.open(png_path)
# Provide common sizes for a good Windows .ico (Explorer, taskbar)
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img.save(ico_path, format="ICO", sizes=sizes)
print(f"Created: {ico_path}")
