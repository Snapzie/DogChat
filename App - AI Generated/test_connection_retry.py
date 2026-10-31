"""Exercise connection retries without credentials, live connections, or waits."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pyodbc


class ConnectionRetryTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "src" / "db.py"
        spec = importlib.util.spec_from_file_location("db_retry_under_test", path)
        self.db = importlib.util.module_from_spec(spec)
        with patch("dotenv.load_dotenv"), patch.object(pyodbc, "pooling", pyodbc.pooling):
            with patch.dict(os.environ, {"DATABASE_AGENT": "DRIVER={ODBC Driver 18 for SQL Server};SERVER=unused.invalid;"}, clear=True):
                spec.loader.exec_module(self.db)
        self.addCleanup(self.db.engine.dispose)
        self.connect = Mock()
        self.dialect = SimpleNamespace(loaded_dbapi=SimpleNamespace(connect=self.connect))
        self.sleep = patch.object(self.db.time, "sleep").start()
        self.addCleanup(patch.stopall)
        self.log = patch.object(self.db.logging, "getLogger").start().return_value

    def run_connection(self):
        return self.db.connect_with_retry(self.dialect, None, ["private-connection-string"], {"timeout": 60})

    def test_success_connects_once(self):
        connection = object()
        self.connect.return_value = connection
        self.assertIs(self.run_connection(), connection)
        self.connect.assert_called_once_with("private-connection-string", timeout=60)
        self.sleep.assert_not_called()

    def test_recovers_after_two_timeouts(self):
        connection = object()
        self.connect.side_effect = [pyodbc.OperationalError("HYT00", "private failure"), pyodbc.OperationalError("HYT01", "private failure"), connection]
        self.assertIs(self.run_connection(), connection)
        self.assertEqual(self.connect.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertNotIn("private", str(self.log.warning.call_args_list))

    def test_stops_after_three_failures(self):
        error = pyodbc.OperationalError("HYT00", "timeout")
        self.connect.side_effect = error
        with self.assertRaises(pyodbc.OperationalError) as caught:
            self.run_connection()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.connect.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_connection_network_errors_can_recover(self):
        for state in ("08001", "08S01"):
            with self.subTest(state=state):
                self.connect.reset_mock()
                self.connect.side_effect = [pyodbc.OperationalError(state, "network unavailable"), "connected"]
                self.assertEqual(self.run_connection(), "connected")
                self.assertEqual(self.connect.call_count, 2)

    def test_permanent_errors_are_not_retried(self):
        for error in (pyodbc.OperationalError("28000", "login rejected"), pyodbc.InterfaceError("IM002", "missing driver"), pyodbc.ProgrammingError("42000", "invalid configuration")):
            with self.subTest(error_type=type(error)):
                self.connect.reset_mock()
                self.connect.side_effect = error
                with self.assertRaises(type(error)):
                    self.run_connection()
                self.assertEqual(self.connect.call_count, 1)
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
