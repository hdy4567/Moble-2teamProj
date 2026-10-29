"""Safety checks for the explicit produce update; all MySQL access is mocked.

Only temporary local backup fixtures are written. These tests never run the
updater against a live database and never start or stop a server.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from mysql.connector import Error

from tools import set_produce_catalog as updater


TEAM_CONFIG = {"host": "192.168.0.90", "port": 3306, "database": "moblekurly"}


def original_rows():
    return [{"product_id": product_id, "name": f"{color} 상품", "color": color,
             "price": Decimal("1000.00"), "stock": stock, "min_stock": 5}
            for product_id, color, stock in [(1, "RED", 50), (2, "BLUE", 20),
                                             (3, "YELLOW", 20), (4, "GREEN", 30)]]


def database_double(rows=None, before_update=None, fail_update=None, change_after_stock=False):
    """A stateful cursor double, not an SQL connection or SQL emulator."""
    rows = [dict(row) for row in (original_rows() if rows is None else rows)]
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = {"db": "moblekurly", "server_uuid": updater.EXPECTED_SERVER_UUID}
    cursor.fetchall.side_effect = lambda: [dict(row) for row in rows]
    cursor.rowcount = 1
    state = {"update_count": 0, "rows": rows}

    def execute(sql, params=()):
        compact = " ".join(sql.split())
        if compact.startswith("UPDATE "):
            state["update_count"] += 1
            if before_update:
                before_update(compact, params)
            if state["update_count"] == fail_update:
                raise Error("intentional mocked UPDATE failure")
            new_name, new_price, product_id, color, old_name, old_price = params
            row = next(row for row in rows if row["product_id"] == product_id)
            if (row["color"], row["name"], row["price"]) != (color, old_name, old_price):
                cursor.rowcount = 0
                return
            row.update(name=new_name, price=new_price)
        elif state["update_count"] and compact.startswith("SELECT product_id") and change_after_stock:
            rows[0]["stock"] += 1

    cursor.execute.side_effect = execute
    return connection, cursor, state


class ProduceUpdateSafetyTests(unittest.TestCase):
    def call_updater(self, connection, apply, directory):
        with patch.dict(updater.DB_CONFIG, TEAM_CONFIG):
            with patch.object(updater, "get_db", return_value=connection):
                return updater.apply_catalog(apply=apply, backup_directory=directory)

    def assert_no_updates(self, cursor):
        self.assertFalse(any(call.args[0].lstrip().startswith("UPDATE ")
                             for call in cursor.execute.call_args_list))

    def test_preview_never_updates_commits_starts_transaction_or_creates_backup(self):
        connection, cursor, _state = database_double()
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "snapshots"
            result = self.call_updater(connection, False, directory)
            self.assertFalse(directory.exists())
        self.assertFalse(result["applied"])
        self.assertEqual(result["before"], original_rows())
        self.assert_no_updates(cursor)
        connection.start_transaction.assert_not_called()
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    def test_apply_backs_up_before_first_update_and_commit_and_preserves_other_columns(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "snapshots"

            def assert_backup_exists(*_args):
                backups = list(directory.glob("*.json"))
                self.assertEqual(len(backups), 1)
                snapshot = json.loads(backups[0].read_text(encoding="utf-8"))
                self.assertEqual(snapshot["identity"], {
                    "db": "moblekurly", "server_uuid": updater.EXPECTED_SERVER_UUID,
                })
                self.assertEqual(snapshot["before"], [
                    {**row, "price": str(row["price"])} for row in original_rows()
                ])

            connection, cursor, state = database_double(before_update=assert_backup_exists)
            connection.commit.side_effect = assert_backup_exists
            result = self.call_updater(connection, True, directory)
            self.assertTrue(Path(result["backup"]).is_file())
        self.assertTrue(result["applied"])
        self.assertEqual(result["changed"], 4)
        self.assertEqual(state["update_count"], 4)
        updates = [call for call in cursor.execute.call_args_list
                   if call.args[0].lstrip().startswith("UPDATE ")]
        self.assertEqual(len(updates), 4)
        for before, after, call in zip(original_rows(), result["after"], updates):
            product_id = before["product_id"]
            self.assertEqual(" ".join(call.args[0].split()),
                             "UPDATE products SET name = %s, price = %s "
                             "WHERE product_id = %s AND color = %s AND name = %s AND price = %s")
            self.assertEqual(after, {**before, "name": updater.PLAN[product_id]["name"],
                                     "price": updater.PLAN[product_id]["price"]})
            for column in ["product_id", "color", "stock", "min_stock"]:
                self.assertEqual(before[column], after[column])
        self.assertTrue(any("FOR UPDATE" in call.args[0] for call in cursor.execute.call_args_list))
        connection.start_transaction.assert_called_once()
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()
        cursor.close.assert_called_once()
        connection.close.assert_called_once()

    def test_wrong_server_uuid_product_id_or_color_rolls_back_before_backup_or_update(self):
        for mismatch in ["uuid", "id", "color"]:
            with self.subTest(mismatch=mismatch), TemporaryDirectory() as temporary:
                rows = original_rows()
                if mismatch == "id":
                    rows[2]["product_id"] = 33
                elif mismatch == "color":
                    rows[1]["color"] = "blue"
                connection, cursor, _state = database_double(rows)
                if mismatch == "uuid":
                    cursor.fetchone.return_value = {"db": "moblekurly", "server_uuid": "wrong-server"}
                directory = Path(temporary) / "snapshots"
                with self.assertRaises(RuntimeError):
                    self.call_updater(connection, True, directory)
                self.assertFalse(directory.exists())
                self.assert_no_updates(cursor)
                connection.rollback.assert_called_once()
                connection.commit.assert_not_called()
                connection.close.assert_called_once()

    def test_second_update_failure_rolls_back_whole_transaction_and_keeps_before_backup(self):
        connection, _cursor, state = database_double(fail_update=2)
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "snapshots"
            with self.assertRaises(Error):
                self.call_updater(connection, True, directory)
            backups = list(directory.glob("*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual([row["price"] for row in json.loads(backups[0].read_text(encoding="utf-8"))["before"]],
                             ["1000.00"] * 4)
        self.assertEqual(state["update_count"], 2)
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_post_update_stock_change_fails_preservation_check_and_rolls_back(self):
        connection, _cursor, state = database_double(change_after_stock=True)
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "보존 검증"):
                self.call_updater(connection, True, Path(temporary) / "snapshots")
        self.assertEqual(state["update_count"], 4)
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()
        connection.close.assert_called_once()

    def test_unapproved_connection_is_rejected_before_any_database_access(self):
        for change in [{"host": "127.0.0.1"}, {"port": 3307}, {"database": "unapproved_catalog"}]:
            with self.subTest(change=change):
                with patch.dict(updater.DB_CONFIG, {**TEAM_CONFIG, **change}):
                    with patch.object(updater, "get_db") as get_db:
                        with self.assertRaises(RuntimeError):
                            updater.apply_catalog(apply=True)
                        get_db.assert_not_called()

    def test_zero_affected_rows_rolls_back_without_committing_remaining_updates(self):
        connection, cursor, _state = database_double()
        original_execute = cursor.execute.side_effect

        def zero_rowcount(sql, params=()):
            original_execute(sql, params)
            if sql.lstrip().startswith("UPDATE "):
                cursor.rowcount = 0

        cursor.execute.side_effect = zero_rowcount
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "변경 건수"):
                self.call_updater(connection, True, Path(temporary) / "snapshots")
        self.assertEqual(sum(call.args[0].lstrip().startswith("UPDATE ")
                             for call in cursor.execute.call_args_list), 1)
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
