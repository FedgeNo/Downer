#!/bin/bash
# Install Downer and register its desktop launcher as the Markdown handler.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

echo "Installing Downer..."

python3 -c "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('GtkSource', '3.0'); gi.require_version('WebKit2', '4.1'); from gi.repository import Gtk, GtkSource, WebKit2" || {
    echo 'Missing GTK dependencies: install python3-gobject, gtksourceview3, and webkit2gtk4.1.' >&2
    exit 1
}
python3 - <<'PY'
import gi
import importlib
from gi.repository import GLib
for name, version in [('Gspell', '1'), ('GtkSpell', '3.0')]:
    try:
        gi.require_version(name, version)
        module = importlib.import_module('gi.repository.' + name)
        available = False
        if name == 'Gspell':
            available = module.Language.get_default() is not None
        else:
            available = bool(module.Checker.get_language_list())
        if available:
            print(f'Optional spellchecking available through {name}.')
            break
    except (ValueError, ImportError, OSError, GLib.Error, RuntimeError):
        continue
else:
    print('Optional spellchecking unavailable: install Gspell 1 or GtkSpell 3 and a system spelling dictionary.')
PY
if ! command -v pandoc &>/dev/null; then
    echo 'Optional bibliography citations unavailable: install Pandoc to enable citeproc. Footnotes and reference links work without it.'
fi
python3 -m pip install --user --upgrade "$SCRIPT_DIR/.."

# Create applications directory
mkdir -p "$APPLICATIONS_DIR"

# Copy desktop file
cp "$SCRIPT_DIR/downer.desktop" "$APPLICATIONS_DIR/downer.desktop"
python3 - "$APPLICATIONS_DIR/downer.desktop" <<'PY'
import sys
import sysconfig
from pathlib import Path
desktop = Path(sys.argv[1])
launcher = Path(sysconfig.get_path('scripts', scheme='posix_user')) / 'downer'
content = desktop.read_text().replace('Exec=downer %F', f'Exec="{launcher}" %F')
desktop.write_text(content)
PY
chmod +x "$APPLICATIONS_DIR/downer.desktop"

# Update desktop database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true
fi

# Register as default markdown viewer
xdg-mime default downer.desktop text/markdown
xdg-mime default downer.desktop text/x-markdown
xdg-mime default downer.desktop application/x-markdown

echo ""
echo "Downer installed successfully!"
echo ""
echo "Usage:"
echo "  downer file.md              # open a file"
echo "  python3 -m downer file.md    # open through Python"
echo "  xdg-open file.md             # open with default app"
echo ""
echo "To uninstall, run:"
echo "  python3 -m pip uninstall downer"
echo "  rm \"$APPLICATIONS_DIR/downer.desktop\""
