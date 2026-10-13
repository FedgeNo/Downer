# Downer

A desktop Markdown editor with a live preview for Linux. Write Markdown on the left and see the rendered document on the right, with local KaTeX math rendering, tables, and dark mode.

Built with Python, GTK 3, GtkSourceView, and WebKitGTK.

## Features

- Open Files sidebar alongside a resizable editor and live preview.
- Only the active document is loaded; inactive entries retain paths and session-only cursor/scroll positions.
- Local Markdown links open in the editor and update its preview, with relative paths and heading anchors supported.
- Markdown syntax highlighting, line numbers, and undo/redo.
- Local spellchecking with system dictionaries, spelling underlines, and right-click suggestions.
- CommonMark formatting and pipe tables with column alignment.
- Labeled footnotes with backlinks, task lists, strikethrough, automatic links, definition lists, subscript/superscript, and callouts.
- Local code syntax highlighting and explicit heading IDs.
- Optional Pandoc bibliography citations using local BibTeX/CSL files or references embedded in document metadata.
- Bundled KaTeX, stylesheets, and fonts: math rendering needs no CDN or internet connection.
- Chemistry notation through KaTeX's bundled mhchem extension.
- Dark mode, word wrap, editor font and size selection, and a toggle for the preview pane.
- File and Edit menus with standard keyboard shortcuts.
- UTF-8 file opening, saving, and Save As, with prompts for unsaved changes.
- Maximized startup and a saved panel split percentage.
- Desktop launcher and optional default Markdown file association.
- Deferred preview-engine startup for empty documents.

## Requirements

Downer requires a graphical Linux desktop and these system libraries:

- Python 3.10 or later with pip and PyGObject (`gi`).
- GTK 3.
- GtkSourceView 3.
- WebKitGTK with the `WebKit2` 4.1 introspection API.
- XDG utilities for desktop integration.

Spellchecking is optional: install Gspell 1 or GtkSpell 3 and a system spelling dictionary for your language to enable it. Downer prefers Gspell and automatically falls back to GtkSpell when Gspell cannot be used. If neither can be used, Downer still opens and edits documents; **Spell Check (Unavailable)** is disabled in the Options menu, with an explanatory tooltip. A diagnostic is also printed to the terminal.

Pandoc is optional for formal bibliography citations. Ordinary Markdown, footnotes, and reference links work without it. Documents that require a missing citation processor or bibliography file show a notice while retaining their readable content. Bibliography and CSL style files must be local; remote metadata resources are rejected.

The current application has been tested on Fedora 43 with Python 3.14 and Wayland. Python package dependencies are installed automatically by pip; the native GTK libraries must be installed separately.

### Desktop Compatibility

Downer uses GTK libraries, but does not require the GNOME desktop. It is intended to run on KDE Plasma, Xfce, Cinnamon, MATE, and other Linux desktops when the required libraries are installed. Desktop integration uses XDG file associations and a standard `.desktop` launcher without desktop-specific restrictions. The installer respects `XDG_DATA_HOME` for the launcher location.

GTK supports both Wayland and X11 backends. Window placement, decorations, themes, and native file chooser behavior depend on the desktop and display server. Testing on this machine does not constitute testing on every desktop environment.

## Installation

On Fedora, install the native dependencies:

```bash
sudo dnf install python3-pip python3-gobject gtk3 gtksourceview3 webkit2gtk4.1 xdg-utils desktop-file-utils
```

For optional English spellchecking:

```bash
sudo dnf install gspell hunspell-en
```

Alternatively, use `gtkspell3` in place of `gspell`; either integration is sufficient.

For optional formal bibliography citations:

```bash
sudo dnf install pandoc
```

Download or clone this repository, then run the following from its root directory.

### Application and Desktop Integration

```bash
bash downer/install.sh
```

The installer installs Downer for your user account, creates a desktop launcher, and **makes Downer the default application for Markdown files**. It does not require root privileges once the system dependencies are present.

### Application Only

To install without changing file associations:

```bash
python3 -m pip install --user .
```

Ensure your Python user scripts directory, usually `~/.local/bin`, is on your `PATH`. You can also launch the application with `python3 -m downer`.

