"""Server-manager safety checks: fixtures and mocked taskkill only."""

import subprocess
import unittest
from unittest.mock import Mock, patch

from tools import server_control as control


ROOT = control.ROOT
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
TUNNEL = str(ROOT / "tools" / "cloudflared.exe")


def process(pid, args, *, ppid=0, created="100", exe=None, name="python.exe"):
    return {
        "pid": pid,
        "ppid": ppid,
        "name": name,
        "exe": exe or PYTHON,
        "command": subprocess.list2cmdline(args),
        "created": created,
    }


def running_snapshot():
    """Windows venv launcher, real Python, Waitress, and owned tunnel."""
    share_args = [PYTHON, "-X", "utf8", "-u", "share.py"]
    waitress_args = [
        PYTHON, "-m", "waitress", "--listen=127.0.0.1:5001",
        "--threads=4", "--no-expose-tracebacks", "app:app",
    ]
    rows = [
        process(100, share_args, created="100"),
        process(110, share_args, ppid=100, created="110",
                exe=r"C:\Python314\python.exe"),
        process(120, waitress_args, ppid=110, created="120"),
        process(130, waitress_args, ppid=120, created="130",
                exe=r"C:\Python314\python.exe"),
        process(140, [TUNNEL, "tunnel", "--no-autoupdate", "--protocol", "http2",
                      "--url", "http://127.0.0.1:5001"],
                ppid=110, created="140", exe=TUNNEL, name="cloudflared.exe"),
    ]
    return {
        "processes": rows,
        "listeners": [{"pid": 130, "port": 5001, "address": "127.0.0.1"}],
    }


