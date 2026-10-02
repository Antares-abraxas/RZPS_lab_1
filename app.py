#!/usr/bin/env python3

import getpass
import sys
from pathlib import Path
from typing import Any

import psycopg
import tomllib
from psycopg.conninfo import make_conninfo

CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"

ALLOWED_KEYS: dict[str, type] = {
    "host": str,
    "port": int,
    "dbname": str,
    "sslmode": str,
    "connect_timeout": int,
    "application_name": str,
}
REQUIRED_KEYS = {"host", "port", "dbname"}
SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}

MAX_USER_BYTES = 63  # NAMEDATALEN-1 в PostgreSQL
MAX_PASSWORD_LEN = 1024
MAX_ATTEMPTS = 3


class ConfigError(Exception):
    """Ошибка в файле конфигурации."""


def load_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Файл конфигурации не найден: {path}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Некорректный TOML в {path}: {e}") from None

    section = data.get("database")
    if not isinstance(section, dict):
        raise ConfigError("В конфиге отсутствует секция [database]")

    unknown = set(section) - set(ALLOWED_KEYS)
    if unknown:
        raise ConfigError(
            f"Недопустимые ключи в [database]: {sorted(unknown)}. "
            f"Разрешены: {sorted(ALLOWED_KEYS)}. "
            "Логин и пароль задаются только вводом пользователя."
        )

    missing = REQUIRED_KEYS - set(section)
    if missing:
        raise ConfigError(f"Не хватает обязательных ключей: {sorted(missing)}")

    for key, expected in ALLOWED_KEYS.items():
        if key not in section:
            continue
        value = section[key]
        if type(value) is not expected:
            raise ConfigError(
                f"Ключ '{key}' должен иметь тип {expected.__name__}, "
                f"а не {type(value).__name__}"
            )
        if isinstance(value, str) and "\x00" in value:
            raise ConfigError(f"Ключ '{key}' содержит NUL-символ")

    if not 1 <= section["port"] <= 65535:
        raise ConfigError("port должен быть в диапазоне 1..65535")
    if "sslmode" in section and section["sslmode"] not in SSL_MODES:
        raise ConfigError(f"sslmode должен быть одним из {sorted(SSL_MODES)}")
    if "connect_timeout" in section and section["connect_timeout"] < 1:
        raise ConfigError("connect_timeout должен быть >= 1")

    return dict(section)


def validate_credentials(user: str, password: str) -> None:
    if not user:
        raise ValueError("Логин не может быть пустым")
    if "\x00" in user or "\x00" in password:
        raise ValueError("Ввод содержит недопустимый NUL-символ")
    if len(user.encode("utf-8")) > MAX_USER_BYTES:
        raise ValueError(f"Логин длиннее {MAX_USER_BYTES} байт")
    if not password:
        raise ValueError("Пароль не может быть пустым")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"Пароль длиннее {MAX_PASSWORD_LEN} символов")


def build_conninfo(config: dict[str, Any], user: str, password: str) -> str:
    validate_credentials(user, password)

    assert "user" not in config and "password" not in config

    params = {key: str(value) for key, value in config.items()}
    params["user"] = user
    params["password"] = password
    return make_conninfo("", **params)


def ask_credentials() -> tuple[str, str]:
    user = input("Логин: ")
    password = getpass.getpass("Пароль: ")
    return user, password


def fetch_version(conninfo: str) -> tuple[str, str, str]:
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION();")
            version = cur.fetchone()[0]

            cur.execute(
                "SELECT current_user, datcollate "
                "FROM pg_database WHERE datname = current_database();"
            )
            current_user, collate = cur.fetchone()
    return version, current_user, collate


def main() -> int:
    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 2

    print(f"Подключение к {config['host']}:{config['port']} / БД '{config['dbname']}'")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            user, password = ask_credentials()
            conninfo = build_conninfo(config, user, password)
        except ValueError as e:
            print(f"Некорректный ввод: {e}", file=sys.stderr)
            continue
        except (KeyboardInterrupt, EOFError):
            print("\nОтмена.")
            return 130

        try:
            version, current_user, collate = fetch_version(conninfo)
        except psycopg.OperationalError as e:
            print(
                f"Не удалось подключиться (попытка {attempt}/{MAX_ATTEMPTS}):\n"
                f"{str(e).strip()}",
                file=sys.stderr,
            )
            continue
        except psycopg.Error as e:
            print(f"Ошибка выполнения запроса: {e}", file=sys.stderr)
            return 1

        print("\nПодключение успешно.")
        print(f"Пользователь БД : {current_user}")
        print(f"Локаль БД       : {collate}")
        print(f"SELECT VERSION(): {version}")
        return 0

    print("Исчерпано число попыток.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