If your distribution disallows pip installations into the system Python environment, use a virtual environment with `--system-site-packages` so it can access the native PyGObject installation:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install .
.venv/bin/downer
```

The supplied desktop installer targets the user pip installation; the virtual environment commands above install the application only.

## Usage

```bash
# Start a new document
downer

# Open an existing document
downer notes.md

# Open multiple documents in one window's file list
downer first.md second.md

# Launch through Python
python3 -m downer notes.md

# Use the default desktop handler after desktop integration
xdg-open notes.md
```

Downer runs as a single instance per desktop session. Opening files from your file manager or another command-line invocation adds them to the existing window and selects the first requested file. Starting `downer` without arguments brings the existing window forward. Use **File → Open** to add one or more documents to the window's file list. Select an entry to switch documents. **Save** writes to the current file; a new document opens a save dialog. **Save As** lets you choose another destination.

### Multiple Files and Local Links

The left sidebar lists open files. Only the active file's source is kept in the editor; the others are reloaded from disk when selected. Switching releases the previous document's undo history. If the current document has unsaved changes, Downer asks you to save, discard, or cancel before switching. There are no hidden drafts for inactive documents.

This prompt applies equally to sidebar selection, local Markdown links, **File → Open**, and files opened from outside the application. Canceling leaves the current document and its unsaved edits intact.

Cursor position and editor/preview scroll positions are remembered during the current session. The file list and these positions are not restored after restarting. Close an entry with its close button or **File → Close File**; closing the final file leaves an empty document.

Clicking a local Markdown or text link loads the target into the editor, then renders that source in the preview. An already-open file is selected without adding a duplicate entry. Relative links resolve against the active file's directory, including `../` paths and URL-encoded filenames. Links such as `[Details](notes.md#details)` also jump to the target heading. Missing files produce an error while keeping the current document open.

Web links open in your default browser. The embedded preview does not browse websites: remote images, stylesheets, scripts, frames, and automatic redirects are blocked. Local images, bundled KaTeX assets, and local fonts remain available.

### Keyboard Shortcuts

| Action | Shortcut |
| --- | --- |
| Open | Ctrl+O |
| Save | Ctrl+S |
| Save As | Ctrl+Shift+S |
| Close File | Ctrl+W |
| Close Window | Ctrl+Shift+W |
| Undo | Ctrl+Z |
| Redo | Ctrl+Shift+Z |
| Cut | Ctrl+X |
| Copy | Ctrl+C |
| Paste | Ctrl+V |
| Select All | Ctrl+A |

### Options

Use the **Options** menu to toggle **Dark Mode**, **Word Wrap**, **Spell Check**, and **Show Preview**, or choose **Editor Font…** to change the editor font and size. Hiding the preview gives the editor the full window width.

These options apply to the current session and are not saved between launches. Dark mode, word wrap, spellchecking, and the preview are enabled initially.

Spellchecking uses Gspell or its GtkSpell fallback with the system's installed dictionaries through Enchant. Right-click a misspelled word for suggested corrections; the context menu also provides spelling-language selection. Available engines depend on your Enchant installation and can include Hunspell, Aspell, and Nuspell. Install additional dictionaries through your distribution's package manager. No online spelling service is used.

### Math

Use `$…$` or `\(…\)` for inline math, and `$$…$$` or `\[…\]` for display math:

```markdown
The area is $A = \pi r^2$.

$$
\int_0^1 x^2\,dx = \frac{1}{3}
$$

\[
\begin{pmatrix}
a & b \\
c & d
\end{pmatrix}
\]

Chemistry: $\ce{2H2 + O2 -> 2H2O}$
```

Math is parsed before Markdown formatting, preserving TeX syntax such as underscores. Expressions inside Markdown code spans and fenced code blocks remain literal. Invalid expressions appear as errors in the preview rather than stopping document rendering.

The bundled renderer is KaTeX 0.19.0. See [KaTeX's supported functions](https://katex.org/docs/supported.html) for its TeX coverage; it is not a complete LaTeX document compiler.

The regular Markdown renderer accepts spaces inside dollar delimiters, such as `$ x^2 $`. Use `$$x^2$$ (eq-square)` to label a display equation and `[Equation](#eq-square)` to link to it. Fenced blocks marked `math` also render as equations.

### Tables

```markdown
| Name | Formula | Value |
| :--- | :---: | ---: |
| Circle | $\pi r^2$ | 3.14 |
| Square | $s^2$ | 4 |
```

Use colons in the separator row for left, center, or right alignment. Cells support inline Markdown formatting and math.

### Footnotes and Reference Links

```markdown
This claim has a labeled footnote.[^smith2024]

[^smith2024]: Smith, *A Study*, 2024. Notes can contain Markdown and math.

See [Smith 2024][smith] for the original paper.

[smith]: https://example.com/paper
```

Footnotes are numbered automatically and include links to the note and back to its reference. Reference links use your chosen visible label.

### Bibliography Citations

With Pandoc installed, use a YAML header to name a local bibliography, then cite its entry keys:

```markdown
---
bibliography: references.bib
---

This result follows from earlier work [@smith2024].
```

For example, `references.bib` beside the Markdown document could contain:

```bibtex
@article{smith2024,
  author = {Alex Smith},
  title = {A Study},
  journal = {Example Journal},
  year = {2024}
}
```

Bibliography paths resolve relative to the active document. You can also provide CSL JSON/YAML bibliography files, put a `references` list directly in the YAML header, or select a local citation style with `csl: style.csl`. Pandoc's citeproc formats the citations and reference list; citation links jump to the corresponding entry. Missing entry keys are reported in the preview.

Documents with formal bibliography citations use Pandoc's Markdown renderer, while other documents use markdown-it-py. Both feed math into the bundled KaTeX renderer. For citation documents, use conventional unspaced `$x^2$` or `\(x^2\)` math delimiters for Pandoc compatibility.

### Other Markdown Extensions

```markdown
~~Removed text~~

- [x] Completed item
- [ ] Pending item

Term
: Its definition.

H~2~O and x^2^

## A Heading {#my-heading}

[Jump to the heading](#my-heading)

> [!NOTE]
> A GitHub-style callout.
```

Bare URLs and email addresses become links. Task checkboxes are read-only in the preview; edit `[ ]` and `[x]` in the source. Fenced code blocks with a language name receive local syntax highlighting. YAML front matter is hidden from the ordinary preview. Inline image/link attributes and block attributes support IDs, classes, and titles; images can also specify width and height. Indented admonitions such as `!!! note "Title"` are supported by the regular renderer.

Markdown has many incompatible extensions. Diagram engines such as Mermaid and full LaTeX document compilation are not included.

### Window State

Downer opens maximized. Drag the divider to adjust the editor/preview proportions; the split percentage is saved when the window closes. Normal window dimensions are also recorded.

Window state is stored in `$XDG_STATE_HOME/downer/window.json`, normally `~/.local/state/downer/window.json`. Exact screen positioning depends on the desktop: coordinates can be requested under X11; Wayland controls placement itself.

## Development

From the repository root, run directly from the source tree:

```bash
python3 -m downer
```

The native dependencies and Python packages must already be installed. To reinstall an updated copy:

```bash
python3 -m pip install --user --upgrade .
```

KaTeX assets are included under `downer/assets/katex/` and packaged with the application. Users do not need Node.js or npm to install or run Downer.

Run the document and preview integration checks in a graphical session:

```bash
python3 -m unittest discover -s tests -v
```

The checks use disposable temporary documents. Preview checks exercise WebKit rendering, local link clicks, and blocked remote content.

## Uninstalling

For the user pip installation:

```bash
python3 -m pip uninstall downer
rm -- ~/.local/share/applications/downer.desktop
```

Remove the desktop file only if you installed desktop integration. Choose another default Markdown application in your desktop's settings afterward. Saved window state is retained, and Markdown documents are not removed.

## License

Downer is released under the [MIT License](LICENSE).

## Third-Party Software

Markdown parsing uses [markdown-it-py](https://github.com/executablebooks/markdown-it-py) and [mdit-py-plugins](https://github.com/executablebooks/mdit-py-plugins). Math rendering uses [KaTeX](https://katex.org/). Its MIT license is included at [downer/assets/katex/LICENSE](downer/assets/katex/LICENSE).
