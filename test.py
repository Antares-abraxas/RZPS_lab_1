import unittest
from pathlib import Path

from app import ConfigError, build_conninfo, validate_credentials
from psycopg.conninfo import conninfo_to_dict

conf = {"host": "127.0.0.1", "port": 5432, "dbname": "appdb", "sslmode": "prefer"}


class InjectionTests(unittest.TestCase):
    def parsed(self, user, password):

        return conninfo_to_dict(build_conninfo(conf, user, password))

    def test_user_cannot_add_options(self):
        """Злоумышленник не может внедрить параметры через имя пользователя"""
        evil = "bob host=evil.example dbname=postgres"
        d = self.parsed(evil, "pw")
        self.assertEqual(d["user"], evil)
        self.assertEqual(d["host"], "127.0.0.1")
        self.assertEqual(d["dbname"], "appdb")

    def test_password_cannot_add_options(self):
        """Злоумышленник не может внедрить параметры через пароль"""
        evil = "x' host='evil.example' sslmode='disable"
        d = self.parsed("bob", evil)
        self.assertEqual(d["password"], evil)
        self.assertEqual(d["host"], "127.0.0.1")
        self.assertEqual(d["sslmode"], "prefer")

    def test_backslash_and_quotes(self):
        """Проверка корректной работы с обратными слэшами и кавычками"""
        d = self.parsed("a\\' b", "p\\\\'q")
        self.assertEqual(d["user"], "a\\' b")
        self.assertEqual(d["password"], "p\\\\'q")

    def test_nul_rejected(self):
        """Нулевые байты (\\x00) строго отклоняются"""
        with self.assertRaises(ValueError):
            validate_credentials("bob\x00", "pw")


if __name__ == "__main__":
    unittest.main()
