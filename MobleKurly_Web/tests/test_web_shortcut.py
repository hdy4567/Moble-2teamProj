"""Check portable Internet Shortcuts without opening a browser or the real desktop."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.web_shortcut import (
    LAUNCHER_NAME,
    SHORTCUT_NAME,
    build_launcher_exe,
    build_package,
    refresh_live_package,
    shortcut_contents,
)


class WebShortcutTests(unittest.TestCase):
    def test_plain_https_homepage_becomes_standard_crlf_shortcut(self):
        self.assertEqual(shortcut_contents('https://example.trycloudflare.com'),
                         '[InternetShortcut]\r\n'
                         'URL=https://example.trycloudflare.com/\r\n'
                         'IconFile=shop.ico\r\n'
                         'IconIndex=0\r\n')

    def test_untrusted_schemes_credentials_and_ini_injection_are_rejected(self):
        for address in [None, 'http://example.com/', 'file:///C:/test', 'javascript:alert(1)',
                        'https://localhost/', 'https://user:secret@example.com/',
                        'https://example.com/?token=secret', 'https://example.com/#data',
                        'https://example.com/\r\nIconFile=evil', 'https://example.com/path']:
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    shortcut_contents(address)

    def test_team_zip_contains_only_shortcut_icon_and_instructions(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / '한글 공백 바로가기'
            archive = build_package('https://example.trycloudflare.com/', destination)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(
                    set(bundle.namelist()),
                    {LAUNCHER_NAME, SHORTCUT_NAME, 'shop.ico', 'README.md'},
                )
                self.assertTrue(bundle.read(LAUNCHER_NAME).startswith(b'MZ'))
                self.assertEqual(bundle.read(SHORTCUT_NAME), shortcut_contents('https://example.trycloudflare.com/').encode('ascii'))
                self.assertTrue(bundle.read('shop.ico').startswith(b'\x00\x00\x01\x00'))
                self.assertIn(b'IconFile=shop.ico', bundle.read(SHORTCUT_NAME))
                guide = bundle.read('README.md').decode('utf-8')
                self.assertIn('실행 파일 하나만', guide)
                self.assertIn('전자 서명이 없습니다', guide)
                self.assertIn('고정 주소가 아닙니다', guide)
                self.assertIn('자동으로 알아내지는 않습니다', guide)
            with self.assertRaises(FileExistsError):
                build_package('https://another.trycloudflare.com/', destination)
            self.assertIn('example.trycloudflare.com', (destination / SHORTCUT_NAME).read_text())

    def test_invalid_url_does_not_create_partial_package(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'shortcut'
            with self.assertRaises(ValueError):
                build_package('file:///C:/invalid', destination)
            self.assertFalse(destination.exists())

    def test_live_package_refreshes_the_same_files_and_zip_to_the_new_address(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / '현재주소용'
            archive = refresh_live_package('https://first.trycloudflare.com/', destination)
            refresh_live_package('https://second.trycloudflare.com/', destination)
            expected = shortcut_contents('https://second.trycloudflare.com/').encode('ascii')
            self.assertEqual((destination / SHORTCUT_NAME).read_bytes(), expected)
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(
                    set(bundle.namelist()),
                    {LAUNCHER_NAME, SHORTCUT_NAME, 'shop.ico', 'README.md'},
                )
                self.assertEqual(bundle.read(SHORTCUT_NAME), expected)
                self.assertIn('second.trycloudflare.com', bundle.read('README.md').decode('utf-8'))
                self.assertNotIn('first.trycloudflare.com', bundle.read('README.md').decode('utf-8'))
                launcher = bundle.read(LAUNCHER_NAME)
                self.assertIn('second.trycloudflare.com'.encode('utf-16le'), launcher)
                self.assertNotIn('first.trycloudflare.com'.encode('utf-16le'), launcher)

    def test_invalid_refresh_preserves_the_last_good_live_package(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / '현재주소용'
            archive = refresh_live_package('https://safe.trycloudflare.com/', destination)
            shortcut_before = (destination / SHORTCUT_NAME).read_bytes()
            archive_before = archive.read_bytes()
            with self.assertRaises(ValueError):
                refresh_live_package('file:///C:/invalid', destination)
            self.assertEqual((destination / SHORTCUT_NAME).read_bytes(), shortcut_before)
            self.assertEqual(archive.read_bytes(), archive_before)

    def test_single_file_launcher_is_a_windows_executable_with_the_current_url(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / LAUNCHER_NAME
            build_launcher_exe('https://launcher.trycloudflare.com/', output)
            executable = output.read_bytes()
            self.assertTrue(executable.startswith(b'MZ'))
            self.assertIn('launcher.trycloudflare.com'.encode('utf-16le'), executable)


if __name__ == '__main__':
    unittest.main()
