import subprocess
import unittest
from unittest.mock import Mock, patch

import share


class ShareShutdownTests(unittest.TestCase):
    def test_live_shortcut_publish_reports_archive_without_touching_server(self):
        archive = share.ROOT / 'current-shortcut.zip'
        with patch.object(share, 'refresh_live_package', return_value=archive) as refresh:
            result = share.publish_live_shortcut('https://example.trycloudflare.com')
        self.assertEqual(result, archive)
        refresh.assert_called_once_with(
            'https://example.trycloudflare.com', share.LIVE_SHORTCUT,
        )

    def test_live_shortcut_publish_failure_does_not_stop_the_server(self):
        with patch.object(share, 'refresh_live_package', side_effect=OSError('disk unavailable')):
            self.assertIsNone(
                share.publish_live_shortcut('https://example.trycloudflare.com')
            )

    def test_missing_or_already_stopped_child_is_not_touched(self):
        with patch.object(share.subprocess, "run") as run:
            share.stop_child(None)
            child = Mock()
            child.poll.return_value = 0
            share.stop_child(child)
        run.assert_not_called()
        child.terminate.assert_not_called()

    def test_windows_stops_only_the_owned_child_process_tree(self):
        child = Mock(pid=43210)
        child.poll.return_value = None
        with patch.object(share.os, "name", "nt"):
            with patch.object(share.subprocess, "run") as run:
                share.stop_child(child)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "43210", "/T", "/F"])
        self.assertFalse(run.call_args.kwargs["check"])
        child.wait.assert_called_once_with(timeout=8)
        child.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
