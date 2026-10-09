import contextlib
import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import psycopg
from psycopg.conninfo import conninfo_to_dict

import pinger

DB = {
    "host": "db",
    "port": 5432,
    "dbname": "appdb",
    "sslmode": "prefer",
    "connect_timeout": 5,
    "statement_timeout": 5,
}
V18 = "PostgreSQL 18.0 (Debian 18.0-1.pgdg13+1) on x86_64-pc-linux-gnu, compiled by gcc, 64-bit"
SETTINGS = pinger.Settings(DB, "PostgreSQL 18", "u", "p", 10, None)


def env(**kw):
    base = {"PINGER_DB_USER": "u", "PINGER_DB_PASSWORD": "p"}
    base.update(kw)
    return base


class ConninfoTests(unittest.TestCase):
    def parsed(self, user, password):
        return conninfo_to_dict(pinger.build_conninfo(DB, user, password))

    def test_user_cannot_add_options(self):
        evil = "bob host=evil.example dbname=postgres"
        d = self.parsed(evil, "pw")
        self.assertEqual(d["user"], evil)
        self.assertEqual(d["host"], "db")
        self.assertEqual(d["dbname"], "appdb")

    def test_password_cannot_add_options(self):
        evil = "x' host='evil.example' sslmode='disable"
        d = self.parsed("bob", evil)
        self.assertEqual(d["password"], evil)
        self.assertEqual(d["host"], "db")
        self.assertEqual(d["sslmode"], "prefer")

    def test_statement_timeout_becomes_option(self):
        d = self.parsed("bob", "pw")
        self.assertEqual(d["options"], "-c statement_timeout=5000")
        self.assertNotIn("statement_timeout", d)

    def test_nul_rejected(self):
        with self.assertRaises(ValueError):
            pinger.build_conninfo(DB, "bob\x00", "pw")


class ConfigTests(unittest.TestCase):
    def test_user_in_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.toml"
            p.write_text(
                '[database]\nhost="h"\nport=5432\ndbname="d"\n'
                'connect_timeout=5\nstatement_timeout=5\nuser="root"\n',
                encoding="utf-8",
            )
            with self.assertRaises(pinger.ConfigError):
                pinger.load_config(p)

    def test_timeouts_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.toml"
            p.write_text(
                '[database]\nhost="h"\nport=5432\ndbname="d"\n', encoding="utf-8"
            )
            with self.assertRaises(pinger.ConfigError):
                pinger.load_config(p)

    def test_real_config_is_valid(self):
        db, prefix = pinger.load_config(pinger.DEFAULT_CONFIG)
        self.assertEqual(prefix, "PostgreSQL 18")
        self.assertIn("connect_timeout", db)


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        s = pinger.load_settings(env())
        self.assertEqual(s.interval, 300)
        self.assertIsNone(s.log_file)

    def test_interval_and_log_file_from_env(self):
        s = pinger.load_settings(
            env(PING_INTERVAL_SECONDS="10", PING_LOG_FILE="/tmp/x.log")
        )
        self.assertEqual(s.interval, 10)
        self.assertEqual(s.log_file, "/tmp/x.log")

    def test_bad_interval(self):
        for bad in ("abc", "0", "-5"):
            with self.subTest(bad=bad), self.assertRaises(pinger.ConfigError):
                pinger.load_settings(env(PING_INTERVAL_SECONDS=bad))

    def test_missing_credentials(self):
        with self.assertRaises(pinger.ConfigError):
            pinger.load_settings({"PINGER_DB_USER": "u"})
        with self.assertRaises(pinger.ConfigError):
            pinger.load_settings({})


class ClassifyTests(unittest.TestCase):
    def test_typical(self):
        self.assertTrue(pinger.classify([(V18,)], "PostgreSQL 18")[0])

    def test_other_version(self):
        self.assertFalse(
            pinger.classify([("PostgreSQL 17.2 on x86_64",)], "PostgreSQL 18")[0]
        )

    def test_weird_shapes(self):
        for rows in ([], [(None,)], [("a", "b")], [(V18,), (V18,)], [(42,)], [("",)]):
            with self.subTest(rows=rows):
                self.assertFalse(pinger.classify(rows, "PostgreSQL 18")[0])


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(contextlib.redirect_stdout(self.out))
        self.stack.enter_context(contextlib.redirect_stderr(self.err))

    def tearDown(self):
        self.stack.close()
        for h in list(pinger.log.handlers):
            h.close()
            pinger.log.removeHandler(h)

    def test_stream_routing(self):
        pinger.setup_logging(None)
        pinger.log.info("line-ok")
        pinger.log.warning("line-atypical")
        pinger.log.error("line-fail")
        self.assertIn("line-ok", self.out.getvalue())
        self.assertIn("line-atypical", self.out.getvalue())
        self.assertIn("line-fail", self.err.getvalue())
        self.assertNotIn("line-fail", self.out.getvalue())
        self.assertNotIn("line-ok", self.err.getvalue())

    def test_duplicate_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.log"
            pinger.setup_logging(str(path))
            pinger.log.info("to-file-ok")
            pinger.log.error("to-file-fail")
            for h in pinger.log.handlers:
                h.flush()
            text = path.read_text(encoding="utf-8")
            self.assertIn("to-file-ok", text)
            self.assertIn("to-file-fail", text)

    def test_bad_log_file_does_not_crash(self):
        pinger.setup_logging("/nonexistent-dir/x.log")
        self.assertIn("Не удалось открыть лог-файл", self.err.getvalue())


class CheckOnceTests(unittest.TestCase):
    def test_success_is_info(self):
        with mock.patch.object(pinger, "query_version", return_value=[(V18,)]):
            with self.assertLogs("pinger", level="INFO") as cm:
                self.assertTrue(pinger.check_once(SETTINGS))
        self.assertEqual(cm.records[0].levelno, logging.INFO)

    def test_atypical_is_warning_and_ok(self):
        with mock.patch.object(
            pinger, "query_version", return_value=[("something else",)]
        ):
            with self.assertLogs("pinger", level="INFO") as cm:
                self.assertTrue(pinger.check_once(SETTINGS))
        self.assertEqual(cm.records[0].levelno, logging.WARNING)

    def test_failure_is_error(self):
        with mock.patch.object(
            pinger, "query_version", side_effect=psycopg.OperationalError("boom")
        ):
            with self.assertLogs("pinger", level="INFO") as cm:
                self.assertFalse(pinger.check_once(SETTINGS))
        self.assertEqual(cm.records[0].levelno, logging.ERROR)

    def test_fail_then_recover(self):
        effects = [psycopg.OperationalError("down"), [(V18,)]]
        with mock.patch.object(pinger, "query_version", side_effect=effects):
            with self.assertLogs("pinger", level="INFO"):
                self.assertFalse(pinger.check_once(SETTINGS))
                self.assertTrue(pinger.check_once(SETTINGS))

    def test_unexpected_exception_is_contained(self):
        with mock.patch.object(
            pinger, "query_version", side_effect=RuntimeError("weird")
        ):
            with self.assertLogs("pinger", level="ERROR"):
                self.assertFalse(pinger.check_once(SETTINGS))


class DeadlineTests(unittest.TestCase):
    def test_hang_is_cut_off(self):
        import time

        with self.assertRaises(TimeoutError):
            pinger.run_with_deadline(lambda: time.sleep(3), 0.2)

    def test_result_returned(self):
        self.assertEqual(pinger.run_with_deadline(lambda: 42, 1), 42)


if __name__ == "__main__":
    unittest.main()
