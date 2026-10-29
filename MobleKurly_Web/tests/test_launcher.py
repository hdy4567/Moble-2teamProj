"""Check the double-click launcher without starting a server or using MySQL."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "서버_켜기.cmd"


class LauncherFileTests(unittest.TestCase):
    def test_launcher_is_utf8_without_bom_and_uses_only_crlf(self):
        contents = LAUNCHER.read_bytes()
        self.assertFalse(contents.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", contents)
        self.assertNotIn(b"\n", contents.replace(b"\r\n", b""))
        self.assertNotIn(b"\r", contents.replace(b"\r\n", b""))
        contents.decode("utf-8")

    def test_launcher_uses_its_own_directory_and_checks_dependencies(self):
        contents = LAUNCHER.read_bytes().decode("utf-8")
        self.assertIn('cd /d "%~dp0"', contents)
        self.assertIn("chcp 65001 >nul", contents)
        self.assertIn('set "MOBLE_PYTHON=.venv\\Scripts\\python.exe"', contents)
        self.assertIn('set "MOBLE_PYTHON=..\\.venv\\Scripts\\python.exe"', contents)
        self.assertIn('if not exist "%MOBLE_PYTHON%" goto python_missing', contents)
        self.assertIn('if not exist ".env" goto env_missing', contents)
        self.assertIn('if not exist "tools\\cloudflared.exe" goto tunnel_missing', contents)
        self.assertIn('if not exist "share.py" goto source_missing', contents)
        self.assertIn('"%MOBLE_PYTHON%" -X utf8 -u share.py', contents)
        self.assertIn("pause", contents)
        self.assertIn("exit /b %MOBLE_SERVER_EXIT%", contents)


@unittest.skipUnless(os.name == "nt", "The launcher requires Windows CMD.")
class WindowsLauncherDependencyTests(unittest.TestCase):
    def run_launcher_with_files(self, relative_paths):
        # All dependencies below are empty, inert fixtures. Each tested branch
        # must stop before Python, cloudflared, or application code can run.
        with tempfile.TemporaryDirectory(prefix="모블 컬리 실행 테스트 ") as temporary:
            root = Path(temporary)
            project = root / "한글 공백 프로젝트"
            unrelated_cwd = root / "다른 현재 폴더"
            project.mkdir()
            unrelated_cwd.mkdir()
            launcher = project / LAUNCHER.name
            shutil.copyfile(LAUNCHER, launcher)
            for relative in relative_paths:
                fixture = project / relative
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.touch()
            result = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher)],
                cwd=unrelated_cwd,
                input=b"\r\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        return result.returncode, result.stdout.decode("utf-8", errors="replace")

    def test_missing_virtualenv_stops_with_installation_instructions(self):
        exit_code, output = self.run_launcher_with_files([])
        self.assertEqual(exit_code, 1, output)
        self.assertIn(".venv\\Scripts\\python.exe 파일이 없습니다.", output)
        self.assertIn("README.md의 설치 절차", output)
        self.assertNotIn(".env 설정 파일이 없습니다.", output)

    def test_missing_env_stops_before_the_python_stub(self):
        exit_code, output = self.run_launcher_with_files([".venv/Scripts/python.exe"])
        self.assertEqual(exit_code, 1, output)
        self.assertIn(".env 설정 파일이 없습니다.", output)
        self.assertIn("SQL을 다시 실행하지 마세요.", output)
        self.assertNotIn("tools\\cloudflared.exe 파일이 없습니다.", output)

    def test_shared_workspace_python_is_found_before_env_check(self):
        exit_code, output = self.run_launcher_with_files(['../.venv/Scripts/python.exe'])
        self.assertEqual(exit_code, 1, output)
        self.assertIn('.env 설정 파일이 없습니다.', output)

    def test_missing_cloudflared_stops_before_the_python_stub(self):
        exit_code, output = self.run_launcher_with_files([".venv/Scripts/python.exe", ".env"])
        self.assertEqual(exit_code, 1, output)
        self.assertIn("tools\\cloudflared.exe 파일이 없습니다.", output)
        self.assertNotIn("share.py 파일이 없습니다.", output)


if __name__ == "__main__":
    unittest.main()
