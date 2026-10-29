"""Inspect this project's Windows servers; stop only after explicit confirmation.

No database access, installation, port-owner guessing, or image-wide taskkill.
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ManagementError(RuntimeError):
    pass


def split_command_line(command):
    if not command:
        return []
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    parse = shell.CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    arguments = parse(command, ctypes.byref(count))
    if not arguments:
        raise ManagementError("실행 명령을 해석하지 못했습니다. 종료하지 않습니다.")
    try:
        return [arguments[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(arguments, wintypes.HLOCAL))


def _path(value):
    return ntpath.normcase(ntpath.normpath(str(value)))


def _port(value):
    try:
        port = int(value)
        return port if 1024 <= port <= 65535 else None
    except (TypeError, ValueError):
        return None


def _script(value, filename, root):
    return value == filename or (
        ntpath.isabs(value) and _path(value) == _path(root / filename)
    )


def _python_paths(root):
    paths = {_path(root / '.venv' / 'Scripts' / 'python.exe')}
    # The root environment was deliberately not relocated with the Flask code.
    # Only this workspace's shared interpreter is allowed, never arbitrary Python.
    if root.name.upper() == 'FLASK':
        paths.add(_path(root.parent / '.venv' / 'Scripts' / 'python.exe'))
    return paths


def identify_process(process, root=ROOT):
    name = str(process.get("name", "")).lower()
    if name not in {"python.exe", "pythonw.exe", "cloudflared.exe"}:
        return None
    known_executables = _python_paths(root) | {
        _path(root / "tools" / "cloudflared.exe"),
    }
    if not process.get("command") and _path(process.get("exe", "")) in known_executables:
        raise ManagementError("프로젝트 프로세스의 명령을 확인하지 못했습니다. 종료하지 않습니다.")
    args = split_command_line(process.get("command", ""))
    if not args:
        return None
    if name == "cloudflared.exe":
        expected = root / "tools" / "cloudflared.exe"
        if (_path(args[0]) != _path(expected)
                or _path(process.get("exe", "")) != _path(expected)
                or len(args) < 4 or args[1] != "tunnel"
                or args.count("--url") != 1):
            return None
        index = args.index("--url")
        if index + 1 >= len(args):
            return None
        match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]+)", args[index + 1])
        port = _port(match.group(1)) if match else None
        options = args[2:]
        seen = set()
        while options:
            option = options[0]
            if option in seen:
                return None
            seen.add(option)
            if option == "--no-autoupdate":
                options = options[1:]
            elif option == "--protocol" and options[1:2] == ["http2"]:
                options = options[2:]
            elif option == "--url" and len(options) >= 2:
                options = options[2:]
            else:
                return None
        return ("tunnel", port) if port else None

    # Windows venv launchers spawn a base-Python executable with the original
    # argv[0]. Match the exact project venv in argv, not the base interpreter.
    if _path(args[0]) not in _python_paths(root):
        return None
    tail = args[1:]
    while tail:
        if tail[0] in {"-u", "-B"}:
            tail = tail[1:]
        elif tail[:2] == ["-X", "utf8"]:
            tail = tail[2:]
        elif tail[0] == "-Xutf8":
            tail = tail[1:]
        else:
            break
    if not tail:
        return None
    if _script(tail[0], "share.py", root):
        options = tail[1:]
        port = 5001 if not options else None
        if len(options) == 2 and options[0] == "--port":
            port = _port(options[1])
        elif len(options) == 1 and options[0].startswith("--port="):
            port = _port(options[0].split("=", 1)[1])
        return ("share", port) if port else None
    if _script(tail[0], "app.py", root) and len(tail) == 1:
        return ("app", 5000)
    if tail[:2] == ["-m", "waitress"] and tail[-1:] == ["app:app"]:
        if any(not (arg == "--no-expose-tracebacks"
                    or re.fullmatch(r"--threads=[1-9][0-9]*", arg)
                    or re.fullmatch(r"--listen=127\.0\.0\.1:[0-9]+", arg))
               for arg in tail[2:-1]):
            return None
        listeners = [re.fullmatch(r"--listen=127\.0\.0\.1:([0-9]+)", arg)
                     for arg in tail[2:-1] if arg.startswith("--listen=")]
        if len(listeners) == 1 and listeners[0]:
            port = _port(listeners[0].group(1))
            return ("waitress", port) if port else None
    return None


def _created(process):
    try:
        return int(process.get("created", ""))
    except (TypeError, ValueError):
        return None


def _children(parent, processes):
    parent_time = _created(parent)
    return [child for child in processes.values()
            if child.get("ppid") == parent["pid"]
            and child["pid"] != parent["pid"]
            and (parent_time is None or _created(child) is None
                 or _created(child) >= parent_time)]


def _tree(root_process, processes):
    tree = {root_process["pid"]}
    pending = [root_process]
    while pending:
        for child in _children(pending.pop(), processes):
            if child["pid"] not in tree:
                tree.add(child["pid"])
                pending.append(child)
    return tree


def _server_console(process, owned):
    """CREATE_NO_WINDOW may still have a private Windows console host child."""
    expected = ntpath.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "conhost.exe")
    return (str(process.get("name", "")).lower() == "conhost.exe"
            and _path(process.get("exe", "")) == _path(expected)
            and process.get("ppid") in owned and _created(process) is not None)


def analyze_snapshot(snapshot, root=ROOT):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("processes"), list) \
            or not isinstance(snapshot.get("listeners"), list):
        raise ManagementError("상태 조회 결과가 불완전합니다. 종료하지 않습니다.")
    try:
        processes = {int(p["pid"]): p for p in snapshot["processes"]}
    except (KeyError, TypeError, ValueError) as exc:
        raise ManagementError("프로세스 정보를 확인하지 못했습니다. 종료하지 않습니다.") from exc
    owned = {}
    for pid, process in processes.items():
        if pid == os.getpid():
            continue
        identity = identify_process(process, root)
        if identity:
            if _created(process) is None or not process.get("exe"):
                raise ManagementError("서버 생성 시각·실행 경로를 확인하지 못했습니다.")
            owned[pid] = identity
    roots = []
    for pid, (kind, port) in owned.items():
        process = processes[pid]
        # A matching immediate parent is enough to collapse venv wrappers.
        # Never cross an unrelated parent process or a reused parent PID.
        parent = processes.get(process.get("ppid"))
        if parent and parent["pid"] in owned and process in _children(parent, processes):
            continue
        tree_pids = _tree(process, processes)
        unsafe = sorted(child for child in tree_pids
                        if (child not in owned and not _server_console(processes[child], owned))
                        or _created(processes[child]) is None)
        listeners = sorted({int(item["port"]) for item in snapshot["listeners"]
                            if item.get("pid") in tree_pids})
        roots.append({
            "pid": pid, "created": process["created"],
            "command": process["command"], "exe": process["exe"],
            "kind": kind, "port": port, "tree_pids": sorted(tree_pids),
            "unsafe_children": unsafe, "listening_ports": listeners,
        })
    return sorted(roots, key=lambda item: item["pid"])


def read_snapshot():
    if os.name != "nt":
        raise ManagementError("이 관리 도구는 Windows용입니다.")
    script = r"""
        $ErrorActionPreference = 'Stop'
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        $processes = @(Get-CimInstance Win32_Process | Select-Object `
          @{n='pid';e={$_.ProcessId}}, @{n='ppid';e={$_.ParentProcessId}}, `
          @{n='name';e={$_.Name}}, @{n='exe';e={$_.ExecutablePath}}, `
          @{n='command';e={$_.CommandLine}}, `
          @{n='created';e={if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().Ticks.ToString()} else {''}}})
        $listeners = @(Get-NetTCPConnection -State Listen | Select-Object `
          @{n='pid';e={$_.OwningProcess}}, @{n='port';e={$_.LocalPort}}, `
          @{n='address';e={$_.LocalAddress}})
        [pscustomobject]@{processes=$processes;listeners=$listeners} | ConvertTo-Json -Depth 4 -Compress
    """
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=FLAGS, timeout=15, check=False,
        )
        if result.returncode:
            raise ManagementError("Windows 실행 상태 조회에 실패했습니다. 종료하지 않습니다.")
        return json.loads(result.stdout.lstrip("\ufeff"))
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ManagementError("Windows 실행 상태를 확인할 수 없습니다. 종료하지 않습니다.") from exc


def stop_target(target, snapshot_provider=read_snapshot, run=subprocess.run, root=ROOT):
    fresh = analyze_snapshot(snapshot_provider(), root)
    current = next((item for item in fresh if item["pid"] == target["pid"]), None)
    if current is None or any(current[key] != target[key]
                              for key in ("pid", "created", "command", "exe")):
        raise ManagementError("실행 정보가 바뀌었습니다. 상태를 다시 확인하세요. 종료하지 않았습니다.")
    if current["unsafe_children"]:
        raise ManagementError("관련 없는 자식 프로세스가 있어 안전하게 종료할 수 없습니다.")
    try:
        result = run(
            ["taskkill", "/PID", str(current["pid"]), "/T", "/F"],
            capture_output=True, creationflags=FLAGS, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagementError("종료 명령을 완료하지 못했습니다. 상태를 다시 확인하세요.") from exc
    if result.returncode:
        raise ManagementError("종료하지 못했습니다. 실행 권한과 현재 상태를 확인하세요.")


def show_status(targets):
    print("\n============================================================")
    print("  모블 컬리 서버 관리 — 이 프로젝트만 확인합니다")
    print("============================================================")
    if not targets:
        print("현재 이 프로젝트의 서버는 꺼져 있습니다.")
        print("켜려면 메인 폴더의 서버_켜기.cmd를 더블클릭하세요.")
        return
    labels = {"share": "외부 공유 서버", "app": "로컬 개발 서버",
              "waitress": "웹 서버", "tunnel": "외부 공유 터널"}
    for number, target in enumerate(targets, 1):
        port = target["port"]
        state = "열림" if port in target["listening_ports"] else "준비 중/웹 포트 미확인"
        print(f"[{number}] {labels[target['kind']]} 실행 중 · PID {target['pid']} · 포트 {port} ({state})")
        if target["unsafe_children"]:
            print("    관련 없는 자식 프로세스가 발견되어 종료를 차단합니다.")
    print("종료하면 해당 서버의 웹 접속과 외부 공유가 중단됩니다.")
    print("MySQL과 다른 프로젝트는 종료하지 않습니다.")


def main():
    parser = argparse.ArgumentParser(description="Moble Kurly Windows server manager")
    parser.add_argument("--status", action="store_true", help="Read status once without prompting")
    args = parser.parse_args()
    while True:
        try:
            targets = analyze_snapshot(read_snapshot())
            show_status(targets)
        except ManagementError as exc:
            print(f"\n확인 불가: {exc}")
            if args.status:
                return 1
            input("Enter를 누르면 닫습니다. ")
            return 1
        if args.status:
            return 0
        print("\n1. 상태 새로 확인    2. 서버 종료 선택    0. 창 닫기")
        choice = input("선택: ").strip()
        if choice == "0":
            return 0
        if choice != "2":
            continue
        if not targets:
            print("종료할 서버가 없습니다.")
            continue
        selected = input("종료할 서버 번호를 입력하세요 (Enter: 취소): ").strip()
        if not selected.isdecimal() or not 1 <= int(selected) <= len(targets):
            print("종료를 취소했습니다.")
            continue
        target = targets[int(selected) - 1]
        if input(f"PID {target['pid']} 서버를 종료할까요? 종료하려면 Y 입력: ").strip().upper() != "Y":
            print("종료를 취소했습니다.")
            continue
        try:
            stop_target(target)
            print("선택한 서버 종료 명령을 완료했습니다. 아래에서 상태를 다시 확인합니다.")
            time.sleep(0.5)
        except ManagementError as exc:
            print(f"종료 중단: {exc}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n관리 창을 닫습니다. 서버는 종료하지 않습니다.")
