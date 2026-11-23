"""Exercise host-side routing and transfer boundaries without a real VM/account."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ldl test ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo with spaces'
        self.repo.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'calls.jsonl'
        shutil.copy(ROOT / 'ldl-mac', self.repo / 'ldl-mac')
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        MOCK_LOG=str(self.log), MOCK_NAMES='', MOCK_OS='Darwin',
                        MOCK_ARCH='arm64', LDL_LIMA_INSTANCE='ldl-test',
                        TMPDIR=str(self.root))
        self.write_executable('uname', '#!/bin/sh\nif [ "$1" = -s ]; then echo "$MOCK_OS"; else echo "$MOCK_ARCH"; fi\n')
        self.write_executable('limactl', '#!' + sys.executable + '\n' + '''
import io, json, os, sys, tarfile
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['MOCK_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if os.environ.get('MOCK_FAIL') == args[0]:
    sys.exit(7)
if args[0] == 'list':
    print(os.environ['MOCK_NAMES'])
if args[-4:] == ['sudo', 'tar', '-xf', '-']:
    data = sys.stdin.buffer.read()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        Path(os.environ['MOCK_LOG'] + '.archive').write_text(json.dumps(archive.getnames()))
''')
        self.git('init', '-q', '--template=')
        for name, content in {'app/main.py': 'print("public")\n',
                              'web/index.html': 'public', '.env.example': 'UI_PORT=6080\n',
                              'compose.yaml': 'services: {}\n', 'ldl': '#!/bin/sh\n',
                              'apks/ledongli.apk': 'test-ldl', 'apks/wechat.apk': 'test-wx'}.items():
            p = self.repo / name
            p.parent.mkdir(exist_ok=True)
            p.write_text(content)
        import hashlib
        (self.repo / 'apks/SHA256SUMS').write_text(''.join(
            hashlib.sha256((self.repo / name).read_bytes()).hexdigest() + '  ' + name + '\n'
            for name in ['apks/ledongli.apk', 'apks/wechat.apk']))
        self.git('add', '.')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def write_executable(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def run_cli(self, *args):
        return subprocess.run(['/bin/sh', str(self.repo / 'ldl-mac'), *args],
                              env=self.env, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_help_needs_no_host_or_vm(self):
        self.env['MOCK_OS'] = 'Linux'
        self.assertEqual(self.run_cli('--help').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_unsupported_hosts_do_not_touch_lima(self):
        for key, value in [('MOCK_OS', 'Linux'), ('MOCK_ARCH', 'x86_64')]:
            with self.subTest(key=key):
                old = self.env[key]
                self.env[key] = value
                self.assertNotEqual(self.run_cli('init').returncode, 0)
                self.assertEqual(self.calls(), [])
                self.env[key] = old

    def test_invalid_instance_is_rejected(self):
        self.env['LDL_LIMA_INSTANCE'] = '../unsafe'
        self.assertNotEqual(self.run_cli('status').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_ldl_arguments_preserved(self):
        self.assertEqual(self.run_cli('run', '--now').returncode, 0)
        self.assertEqual(self.calls(), [['shell', '--workdir', '/opt/ldl', 'ldl-test',
                                        'sudo', './ldl', 'run', '--now']])

    def test_compose_arguments_preserved(self):
        self.assertEqual(self.run_cli('compose', 'logs', '--tail=5', 'controller').returncode, 0)
        self.assertEqual(self.calls()[0][-6:], ['sudo', 'docker', 'compose', 'logs', '--tail=5', 'controller'])

    def test_missing_start_does_not_create_default_vm(self):
        self.assertNotEqual(self.run_cli('start').returncode, 0)
        self.assertEqual([x[0] for x in self.calls()], ['list'])

    def test_failed_inventory_does_not_create_vm(self):
        self.env['MOCK_FAIL'] = 'list'
        self.assertNotEqual(self.run_cli('init').returncode, 0)
        self.assertEqual([x[0] for x in self.calls()], ['list'])

    def test_existing_init_does_not_modify_vm(self):
        self.env['MOCK_NAMES'] = 'other\nldl-test'
        self.assertNotEqual(self.run_cli('init').returncode, 0)
        self.assertEqual([x[0] for x in self.calls()], ['list'])

    def test_start_failure_does_not_start_containers(self):
        self.env.update(MOCK_NAMES='ldl-test', MOCK_FAIL='start')
        self.assertNotEqual(self.run_cli('start').returncode, 0)
        self.assertEqual([x[0] for x in self.calls()], ['list', 'start'])

    def test_bad_apks_stop_before_vm_creation(self):
        (self.repo / 'apks/wechat.apk').write_text('LFS pointer or damaged download')
        self.assertNotEqual(self.run_cli('init').returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_sync_excludes_private_and_untracked_files(self):
        for name in ['.env', 'app/account.json', 'app/private.py', 'web/screenshot.png', 'state/cookie.json']:
            p = self.repo / name
            p.parent.mkdir(exist_ok=True)
            p.write_text('DO NOT TRANSFER')
        result = self.run_cli('sync')
        self.assertEqual(result.returncode, 0, result.stderr)
        names = json.loads(Path(str(self.log) + '.archive').read_text())
        self.assertIn('app/main.py', names)
        self.assertIn('apks/ledongli.apk', names)
        self.assertIn('.env.example', names)
        self.assertNotIn('ldl-mac', names)
        self.assertFalse(any('private' in x or 'account' in x or 'cookie' in x or x == '.env' or x.startswith('.git') for x in names))
        self.assertEqual(list(self.root.glob('ldl-source.*')), [])

    def test_failed_archive_never_reaches_vm(self):
        self.write_executable('tar', '#!/bin/sh\nexit 9\n')
        self.assertNotEqual(self.run_cli('sync').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.root.glob('ldl-source.*')), [])

    def test_init_does_not_log_in_or_submit(self):
        result = self.run_cli('init')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual(calls[1][:4], ['start', '--yes', '--name', 'ldl-test'])
        self.assertTrue(any(c[-3:] == ['sudo', './ldl', 'doctor'] for c in calls))
        self.assertFalse(any('run' in c or 'setup' in c or 'schedule-on' in c for c in calls))


if __name__ == '__main__':
    unittest.main()
