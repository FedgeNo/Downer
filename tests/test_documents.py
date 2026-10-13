"""Document switching and preview integration checks; requires a graphical session."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import shutil
from unittest.mock import patch, Mock

from downer.main import DownerWindow, Gtk, Gio, GLib


def buffer_text(window):
    return window.buffer.get_text(window.buffer.get_start_iter(), window.buffer.get_end_iter(), True)


def wait_until(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Timed out waiting for the preview')


def evaluate(window, script):
    results = []
    def finished(view, task, data):
        results.append(view.evaluate_javascript_finish(task).to_string())
    window.webview.evaluate_javascript(script, -1, None, None, None, finished, None)
    wait_until(lambda: bool(results))
    return results[0]


@unittest.skipUnless(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'), 'Needs a graphical session')
class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.first = self.root / 'first.md'
        self.second = self.root / 'second.md'
        self.first.write_text('# First\nOriginal text', encoding='utf-8')
        self.second.write_text('# Second\nDifferent text', encoding='utf-8')
        self.window = DownerWindow(state_path=self.root / 'window.json')
        def no_preview():
            if self.window._refresh_id:
                GLib.source_remove(self.window._refresh_id)
                self.window._refresh_id = None
            return False
        self.window._refresh_preview = no_preview
        self.errors = []
        self.window._show_error = self.errors.append
        self.window.open_document(self.first)

    def tearDown(self):
        self.window.destroy()
        self.scratch.cleanup()

    def test_inactive_documents_reload_and_old_undo_is_released(self):
        self.window.buffer.place_cursor(self.window.buffer.get_iter_at_offset(4))
        self.window.open_document(self.second)
        self.first.write_text('# First changed externally', encoding='utf-8')
        self.window.open_document(self.first)
        self.assertEqual(buffer_text(self.window), '# First changed externally')
        self.assertEqual(self.window.buffer.get_iter_at_mark(self.window.buffer.get_insert()).get_offset(), 4)
        self.assertFalse(self.window.buffer.can_undo())
        self.assertEqual(len(self.window.file_list.get_children()), 2)
        self.window.open_document(self.second)
        self.assertEqual(len(self.window.file_list.get_children()), 2)

    def test_cancel_switch_keeps_source_and_selection(self):
        self.window.buffer.insert_at_cursor('Unsaved ')
        dialog = Mock()
        dialog.run.return_value = Gtk.ResponseType.CANCEL
        with patch.object(Gtk, 'MessageDialog', return_value=dialog):
            self.assertFalse(self.window.open_document(self.second))
        self.assertEqual(self.window.filepath, self.first)
        self.assertEqual(self.window.file_list.get_selected_row().filepath, self.first)
        self.assertIn('Unsaved', buffer_text(self.window))
        self.assertNotIn('Unsaved', self.first.read_text())

    def test_editor_scroll_restored_when_switching(self):
        long_file = self.root / 'long.md'
        long_file.write_text('A line of text.\n' * 300)
        self.window.open_document(long_file)
        adjustment = self.window.editor_scrolled.get_vadjustment()
        wait_until(lambda: self.window._restore_editor_id is None and adjustment.get_upper() > adjustment.get_page_size())
        adjustment.set_value(300)
        self.window.open_document(self.second)
        wait_until(lambda: self.window._restore_editor_id is None)
        self.window.open_document(long_file)
        wait_until(lambda: self.window._restore_editor_id is None)
        self.assertAlmostEqual(adjustment.get_value(), 300, delta=2)

    def test_file_list_and_document_positions_are_session_only(self):
        self.window.open_document(self.second)
        self.window.buffer.place_cursor(self.window.buffer.get_end_iter())
        self.window._save_window_state()
        reopened = DownerWindow(state_path=self.root / 'window.json')
        try:
            self.assertEqual(len(reopened.file_list.get_children()), 1)
            self.assertIsNone(reopened.filepath)
            self.assertEqual(reopened.buffer.get_iter_at_mark(reopened.buffer.get_insert()).get_offset(), 0)
        finally:
            reopened.destroy()

    def test_save_before_switch(self):
        self.window.buffer.insert_at_cursor('Saved ')
        dialog = Mock()
        dialog.run.return_value = Gtk.ResponseType.ACCEPT
        with patch.object(Gtk, 'MessageDialog', return_value=dialog):
            self.assertTrue(self.window.open_document(self.second))
        self.assertIn('Saved', self.first.read_text())
        self.assertEqual(buffer_text(self.window), self.second.read_text())

    def test_discard_before_switch(self):
        self.window.buffer.insert_at_cursor('Discarded ')
        dialog = Mock()
        dialog.run.return_value = Gtk.ResponseType.REJECT
        with patch.object(Gtk, 'MessageDialog', return_value=dialog):
            self.assertTrue(self.window.open_document(self.second))
        self.assertEqual(self.window.file_list.get_children()[0].file_label.get_text(), 'first.md')
        self.window.open_document(self.first)
        self.assertNotIn('Discarded', buffer_text(self.window))

    def test_failed_save_prevents_switch(self):
        self.window.buffer.insert_at_cursor('Unsaved ')
        dialog = Mock()
        dialog.run.return_value = Gtk.ResponseType.ACCEPT
        with patch.object(Gtk, 'MessageDialog', return_value=dialog), patch.object(Path, 'write_text', side_effect=OSError('Disk full')):
            self.assertFalse(self.window.open_document(self.second))
        self.assertEqual(self.window.filepath, self.first)
        self.assertTrue(self.window.buffer.get_modified())
        self.assertTrue(self.errors)

    def test_open_menu_prompts_and_cancel_keeps_current_document(self):
        self.window.buffer.insert_at_cursor('Unsaved ')
        chooser = Mock()
        chooser.run.return_value = Gtk.ResponseType.ACCEPT
        chooser.get_filenames.return_value = [str(self.second)]
        prompt = Mock()
        prompt.run.return_value = Gtk.ResponseType.CANCEL
        with patch.object(Gtk, 'FileChooserNative', return_value=chooser), patch.object(Gtk, 'MessageDialog', return_value=prompt):
            self.window._on_open(None)
        prompt.run.assert_called_once()
        self.assertEqual(self.window.filepath, self.first)
        self.assertTrue(self.window.buffer.get_modified())
        self.assertIn('Unsaved', buffer_text(self.window))
        self.assertEqual(len(self.window.file_list.get_children()), 1)

    def test_open_menu_adds_multiple_files_but_loads_only_first(self):
        third = self.root / 'third.md'
        third.write_text('# Third')
        chooser = Mock()
        chooser.run.return_value = Gtk.ResponseType.ACCEPT
        chooser.get_filenames.return_value = [str(self.second), str(third)]
        original_read = Path.read_text
        def read(path, *args, **kwargs):
            if path == third:
                raise AssertionError('Inactive file source should not be read')
            return original_read(path, *args, **kwargs)
        with patch.object(Gtk, 'FileChooserNative', return_value=chooser), patch.object(Path, 'read_text', read):
            self.window._on_open(None)
        self.assertEqual(self.window.filepath, self.second)
        self.assertEqual(len(self.window.file_list.get_children()), 3)
        self.assertEqual(buffer_text(self.window), self.second.read_text())

    def test_missing_link_keeps_document(self):
        self.assertFalse(self.window._follow_link('missing.md'))
        self.assertEqual(self.window.filepath, self.first)
        self.assertEqual(buffer_text(self.window), self.first.read_text())
        self.assertTrue(self.errors)

    def test_web_links_use_default_browser(self):
        with patch.object(Gio.AppInfo, 'launch_default_for_uri') as launch:
            self.assertTrue(self.window._follow_link('https://example.com/docs'))
            launch.assert_called_once_with('https://example.com/docs', None)
        self.assertEqual(self.window.filepath, self.first)

    def test_remote_file_host_is_rejected(self):
        self.assertFalse(self.window._follow_link('file://remote-host/document.md'))
        self.assertEqual(self.window.filepath, self.first)
        self.assertTrue(self.errors)

    def test_close_files_and_last_file(self):
        self.window.open_document(self.second)
        self.window._close_document(self.first)
        self.assertEqual(len(self.window.file_list.get_children()), 1)
        self.window._close_document(self.second)
        self.assertIsNone(self.window.filepath)
        self.assertEqual(buffer_text(self.window), '')
        self.assertFalse(self.window.buffer.can_undo())
        self.assertEqual(len(self.window.file_list.get_children()), 1)

    def test_close_failure_preserves_unsaved_state(self):
        self.window._add_document(self.second)
        self.second.unlink()
        self.window.buffer.insert_at_cursor('Unsaved ')
        dialog = Mock()
        dialog.run.return_value = Gtk.ResponseType.REJECT
        with patch.object(Gtk, 'MessageDialog', return_value=dialog):
            self.window._close_document(self.first)
        self.assertEqual(self.window.filepath, self.first)
        self.assertTrue(self.window.buffer.get_modified())
        self.assertIn('Unsaved', buffer_text(self.window))

    def test_save_as_updates_file_list_without_duplicates(self):
        self.window._add_document(self.second)
        dialog = Mock()
        dialog.run.return_value = Gtk.ResponseType.ACCEPT
        dialog.get_filename.return_value = str(self.second)
        with patch.object(Gtk, 'FileChooserNative', return_value=dialog):
            self.assertTrue(self.window._on_save(None, True))
        self.assertEqual(self.window.filepath, self.second)
        self.assertEqual(self.second.read_text(), self.first.read_text())
        self.assertEqual(len(self.window.file_list.get_children()), 1)
        self.assertEqual(self.window.file_list.get_selected_row().filepath, self.second)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'), 'Needs a graphical session')
class PreviewTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pandoc'), 'Pandoc is optional')
    def test_footnote_and_bibliography_links_stay_on_editor_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'citations.md'
            text = '''---
references:
- id: smith2024
  title: A Study
  author:
  - family: Smith
    given: Alex
  issued:
    date-parts: [[2024]]
---
# Results

A claim [@smith2024] with a footnote.[^note]

Math $x^2$.

''' + 'More text.\n\n' * 150 + '[^note]: A labeled footnote.\n'
            source.write_text(text, encoding='utf-8')
            window = DownerWindow(filepath=source, state_path=root / 'window.json')
            loaded = []
            window.webview.connect('load-changed', lambda view, event: loaded.append(True) if int(event) == 3 else None)
            try:
                wait_until(lambda: bool(loaded))
                data = json.loads(evaluate(window, 'JSON.stringify({math:document.querySelectorAll(".katex").length,citation:!!document.getElementById("ref-smith2024"),footnote:!!document.getElementById("fn1")})'))
                self.assertEqual(data, {'math': 1, 'citation': True, 'footnote': True})
                evaluate(window, 'document.querySelector("a[role=doc-noteref]").click(); "clicked"')
                wait_until(lambda: len(loaded) >= 2 and window._preview_scroll > 0)
                evaluate(window, 'document.querySelector("a[role=doc-backlink]").click(); "clicked"')
                wait_until(lambda: len(loaded) >= 3)
                evaluate(window, 'document.querySelector(".citation a").click(); "clicked"')
                wait_until(lambda: len(loaded) >= 4 and window._preview_scroll > 0)
                self.assertEqual(window.filepath, source)
                self.assertEqual(buffer_text(window), text)
                self.assertEqual(len(window.file_list.get_children()), 1)
            finally:
                window.destroy()

    def test_untrusted_markup_cannot_fetch_resources_or_redirect(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Untrusted remote content')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                address = f'http://127.0.0.1:{server.server_port}'
                source = root / 'untrusted.md'
                source.write_text(f'''# Safe Document

![Remote image]({address}/image.png)

<link rel="stylesheet" href="{address}/style.css">
<iframe src="{address}/frame"></iframe>
<script src="{address}/script.js"></script>
<script>window.untrustedScriptRan = true;</script>
<meta http-equiv="refresh" content="0;url={address}/redirect">
''', encoding='utf-8')
                window = DownerWindow(filepath=source, state_path=root / 'window.json')
                loaded = []
                window.webview.connect('load-changed', lambda view, event: loaded.append(True) if int(event) == 3 else None)
                try:
                    wait_until(lambda: bool(loaded))
                    data = json.loads(evaluate(window, 'JSON.stringify({heading:document.querySelector("h1").textContent,scriptRan:window.untrustedScriptRan===true,imageLoaded:document.querySelector("img").naturalWidth>0})'))
                    self.assertEqual(data, {'heading': 'Safe Document', 'scriptRan': False, 'imageLoaded': False})
                    self.assertEqual(requests, [])
                    self.assertEqual(window.filepath, source)
                    self.assertEqual(buffer_text(window), source.read_text())
                finally:
                    window.destroy()
        finally:
            server.shutdown()
            server.server_close()

    def test_clicked_local_link_switches_source_and_rendered_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sub').mkdir()
            first = root / 'first.md'
            second = root / 'sub' / 'second file.md'
            first.write_text('# First\n\n[Next](sub/second%20file.md#section-two)\n\n$\\frac{1}{2}$', encoding='utf-8')
            second.write_text('# Second\n\n' + 'Paragraph.\n\n' * 150 + '## Section Two\n\n| Math | Value |\n| --- | --- |\n| $x^2$ | 4 |\n\n[Back](../first.md)', encoding='utf-8')
            window = DownerWindow(filepath=first, state_path=root / 'window.json')
            loaded = []
            window.webview.connect('load-changed', lambda view, event: loaded.append(True) if int(event) == 3 else None)
            try:
                wait_until(lambda: bool(loaded))
                evaluate(window, 'document.querySelector("a").click(); "clicked"')
                wait_until(lambda: window.filepath == second and len(loaded) >= 2)
                self.assertEqual(buffer_text(window), second.read_text())
                data = json.loads(evaluate(window, 'JSON.stringify({heading:document.querySelector("h1").textContent,math:document.querySelectorAll(".katex").length,tables:document.querySelectorAll("table").length,anchor:!!document.getElementById("section-two")})'))
                self.assertEqual(data, {'heading': 'Second', 'math': 1, 'tables': 1, 'anchor': True})
                wait_until(lambda: window._preview_scroll > 0)
                saved_scroll = window._preview_scroll
                evaluate(window, 'document.querySelector("a").click(); "clicked"')
                wait_until(lambda: window.filepath == first and len(loaded) >= 3)
                self.assertEqual(evaluate(window, 'document.querySelector("h1").textContent'), 'First')
                self.assertEqual(len(window.file_list.get_children()), 2)
                window.open_document(second)
                wait_until(lambda: len(loaded) >= 4 and window._preview_scroll > 0)
                restored_scroll = float(evaluate(window, 'window.scrollY'))
                self.assertAlmostEqual(restored_scroll, saved_scroll, delta=2)
            finally:
                window.destroy()


if __name__ == '__main__':
    unittest.main()
