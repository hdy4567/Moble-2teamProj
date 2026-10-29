"""Package a browser shortcut, without installing or executing anything on a PC."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SHORTCUT_NAME = '모블 컬리 웹 열기.url'
LAUNCHER_NAME = '모블 컬리 웹 열기.exe'
PACKAGE_FILES = (LAUNCHER_NAME, SHORTCUT_NAME, 'shop.ico', 'README.md')


def shortcut_contents(address):
    if not isinstance(address, str) or len(address) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in address):
        raise ValueError('Expected a plain public HTTPS homepage URL.')
    url = urlsplit(address)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.hostname == 'localhost' or '.' not in url.hostname
            or not re.fullmatch(r'[a-z0-9.-]+', url.hostname)
            or url.port not in (None, 443) or url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('Expected a public HTTPS homepage URL without extra parameters.')
    return ('[InternetShortcut]\r\n'
            'URL=' + address.rstrip('/') + '/\r\n'
            'IconFile=shop.ico\r\n'
            'IconIndex=0\r\n')


def readme_contents(address):
    return f'''# 모블 컬리 — 팀원 PC용 바로가기

## 사용법

1. ZIP 전체를 압축 해제하세요.
2. 파란 MK 아이콘의 **{LAUNCHER_NAME}** 파일을 더블클릭하면 기본 브라우저로 홈페이지가 열립니다.
3. 실행 파일 하나만 바탕화면으로 복사해도 아이콘과 실행 기능이 유지됩니다.

팀원 PC에는 Python·MySQL·Cloudflare 설치가 필요 없습니다. 별도 설치 도구나 스크립트 실행도 없습니다.

이 실행 파일은 팀 프로젝트용으로 직접 빌드되어 전자 서명이 없습니다. Windows가 처음 실행할 때 게시자를 확인할 수 없다는 안내를 표시할 수 있습니다. 조직 보안 정책상 실행할 수 없는 경우에는 같은 폴더의 **{SHORTCUT_NAME}**을 사용하세요. 보안 기능을 끄거나 우회하지 마세요.

## URL 바로가기(예비 방식)

`.url`은 별도 프로그램 없이 열리지만 Windows 탐색기가 상대경로 ICO를 찾지 못하면 기본 브라우저 아이콘으로 보일 수 있습니다. 실행에는 문제가 없습니다. `.url`을 사용할 때는 동봉한 **shop.ico**와 같은 폴더에 보관하세요.

## 현재 주소

{address.rstrip('/')}/

**이 파일은 현재 실행 중인 Cloudflare 임시 주소용입니다. 고정 주소가 아닙니다.** 서버 PC·Cloudflare 터널·팀 DB가 실행 중이어야 접속됩니다. 바로가기를 누른다고 서버가 켜지지는 않습니다.

Cloudflare 터널을 종료했다가 다시 생성하면 주소가 바뀌므로 새 바로가기를 다시 받아야 합니다. 배포된 파일이 새 주소를 자동으로 알아내지는 않습니다. 도메인을 연결한 고정 터널을 도입하면 이 문제를 없앨 수 있습니다.

이 ZIP에는 바로가기, 아이콘, 이 설명서만 들어 있습니다. DB 비밀번호·.env·주문·개인정보·서버 소스는 포함하지 않습니다.
'''


def _compiler_path():
    windows = Path(os.environ.get('WINDIR', r'C:\Windows'))
    candidates = (
        windows / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe',
        windows / 'Microsoft.NET' / 'Framework' / 'v4.0.30319' / 'csc.exe',
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def build_launcher_exe(address, destination):
    """Build a one-file Windows launcher with the approved MK icon embedded."""
    shortcut_contents(address)  # Reuse the strict public-HTTPS validation.
    compiler = _compiler_path()
    if compiler is None:
        raise FileNotFoundError('The Windows .NET Framework C# compiler is missing.')
    icon = ROOT / 'static/images/moble-kurly-shortcut-v7.ico'
    if not icon.is_file():
        raise FileNotFoundError('The approved MK shortcut icon is missing.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = f'''using System;
using System.Diagnostics;
using System.Windows.Forms;

internal static class MobleKurlyLauncher
{{
    [STAThread]
    private static void Main()
    {{
        const string url = "{address.rstrip('/')}/";
        try
        {{
            Process.Start(new ProcessStartInfo(url) {{ UseShellExecute = true }});
        }}
        catch (Exception error)
        {{
            MessageBox.Show(
                "모블 컬리 홈페이지를 열 수 없습니다.\\n\\n" + error.Message,
                "모블 컬리",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }}
    }}
}}
'''
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with tempfile.TemporaryDirectory(prefix='moble-kurly-launcher-') as folder:
        folder = Path(folder)
        source_path = folder / 'Launcher.cs'
        output_path = folder / LAUNCHER_NAME
        source_path.write_text(source, encoding='utf-8-sig')
        result = subprocess.run(
            [str(compiler), '/nologo', '/target:winexe', '/optimize+',
             '/platform:anycpu', f'/win32icon:{icon}',
             '/reference:System.Windows.Forms.dll', f'/out:{output_path}',
             str(source_path)],
            cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=flags, timeout=30, check=False,
        )
        if result.returncode or not output_path.is_file():
            details = result.stdout.decode(errors='replace').strip()
            raise OSError(f'Could not build the web launcher. {details}')
        built = output_path.read_bytes()
        if not built.startswith(b'MZ'):
            raise OSError('The generated web launcher is not a valid Windows executable.')
        temporary = destination.with_name(destination.name + '.tmp')
        temporary.write_bytes(built)
        temporary.replace(destination)
    return destination


def _write_package(address, destination, *, replace):
    contents = shortcut_contents(address)
    destination = Path(destination)
    archive = destination.with_suffix('.zip')
    if not replace and (destination.exists() or archive.exists()):
        raise FileExistsError('Existing shortcut packages are never overwritten.')
    icon = ROOT / 'static/images/moble-kurly-shortcut-v7.ico'
    if not icon.is_file():
        raise FileNotFoundError('The approved MK shortcut icon is missing.')
    destination.mkdir(parents=True, exist_ok=replace)
    build_launcher_exe(address, destination / LAUNCHER_NAME)
    (destination / SHORTCUT_NAME).write_bytes(contents.encode('ascii'))
    shutil.copyfile(icon, destination / 'shop.ico')
    (destination / 'README.md').write_text(readme_contents(address), encoding='utf-8')

    temporary_archive = archive.with_name(archive.name + '.tmp') if replace else archive
    if replace and temporary_archive.exists():
        temporary_archive.unlink()
    mode = 'w' if replace else 'x'
    try:
        with zipfile.ZipFile(temporary_archive, mode, zipfile.ZIP_DEFLATED) as bundle:
            for name in PACKAGE_FILES:
                bundle.write(destination / name, arcname=name)
        if replace:
            temporary_archive.replace(archive)
    finally:
        if replace and temporary_archive.exists():
            temporary_archive.unlink()
    return archive


def build_package(address, destination):
    """Create a new one-time package and refuse to overwrite prior output."""
    return _write_package(address, destination, replace=False)


def refresh_live_package(address, destination):
    """Atomically refresh the stable 'current URL' package after tunnel startup."""
    return _write_package(address, destination, replace=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(build_package(args.url, args.output))
