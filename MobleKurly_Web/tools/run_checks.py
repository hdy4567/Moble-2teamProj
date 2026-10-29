"""Run all Python project checks with real MySQL connections disabled."""
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

WEB_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = WEB_ROOT.parent
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, str(WEB_ROOT))


def main():
    import mysql.connector
    from mysql.connector import pooling
    logging.disable(logging.CRITICAL)
    blocked = RuntimeError('Actual MySQL access is disabled during offline checks')
    with patch.object(mysql.connector, 'connect', side_effect=blocked), patch.object(pooling, 'MySQLConnectionPool', side_effect=blocked):
        suite = unittest.TestSuite()
        for folder in (WEB_ROOT / 'tests', WORKSPACE / 'DB/tests',
                       WORKSPACE / 'MFC/tests', WORKSPACE / 'HARDWARE/tests'):
            suite.addTests(unittest.TestLoader().discover(str(folder)))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