class ServerControlTests(unittest.TestCase):
    def test_windows_argument_parser_preserves_spaced_paths(self):
        args = [PYTHON, "-X", "utf8", str(ROOT / "share.py")]
        self.assertEqual(control.split_command_line(subprocess.list2cmdline(args)), args)

    def test_identifies_only_supported_project_server_commands(self):
        cases = [
            ([PYTHON, "share.py"], "share", 5001),
            ([PYTHON, "-X", "utf8", "-u", str(ROOT / "share.py"), "--port", "5002"],
             "share", 5002),
            ([PYTHON, "app.py"], "app", 5000),
            ([PYTHON, "-m", "waitress", "--listen=127.0.0.1:5001", "app:app"],
             "waitress", 5001),
        ]
        for args, kind, port in cases:
            with self.subTest(args=args):
                self.assertEqual(control.identify_process(process(100, args), root=ROOT),
                                 (kind, port))
        tunnel = running_snapshot()["processes"][-1]
        self.assertEqual(control.identify_process(tunnel, root=ROOT), ("tunnel", 5001))

    def test_rejects_other_projects_and_lookalike_or_unsafe_arguments(self):
        cases = [
            [r"C:\OtherProject\.venv\Scripts\python.exe", "share.py"],
            [PYTHON, r"C:\OtherProject\share.py"],
            [PYTHON, "share.py.bak"],
            [PYTHON, "-c", "print('share.py')"],
            [PYTHON, "share.py", "--unknown"],
            [PYTHON, "-m", "waitress", "--listen=127.0.0.1:5001", "other:app"],
            [PYTHON, "-m", "waitress", "--listen=127.0.0.1:5001", "app:app", "--unknown"],
            [PYTHON, "share.py", "--port", "70000"],
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assertIsNone(control.identify_process(process(100, args), root=ROOT))
        for args in [
            [TUNNEL, "tunnel", "--url", "http://127.0.0.1:5001", "--unknown"],
            [TUNNEL, "tunnel", "--url", "http://192.168.0.90:5001"],
            [TUNNEL, "tunnel", "--url", "http://127.0.0.1:5001", "--url", "http://127.0.0.1:5002"],
        ]:
            with self.subTest(args=args):
                candidate = process(100, args, exe=TUNNEL, name="cloudflared.exe")
                self.assertIsNone(control.identify_process(candidate, root=ROOT))

    def test_base_python_child_is_owned_only_with_exact_venv_argv_zero(self):
        valid = process(100, [PYTHON, "share.py"], exe=r"C:\Python314\python.exe")
        self.assertEqual(control.identify_process(valid, root=ROOT), ("share", 5001))
        invalid = process(100, [r"C:\Python314\python.exe", "share.py"], exe=PYTHON)
        self.assertIsNone(control.identify_process(invalid, root=ROOT))

    def test_analysis_collapses_owned_nested_launcher_tree(self):
        targets = control.analyze_snapshot(running_snapshot(), root=ROOT)
        self.assertEqual([target["pid"] for target in targets], [100])
        self.assertEqual(set(targets[0]["tree_pids"]), {100, 110, 120, 130, 140})
        self.assertFalse(targets[0]["unsafe_children"])

    def test_unknown_descendant_blocks_tree_shutdown(self):
        snapshot = running_snapshot()
        snapshot["processes"].append(process(
            150, [r"C:\Windows\System32\notepad.exe"], ppid=110,
            created="150", exe=r"C:\Windows\System32\notepad.exe", name="notepad.exe"))
        targets = control.analyze_snapshot(snapshot, root=ROOT)
        self.assertTrue(targets[0]["unsafe_children"])
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        with self.assertRaises(control.ManagementError):
            control.stop_target(targets[0], snapshot_provider=Mock(return_value=snapshot),
                                run=run, root=ROOT)
        run.assert_not_called()

    def test_only_real_windows_console_direct_children_are_allowed(self):
        with patch.dict(control.os.environ, {"SystemRoot": r"C:\Windows"}):
            valid = running_snapshot()
            valid["processes"].append(process(
                150, [r"C:\Windows\System32\conhost.exe", "0xffffffff", "-ForceV1"],
                ppid=110, created="150", exe=r"C:\Windows\System32\conhost.exe",
                name="conhost.exe"))
            targets = control.analyze_snapshot(valid, root=ROOT)
            self.assertEqual([target["pid"] for target in targets], [100])
            self.assertIn(150, targets[0]["tree_pids"])
            self.assertFalse(targets[0]["unsafe_children"])

            for exe, parent_pid, created in [
                (r"C:\Other\conhost.exe", 110, "160"),
                (r"C:\Windows\System32\conhost.exe", 150, "160"),
                (r"C:\Windows\System32\conhost.exe", 110, ""),
            ]:
                with self.subTest(exe=exe, parent_pid=parent_pid, created=created):
                    snapshot = running_snapshot()
                    if parent_pid == 150:
                        snapshot["processes"].append(process(
                            150, [PYTHON, "unrelated.py"], ppid=110, created="150"))
                    snapshot["processes"].append(process(
                        160, [exe], ppid=parent_pid, created=created,
                        exe=exe, name="conhost.exe"))
                    targets = control.analyze_snapshot(snapshot, root=ROOT)
                    self.assertIn(160, targets[0]["unsafe_children"])

    def test_reused_parent_pid_is_not_treated_as_real_ancestor(self):
        snapshot = {
            "processes": [
                process(100, [PYTHON, "share.py"], created="300"),
                process(110, [PYTHON, "app.py"], ppid=100, created="200"),
            ],
            "listeners": [],
        }
        targets = control.analyze_snapshot(snapshot, root=ROOT)
        self.assertEqual({target["pid"] for target in targets}, {100, 110})

    def test_shutdown_rechecks_identity_and_targets_one_exact_tree(self):
        snapshot = running_snapshot()
        target = control.analyze_snapshot(snapshot, root=ROOT)[0]
        provider = Mock(return_value=snapshot)
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        control.stop_target(target, snapshot_provider=provider, run=run, root=ROOT)
        provider.assert_called()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "100", "/T", "/F"])

    def test_shutdown_refuses_changed_or_missing_process_identity(self):
        for field, value in [
            ("created", "999"), ("command", '"C:\\Other\\python.exe" share.py'),
            ("exe", r"C:\Other\python.exe"), ("created", ""),
        ]:
            with self.subTest(field=field, value=value):
                before = running_snapshot()
                target = control.analyze_snapshot(before, root=ROOT)[0]
                after = running_snapshot()
                after["processes"][0][field] = value
                run = Mock(return_value=subprocess.CompletedProcess([], 0))
                with self.assertRaises(control.ManagementError):
                    control.stop_target(target, snapshot_provider=Mock(return_value=after),
                                        run=run, root=ROOT)
                run.assert_not_called()
        before = running_snapshot()
        target = control.analyze_snapshot(before, root=ROOT)[0]
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        with self.assertRaises(control.ManagementError):
            control.stop_target(target, snapshot_provider=Mock(return_value={
                "processes": [], "listeners": []}), run=run, root=ROOT)
        run.assert_not_called()

    def test_shutdown_rechecks_new_unknown_descendants(self):
        target = control.analyze_snapshot(running_snapshot(), root=ROOT)[0]
        after = running_snapshot()
        after["processes"].append(process(
            150, [PYTHON, "unrelated.py"], ppid=100, created="150"))
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        with self.assertRaises(control.ManagementError):
            control.stop_target(target, snapshot_provider=Mock(return_value=after),
                                run=run, root=ROOT)
        run.assert_not_called()

    def test_snapshot_failure_never_calls_taskkill(self):
        target = control.analyze_snapshot(running_snapshot(), root=ROOT)[0]
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        with self.assertRaises((control.ManagementError, OSError)):
            control.stop_target(target, snapshot_provider=Mock(side_effect=OSError("denied")),
                                run=run, root=ROOT)
        run.assert_not_called()

    def test_taskkill_failure_is_reported(self):
        snapshot = running_snapshot()
        target = control.analyze_snapshot(snapshot, root=ROOT)[0]
        run = Mock(return_value=subprocess.CompletedProcess([], 1, "", "Access denied"))
        with self.assertRaises(control.ManagementError):
            control.stop_target(target, snapshot_provider=Mock(return_value=snapshot),
                                run=run, root=ROOT)

    def test_main_requires_explicit_confirmation_before_stopping(self):
        for answer, expected_calls in [("N", 0), ("Y", 1), ("", 0)]:
            with self.subTest(answer=answer):
                with patch("sys.argv", ["server_control.py"]), \
                        patch.object(control, "read_snapshot", return_value=running_snapshot()), \
                        patch.object(control, "stop_target") as stop, \
                        patch.object(control.time, "sleep"), \
                        patch("builtins.print"), \
                        patch("builtins.input", side_effect=["2", "1", answer, "0"]):
                    self.assertEqual(control.main(), 0)
                    self.assertEqual(stop.call_count, expected_calls)
                    if expected_calls:
                        self.assertEqual(stop.call_args.args[0]["pid"], 100)

    def test_management_cmd_is_utf8_without_bom_and_uses_windows_newlines(self):
        payload = (ROOT / "서버_관리.cmd").read_bytes()
        self.assertFalse(payload.startswith(b"\xef\xbb\xbf"))
        text = payload.decode("utf-8", errors="strict")
        self.assertIn("chcp 65001", text)
        self.assertIn('cd /d "%~dp0"', text)
        self.assertIn('"tools\\server_control.py"', text)
        self.assertIn("관리 도구", text)
        self.assertIn(b"\r\n", payload)
        remainder = payload.replace(b"\r\n", b"")
        self.assertNotIn(b"\n", remainder)
        self.assertNotIn(b"\r", remainder)


if __name__ == "__main__":
    unittest.main()
