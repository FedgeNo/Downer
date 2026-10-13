"""Downer - a desktop Markdown editor with an open-file sidebar and live preview.

A GTK3 application with a GtkSourceView editor pane and a WebKit2 HTML
preview pane. Integrates with XDG to become the default markdown viewer.
"""
import sys
import secrets
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkSource', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib, GtkSource, Pango

GSPELL_ERROR = None
try:
    gi.require_version('Gspell', '1')
    from gi.repository import Gspell
except (ValueError, ImportError, OSError) as error:
    Gspell = None
    GSPELL_ERROR = f'Spellchecking unavailable: install Gspell 1 and a spelling dictionary. {error}'

from downer.converter import convert_markdown
from downer.preview import PREVIEW_CSS


class DownerWindow(Gtk.Window):
    """Main window with a file list, one active editor buffer, and live preview."""

    def __init__(self, app=None, filepath=None, state_path=None):
        super().__init__()
        if app:
            self.set_application(app)
            app.add_window(self)
        initial_filepath = filepath
        self.filepath = None
        self._documents = {}
        self._selecting_file = False
        self._restore_editor_id = None
        self._restore_editor_attempts = 0
        self._preview_nonce = None
        self._preview_scroll = 0
        self._preview_fragment = ''
        self._preview_base_uri = None
        self._preview_load_pending = False
        self._refresh_id = None
        self._state_path = Path(GLib.get_user_state_dir()) / 'downer' / 'window.json'
        if state_path is not None:
            self._state_path = Path(state_path)
        self._window_state = {}
        if self._state_path.exists():
            try:
                self._window_state = json.loads(self._state_path.read_text(encoding='utf-8'))
                if not isinstance(self._window_state, dict):
                    raise ValueError('Window state must be an object')
            except (OSError, ValueError) as error:
                print(f'Unable to read window state: {error}', file=sys.stderr)
                self._window_state = {}
        self._normal_size = (1000, 700)
        self._normal_position = None
        self._restoring_split = True
        self.dark_mode = True
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', True)

        # --- Editor buffer ---
        self.buffer = GtkSource.Buffer()
        self.buffer.set_style_scheme(GtkSource.StyleSchemeManager.get_default().get_scheme('oblivion'))

        # Syntax highlighting for markdown
        lm = GtkSource.LanguageManager.get_default()
        lang = lm.get_language('markdown')
        if lang:
            self.buffer.set_language(lang)

        self.buffer.connect('changed', self._on_buffer_changed)
        self.buffer.connect('modified-changed', lambda buffer: self._update_file_label())

        # --- Editor view ---
        self.source_view = GtkSource.View()
        self.source_view.set_buffer(self.buffer)
        self.source_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.source_view.set_tab_width(4)
        self.source_view.set_show_line_numbers(True)
        self.source_view.set_vexpand(True)
        self.source_view.set_hexpand(True)
        self.spell_view = None
        self.spell_backend = None
        self.spellcheck_error = GSPELL_ERROR
        self._setup_spellchecking()

        # Start the browser only when there is content to preview.
        self.webview = None
        self.preview_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.preview_container.set_vexpand(True)
        self.preview_container.set_hexpand(True)

        # --- Build UI ---
        self._build_ui()
        self._add_document(None)
        self._select_document()
        if initial_filepath:
            self.open_document(initial_filepath)
        self.buffer.set_modified(False)
        self._update_title()
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
        if not initial_filepath:
            self._refresh_id = GLib.idle_add(self._refresh_preview)

    def _build_ui(self):
        self.set_title('Downer')
        width = self._window_state.get('width', 1000)
        height = self._window_state.get('height', 700)
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            self._normal_size = (width, height)
        self.set_default_size(*self._normal_size)
        position = self._window_state.get('position')
        if self._supports_position() and isinstance(position, list) and len(position) == 2 and all(isinstance(value, int) for value in position):
            self.move(*position)
        self.maximize()

        menu_bar = Gtk.MenuBar()
        accelerators = Gtk.AccelGroup()
        self.add_accel_group(accelerators)

        def add_menu(label):
            item = Gtk.MenuItem.new_with_mnemonic(label)
            menu = Gtk.Menu()
            item.set_submenu(menu)
            menu_bar.append(item)
            return menu

        def add_item(menu, label, callback, shortcut=None):
            item = Gtk.MenuItem.new_with_mnemonic(label)
            item.connect('activate', callback)
            menu.append(item)
            if shortcut:
                key, modifiers = Gtk.accelerator_parse(shortcut)
                item.add_accelerator('activate', accelerators, key, modifiers, Gtk.AccelFlags.VISIBLE)
            return item

        file_menu = add_menu('_File')
        add_item(file_menu, '_Open…', self._on_open, '<Control>o')
        add_item(file_menu, '_Save', self._on_save, '<Control>s')
        add_item(file_menu, 'Save _As…', lambda item: self._on_save(item, True), '<Control><Shift>s')
        file_menu.append(Gtk.SeparatorMenuItem())
        add_item(file_menu, '_Close File', lambda item: self._close_document(self.filepath), '<Control>w')
        add_item(file_menu, 'Close _Window', lambda item: self.close(), '<Control><Shift>w')

        edit_menu = add_menu('_Edit')
        add_item(edit_menu, '_Undo', lambda item: self.buffer.undo() if self.buffer.can_undo() else None, '<Control>z')
        add_item(edit_menu, '_Redo', lambda item: self.buffer.redo() if self.buffer.can_redo() else None, '<Control><Shift>z')
        edit_menu.append(Gtk.SeparatorMenuItem())
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        add_item(edit_menu, 'Cu_t', lambda item: self.buffer.cut_clipboard(clipboard, True), '<Control>x')
        add_item(edit_menu, '_Copy', lambda item: self.buffer.copy_clipboard(clipboard), '<Control>c')
        add_item(edit_menu, '_Paste', lambda item: self.buffer.paste_clipboard(clipboard, None, True), '<Control>v')
        add_item(edit_menu, 'Select _All', lambda item: self.buffer.select_range(self.buffer.get_start_iter(), self.buffer.get_end_iter()), '<Control>a')

        options_menu = add_menu('_Options')
        dark_item = Gtk.CheckMenuItem.new_with_label('Dark Mode')
        dark_item.set_active(self.dark_mode)
        dark_item.connect('toggled', self._on_dark_mode)
        options_menu.append(dark_item)
        wrap_item = Gtk.CheckMenuItem.new_with_label('Word Wrap')
        wrap_item.set_active(True)
        wrap_item.connect('toggled', lambda item: self.source_view.set_wrap_mode(Gtk.WrapMode.WORD if item.get_active() else Gtk.WrapMode.NONE))
        options_menu.append(wrap_item)
        spell_item = Gtk.CheckMenuItem.new_with_label('Spell Check')
        spell_item.set_active(self.spell_view is not None)
        if self.spell_view is not None:
            spell_item.connect('toggled', self._on_spell_check)
        else:
            spell_item.set_label('Spell Check (Unavailable)')
            spell_item.set_sensitive(False)
            spell_item.set_tooltip_text(self.spellcheck_error)
        options_menu.append(spell_item)
        preview_item = Gtk.CheckMenuItem.new_with_label('Show Preview')
        preview_item.set_active(True)
        options_menu.append(preview_item)
        add_item(options_menu, 'Editor Font…', self._on_font)

        # Paned with editor and preview
        paned = Gtk.Paned()
        self.paned = paned
        paned.set_orientation(Gtk.Orientation.HORIZONTAL)
        paned.set_position(500)
        paned.connect('size-allocate', self._restore_split)

        # Editor pane
        editor_scrolled = Gtk.ScrolledWindow()
        self.editor_scrolled = editor_scrolled
        editor_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        editor_scrolled.add(self.source_view)
        paned.pack1(editor_scrolled, True, True)

        # Preview pane
        preview_scrolled = Gtk.ScrolledWindow()
        preview_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_scrolled.add(self.preview_container)
        preview_item.connect('toggled', lambda item: preview_scrolled.set_visible(item.get_active()))
        paned.pack2(preview_scrolled, True, True)

        self.file_list = Gtk.ListBox()
        self.file_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.file_list.connect('row-selected', self._on_file_selected)
        file_scrolled = Gtk.ScrolledWindow()
        file_scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        file_scrolled.add(self.file_list)
        file_sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        file_sidebar.set_size_request(160, -1)
        file_sidebar.pack_start(Gtk.Label(label='Open Files', xalign=0), False, False, 8)
        file_sidebar.pack_start(file_scrolled, True, True, 0)
        workspace = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        workspace.set_position(200)
        workspace.pack1(file_sidebar, False, False)
        workspace.pack2(paned, True, False)

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.pack_start(menu_bar, False, False, 0)
        main_box.pack_start(workspace, True, True, 0)

        self.add(main_box)

        # Window close
        self.connect('delete-event', self._on_close)
        self.connect('destroy', self._on_destroy)
        self.connect('configure-event', self._on_configure)
        self._maximize_handler = self.connect('map', self._on_map)

        self.show_all()

    def _add_document(self, filepath):
        if filepath in self._documents:
            return
        row = Gtk.ListBoxRow()
        row.filepath = filepath
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        label = Gtk.Label(label=filepath.name if filepath else 'Untitled', xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(24)
        row.file_label = label
        row.set_tooltip_text(str(filepath) if filepath else 'Unsaved document')
        close = Gtk.Button.new_from_icon_name('window-close-symbolic', Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text('Close File')
        close.connect('clicked', lambda button: self._close_document(row.filepath))
        box.pack_start(label, True, True, 0)
        box.pack_end(close, False, False, 0)
        row.add(box)
        self._documents[filepath] = {'row': row, 'cursor': 0, 'editorScroll': 0, 'previewScroll': 0}
        self.file_list.add(row)
        row.show_all()

    def _select_document(self):
        self._selecting_file = True
        self.file_list.select_row(self._documents[self.filepath]['row'])
        self._selecting_file = False

    def _update_file_label(self):
        if self.filepath not in self._documents:
            return
        label = self.filepath.name if self.filepath else 'Untitled'
        if self.buffer.get_modified():
            label += ' *'
        self._documents[self.filepath]['row'].file_label.set_text(label)

    def _on_file_selected(self, file_list, row):
        if row is not None and not self._selecting_file:
            self.open_document(row.filepath)

    def _remember_document_position(self):
        if self.filepath in self._documents:
            self._documents[self.filepath]['cursor'] = self.buffer.get_iter_at_mark(self.buffer.get_insert()).get_offset()
            if self._restore_editor_id is None:
                self._documents[self.filepath]['editorScroll'] = self.editor_scrolled.get_vadjustment().get_value()
            self._documents[self.filepath]['previewScroll'] = self._preview_scroll

    def _remove_document(self, filepath):
        self._selecting_file = True
        self.file_list.remove(self._documents.pop(filepath)['row'])
        self._selecting_file = False

    def open_document(self, filepath, fragment=''):
        if filepath is not None:
            filepath = Path(filepath).resolve()
        if filepath == self.filepath:
            self._select_document()
            if fragment:
                self._preview_fragment = fragment
                self._refresh_preview()
            return True
        if not self._confirm_discard():
            self._select_document()
            return False
        try:
            text = filepath.read_text(encoding='utf-8') if filepath else ''
        except (OSError, UnicodeError) as error:
            self._show_error(f'Failed to open file: {error}')
            self._select_document()
            return False
        self._remember_document_position()
        self.buffer.set_modified(False)
        if self.filepath is None and not self.buffer.get_char_count():
            self._remove_document(None)
        self._add_document(filepath)
        self.filepath = filepath
        self._preview_nonce = None
        self._preview_scroll = self._documents[filepath]['previewScroll']
        self._preview_fragment = fragment
        # Clearing undo history releases the previous document's text.
        self.buffer.begin_not_undoable_action()
        self.buffer.set_text(text)
        self.buffer.end_not_undoable_action()
        self.buffer.set_modified(False)
        position = min(self._documents[filepath]['cursor'], self.buffer.get_char_count())
        self.buffer.place_cursor(self.buffer.get_iter_at_offset(position))
        self._select_document()
        self._update_title()
        if self._restore_editor_id:
            GLib.source_remove(self._restore_editor_id)
        self._restore_editor_attempts = 0
        self._restore_editor_id = GLib.timeout_add(50, self._restore_editor_position)
        self._refresh_preview()
        return True

    def _restore_editor_position(self):
        # TextView lays out long buffers lazily, so its scroll range may arrive later.
        self.source_view.get_line_yrange(self.buffer.get_end_iter())
        adjustment = self.editor_scrolled.get_vadjustment()
        position = self._documents[self.filepath]['editorScroll']
        self._restore_editor_attempts += 1
        if adjustment.get_upper() - adjustment.get_page_size() < position and self._restore_editor_attempts < 20:
            return GLib.SOURCE_CONTINUE
        self._restore_editor_id = None
        adjustment.set_value(position)
        return GLib.SOURCE_REMOVE

    def _close_document(self, filepath):
        if filepath == self.filepath:
            if not self._confirm_discard():
                return
            # Saving an untitled document may change its identity.
            filepath = self.filepath
            modified = self.buffer.get_modified()
            self.buffer.set_modified(False)
            remaining = [path for path in self._documents if path != filepath]
            if remaining and not self.open_document(remaining[0]):
                self.buffer.set_modified(modified)
                return
            if not remaining:
                self.buffer.begin_not_undoable_action()
                self.buffer.set_text('')
                self.buffer.end_not_undoable_action()
                self.buffer.set_modified(False)
                self.filepath = None
                self._preview_scroll = 0
                self._preview_nonce = None
                self._preview_fragment = ''
        self._remove_document(filepath)
        if not self._documents:
            self._add_document(None)
        self._select_document()
        self._update_title()
        self._refresh_preview()

    def _setup_spellchecking(self):
        if Gspell is not None:
            spell_view = None
            try:
                if Gspell.Language.get_default() is None:
                    self.spellcheck_error = 'Spellchecking unavailable: install a system spelling dictionary for your language.'
                else:
                    spell_view = Gspell.TextView.get_from_gtk_text_view(self.source_view)
                    spell_view.basic_setup()
                    self.spell_view = spell_view
                    self.spell_backend = 'Gspell'
                    self.spellcheck_error = None
            except (GLib.Error, RuntimeError, OSError) as error:
                if spell_view is not None:
                    spell_view.set_inline_spell_checking(False)
                self.spellcheck_error = f'Spellchecking unavailable: {error}'
        if self.spell_view is None:
            try:
                gi.require_version('GtkSpell', '3.0')
                from gi.repository import GtkSpell
                checker = GtkSpell.Checker()
                if not checker.set_language(None):
                    raise RuntimeError('No system spelling dictionary is available')
                if not checker.attach(self.source_view):
                    raise RuntimeError('GtkSpell could not attach to the editor')
                self.spell_view = checker
                self.spell_backend = 'GtkSpell'
                self.spellcheck_error = None
            except (ValueError, ImportError, OSError, GLib.Error, RuntimeError) as error:
                primary_error = self.spellcheck_error or 'Gspell is unavailable'
                self.spellcheck_error = f'{primary_error} GtkSpell fallback unavailable: {error}. Install Gspell 1 or GtkSpell 3 and a spelling dictionary.'
        if self.spellcheck_error:
            print(self.spellcheck_error, file=sys.stderr)

    def _on_spell_check(self, item):
        if self.spell_backend == 'Gspell':
            self.spell_view.set_inline_spell_checking(item.get_active())
        elif item.get_active():
            self.spell_view.attach(self.source_view)
        else:
            self.spell_view.detach()

    def _on_map(self, widget):
        self.disconnect(self._maximize_handler)
        self.maximize()

    def _supports_position(self):
        return 'X11' in self.get_display().__gtype__.name

    def _restore_split(self, paned, allocation):
        if self._restoring_split and allocation.width > 1:
            ratio = self._window_state.get('splitRatio', 0.5)
            if not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:
                ratio = 0.5
            paned.set_position(round(allocation.width * ratio))
            self._restoring_split = False

    def _on_configure(self, widget, event):
        if not self.is_maximized() and not self.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
            self._normal_size = self.get_size()
            if self._supports_position():
                self._normal_position = self.get_position()
        return False

    def _save_window_state(self):
        state = {
            'width': self._normal_size[0],
            'height': self._normal_size[1],
            'maximized': self.is_maximized(),
        }
        ratio = self._window_state.get('splitRatio', 0.5)
        if self.paned.get_child2().get_visible() and self.paned.get_allocated_width() > 1:
            ratio = self.paned.get_position() / self.paned.get_allocated_width()
        state['splitRatio'] = ratio
        if self._normal_position is not None:
            state['position'] = self._normal_position
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            Gio.File.new_for_path(str(self._state_path)).replace_contents(
                json.dumps(state).encode('utf-8'), None, False,
                Gio.FileCreateFlags.PRIVATE, None)
        except (OSError, GLib.Error) as error:
            print(f'Unable to save window state: {error}', file=sys.stderr)

    def _update_title(self):
        if self.filepath:
            self.set_title(f"Downer — {self.filepath.name}")
        else:
            self.set_title('Downer')

    def _on_font(self, item):
        dialog = Gtk.FontChooserDialog(title='Editor Font', transient_for=self)
        dialog.set_font_desc(self.source_view.get_style_context().get_font(Gtk.StateFlags.NORMAL))
        if dialog.run() == Gtk.ResponseType.OK:
            self.source_view.override_font(dialog.get_font_desc())
        dialog.destroy()

    def _on_dark_mode(self, item):
        self.dark_mode = item.get_active()
        Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', self.dark_mode)
        scheme = 'classic'
        if self.dark_mode:
            scheme = 'oblivion'
        self.buffer.set_style_scheme(GtkSource.StyleSchemeManager.get_default().get_scheme(scheme))
        self._refresh_preview()

    def _on_buffer_changed(self, buffer):
        # Debounce preview refresh
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
        self._refresh_id = GLib.timeout_add(150, self._refresh_preview)

    def _refresh_preview(self):
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
            self._refresh_id = None
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, True)
        if self.webview is None:
            if not text:
                return GLib.SOURCE_REMOVE
            gi.require_version('WebKit2', '4.1')
            from gi.repository import WebKit2
            self.webview = WebKit2.WebView()
            manager = self.webview.get_user_content_manager()
            manager.register_script_message_handler('downer')
            manager.connect('script-message-received::downer', self._on_preview_message)
            self.webview.connect('decide-policy', self._on_preview_policy)
            settings = self.webview.get_settings()
            settings.set_property('enable-developer-extras', True)
            settings.set_property('enable-javascript', True)
            settings.set_allow_file_access_from_file_urls(True)
            settings.set_property('enable-page-cache', False)
            self.webview.set_vexpand(True)
            self.webview.set_hexpand(True)
            self.preview_container.pack_start(self.webview, True, True, 0)
            self.webview.show()
        base_path = Path.cwd()
        if self.filepath:
            base_path = self.filepath.parent
        body_html = convert_markdown(text, base_path=base_path)
        nonce = secrets.token_hex(16)
        self._preview_nonce = nonce
        fragment = json.dumps(self._preview_fragment).replace('<', '\\u003c')
        self._preview_fragment = ''
        scroll = max(0, self._preview_scroll)
        assets_uri = (Path(__file__).parent / 'assets' / 'katex').resolve().as_uri()
        full_html = f"""<!DOCTYPE html>
<html lang="en" class="{'Dark' if self.dark_mode else 'Light'}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline' file:; img-src file: data:; font-src file: data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<link rel="stylesheet" href="{assets_uri}/katex.min.css">
<script nonce="{nonce}" src="{assets_uri}/katex.min.js"></script>
<script nonce="{nonce}" src="{assets_uri}/contrib/mhchem.min.js"></script>
<style>{PREVIEW_CSS}</style>
</head>
<body>
{body_html}
<script nonce="{nonce}">
document.querySelectorAll('.MathSpan, .MathDiv, span.math').forEach(function(element) {{
    katex.render(element.textContent, element, {{
        displayMode: element.classList.contains('MathDiv') || element.classList.contains('display'),
        throwOnError: false,
        trust: false,
        macros: window.mathMacros || (window.mathMacros = {{}})
    }});
}});
const fragment = {fragment};
function restore_position() {{
    const target = document.getElementById(fragment);
    if (target) {{
        target.scrollIntoView();
    }} else {{
        window.scrollTo(0, {scroll});
    }}
}}
window.addEventListener('load', restore_position);
document.fonts.ready.then(restore_position);
document.addEventListener('click', function(event) {{
    const link = event.target.closest('a[href]');
    if (link) {{
        event.preventDefault();
        window.webkit.messageHandlers.downer.postMessage(JSON.stringify({{nonce: '{nonce}', href: link.getAttribute('href')}}));
    }}
}});
window.addEventListener('scroll', function() {{
    window.webkit.messageHandlers.downer.postMessage(JSON.stringify({{nonce: '{nonce}', scroll: window.scrollY}}));
}});
</script>
</body>
</html>"""
        base_uri = Path.cwd().as_uri() + '/'
        if self.filepath:
            base_uri = self.filepath.parent.as_uri() + '/'
        base_uri += '?downer=' + nonce
        self._preview_base_uri = base_uri
        self._preview_load_pending = True
        self.webview.load_html(full_html, base_uri=base_uri)
        return GLib.SOURCE_REMOVE

    def _on_preview_message(self, manager, result):
        try:
            message = json.loads(result.get_js_value().to_string())
            if not isinstance(message, dict) or message.get('nonce') != self._preview_nonce:
                return
            if isinstance(message.get('href'), str):
                self._follow_link(message['href'])
            elif isinstance(message.get('scroll'), (int, float)):
                self._preview_scroll = max(0, message['scroll'])
        except (ValueError, TypeError) as error:
            print(f'Unable to process preview navigation: {error}', file=sys.stderr)

    def _on_preview_policy(self, webview, decision, decision_type):
        from gi.repository import WebKit2
        if decision_type in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            action = decision.get_navigation_action()
            if action.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED:
                decision.ignore()
                self._follow_link(action.get_request().get_uri())
                return True
            if (decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION
                    and self._preview_load_pending
                    and action.get_request().get_uri() == self._preview_base_uri):
                self._preview_load_pending = False
                return False
            decision.ignore()
            return True
        return False

    def _follow_link(self, uri):
        try:
            parts = urlsplit(uri)
            if parts.scheme in ('http', 'https', 'mailto'):
                Gio.AppInfo.launch_default_for_uri(uri, None)
                return True
            if parts.scheme not in ('', 'file') or parts.netloc not in ('', 'localhost'):
                raise ValueError('This link is not a local file or a supported web link')
            if not parts.path:
                self._preview_fragment = unquote(parts.fragment)
                if not parts.fragment:
                    self._preview_scroll = 0
                self._refresh_preview()
                return True
            filepath = Path(unquote(parts.path))
            if not filepath.is_absolute():
                base = Path.cwd()
                if self.filepath:
                    base = self.filepath.parent
                filepath = base / filepath
            filepath = filepath.resolve()
            if not filepath.is_file():
                raise FileNotFoundError(f'File not found: {filepath}')
            if filepath.suffix.lower() in ('.md', '.markdown', '.mdown', '.mkd', '.mkdn', '.txt'):
                return self.open_document(filepath, unquote(parts.fragment))
            Gio.AppInfo.launch_default_for_uri(filepath.as_uri(), None)
            return True
        except (OSError, ValueError, GLib.Error) as error:
            self._show_error(f'Unable to open link: {error}')
            return False

    def _on_open(self, button):
        dialog = Gtk.FileChooserNative(
            title='Open Markdown File',
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.set_select_multiple(True)
        filter_md = Gtk.FileFilter()
        filter_md.set_name('Markdown')
        filter_md.add_pattern('*.md')
        filter_md.add_pattern('*.markdown')
        dialog.add_filter(filter_md)

        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            filenames = dialog.get_filenames()
            if filenames and self.open_document(filenames[0]):
                for filename in filenames[1:]:
                    self._add_document(Path(filename).resolve())
        dialog.destroy()

    def _on_save(self, button, save_as=False):
        filepath = self.filepath
        if not self.filepath or save_as:
            dialog = Gtk.FileChooserNative(
                title='Save Markdown File',
                transient_for=self,
                action=Gtk.FileChooserAction.SAVE,
            )
            dialog.set_do_overwrite_confirmation(True)
            dialog.set_current_name('Untitled.md')
            response = dialog.run()
            if response == Gtk.ResponseType.ACCEPT:
                filepath = Path(dialog.get_filename()).resolve()
            else:
                dialog.destroy()
                return False
            dialog.destroy()

        try:
            text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
            filepath.write_text(text, encoding='utf-8')
            if filepath != self.filepath:
                self._remember_document_position()
                state = self._documents[self.filepath].copy()
                self._remove_document(self.filepath)
                if filepath in self._documents:
                    self._remove_document(filepath)
                self._add_document(filepath)
                for key in ('cursor', 'editorScroll', 'previewScroll'):
                    self._documents[filepath][key] = state[key]
            self.filepath = filepath
            self.buffer.set_modified(False)
            self._select_document()
            self._update_file_label()
            self._update_title()
            self._refresh_preview()
            return True
        except Exception as e:
            self._show_error(f"Failed to save file: {e}")
            return False

    def _confirm_discard(self):
        if not self.buffer.get_modified():
            return True
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            text='Save changes before continuing?')
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL,
            'Discard', Gtk.ResponseType.REJECT, 'Save', Gtk.ResponseType.ACCEPT)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT:
            return self._on_save(None)
        return response == Gtk.ResponseType.REJECT

    def _on_close(self, widget, event):
        return not self._confirm_discard()

    def _on_destroy(self, widget):
        self._save_window_state()
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
            self._refresh_id = None
        if self._restore_editor_id:
            GLib.source_remove(self._restore_editor_id)
            self._restore_editor_id = None

    def _show_error(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.connect('response', lambda d, r: d.destroy())
        dialog.present()


class DownerApplication(Gtk.Application):
    """GTK3 application wrapper."""

    def __init__(self):
        super().__init__(application_id='com.fedge.downer',
            flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.connect('activate', self._on_activate)
        self.connect('open', self._on_open)

    def _on_activate(self, app):
        win = self.get_active_window()
        if win is None and self.get_windows():
            win = self.get_windows()[0]
        if win is None:
            win = DownerWindow(app)
        win.present()

    def _on_open(self, app, files, count, hint):
        window = self.get_active_window()
        if window is None and self.get_windows():
            window = self.get_windows()[0]
        first = True
        for file in files:
            filepath = file.get_path()
            if filepath:
                if window is None:
                    window = DownerWindow(app, filepath)
                elif first:
                    if not window.open_document(filepath):
                        window.present()
                        return
                else:
                    window._add_document(Path(filepath).resolve())
                first = False
        if window is not None:
            window.present()


def main():
    """Entry point for the Downer application."""
    app = DownerApplication()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
