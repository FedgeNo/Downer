"""Check file forwarding between independent application processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


APPLICATION = '''
import json
from pathlib import Path
import sys
from downer.main import DownerApplication, DownerWindow

application_id, directory, *filenames = sys.argv[1:]
root = Path(directory)
original_init = DownerWindow.__init__
def init(self, *args, **kwargs):
    original_init(self, *args, state_path=root / 'window.json', **kwargs)
DownerWindow.__init__ = init

def report(app):
    window = app.get_windows()[0]
    data = {
        'windows': len(app.get_windows()),
        'active': str(window.filepath),
        'files': [str(row.filepath) for row in window.file_list.get_children()],
    }
    temporary = root / 'status.tmp'
    temporary.write_text(json.dumps(data))
    temporary.replace(root / 'status.json')

original_open = DownerApplication._on_open
def opened(self, *args):
    original_open(self, *args)
    report(self)
DownerApplication._on_open = opened
original_activate = DownerApplication._on_activate
def activated(self, *args):
    original_activate(self, *args)
    report(self)
DownerApplication._on_activate = activated

app = DownerApplication()
app.set_application_id(application_id)
sys.exit(app.run(['downer', *filenames]))
'''


@unittest.skipUnless((os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and os.environ.get('DBUS_SESSION_BUS_ADDRESS'), 'Needs a graphical desktop session with D-Bus')
class SingletonTests(unittest.TestCase):
    def test_new_launches_forward_files_to_one_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, third = [root / name for name in ('first.md', 'second.md', 'third.md')]
            for path in (first, second, third):
                path.write_text('')
            application_id = 'com.fedge.downer.Test' + uuid.uuid4().hex
            command = [sys.executable, '-c', APPLICATION, application_id, directory]
            primary = subprocess.Popen([*command, str(first)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 15
                while not (root / 'status.json').exists() and time.monotonic() < deadline:
                    if primary.poll() is not None:
                        self.fail(primary.stderr.read().decode())
                    time.sleep(0.02)
                self.assertTrue((root / 'status.json').exists(), 'Primary app did not open')
                subprocess.run([*command, str(second)], check=True, timeout=15, stdout=subprocess.DEVNULL)
                status = json.loads((root / 'status.json').read_text())
                self.assertEqual(status, {'windows': 1, 'active': str(second), 'files': [str(first), str(second)]})
                subprocess.run([*command, str(first), str(third)], check=True, timeout=15, stdout=subprocess.DEVNULL)
                status = json.loads((root / 'status.json').read_text())
                self.assertEqual(status, {'windows': 1, 'active': str(first), 'files': [str(first), str(second), str(third)]})
                subprocess.run(command, check=True, timeout=15, stdout=subprocess.DEVNULL)
                self.assertEqual(json.loads((root / 'status.json').read_text()), status)
                self.assertIsNone(primary.poll())
            finally:
                primary.terminate()
                try:
                    primary.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    primary.kill()
                    primary.wait()
                primary.stderr.close()


if __name__ == '__main__':
    unittest.main()
