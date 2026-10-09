#!/usr/bin/env python3

import logging
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import psycopg
import tomllib
from psycopg.conninfo import make_conninfo

log = logging.getLogger("pinger")

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"
DEFAULT_INTERVAL = 300

ALLOWED_KEYS: dict[str, type] = {
    "host": str,
    "port": int,
    "dbname": str,
    "sslmode": str,
    "connect_timeout": int,
    "statement_timeout": int,
    "application_name": str,
}
REQUIRED_KEYS = {"host", "port", "dbname", "connect_timeout", "statement_timeout"}
SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
ALLOWED_CHECK_KEYS = {"expected_version_prefix"}

MAX_USER_BYTES = 63
MAX_PASSWORD_LEN = 1024


class ConfigError(Exception):
    """Ошибка конфигурации (файл или переменные окружения)."""


@dataclass(frozen=True)
class Settings:
    db: dict[str, Any]
    expected_prefix: str
    user: str
    password: str
    interval: int
    log_file: str | None

    @property
    def deadline(self) -> int:
        return self.db["connect_timeout"] + self.db["statement_timeout"] + 5


def load_config(path: Path) -> tuple[dict[str, Any], str]:
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
            "Логин и пароль задаются только переменными окружения."
        )
    missing = REQUIRED_KEYS - set(section)
    if missing:
        raise ConfigError(f"Не хватает обязательных ключей: {sorted(missing)}")

    for key, expected in ALLOWED_KEYS.items():
        if key not in section:
            continue
        value = section[key]
        if type(value) is not expected:  # bool - подкласс int, поэтому не isinstance
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
    for key in ("connect_timeout", "statement_timeout"):
        if section[key] < 1:
            raise ConfigError(f"{key} должен быть >= 1")

    check = data.get("check", {})
    if not isinstance(check, dict):
        raise ConfigError("[check] должна быть таблицей")
    unknown = set(check) - ALLOWED_CHECK_KEYS
    if unknown:
        raise ConfigError(f"Недопустимые ключи в [check]: {sorted(unknown)}")
    prefix = check.get("expected_version_prefix", "PostgreSQL 18")
    if not isinstance(prefix, str) or not prefix or "\x00" in prefix:
        raise ConfigError("expected_version_prefix должен быть непустой строкой")

    return dict(section), prefix


def validate_credentials(user: str, password: str) -> None:
    if not user:
        raise ValueError("Логин не может быть пустым")
    if not password:
        raise ValueError("Пароль не может быть пустым")
    if "\x00" in user or "\x00" in password:
        raise ValueError("Логин/пароль содержат недопустимый NUL-символ")
    if len(user.encode("utf-8")) > MAX_USER_BYTES:
        raise ValueError(f"Логин длиннее {MAX_USER_BYTES} байт")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"Пароль длиннее {MAX_PASSWORD_LEN} символов")


def read_interval(env: Mapping[str, str]) -> int:
    raw = (env.get("PING_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_INTERVAL
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(
            f"PING_INTERVAL_SECONDS должна быть целым числом, получено: {raw!r}"
        ) from None
    if value < 1:
        raise ConfigError("PING_INTERVAL_SECONDS должна быть >= 1")
    return value


def load_settings(env: Mapping[str, str], config_path: Path | None = None) -> Settings:
    path = Path(config_path or env.get("PINGER_CONFIG") or DEFAULT_CONFIG)
    db, prefix = load_config(path)
    prefix = env.get("EXPECTED_VERSION_PREFIX") or prefix

    user = env.get("PINGER_DB_USER")
    password = env.get("PINGER_DB_PASSWORD")
    if not user or not password:
        raise ConfigError(
            "Не заданы переменные окружения PINGER_DB_USER и/или PINGER_DB_PASSWORD"
        )
    try:
        validate_credentials(user, password)
    except ValueError as e:
        raise ConfigError(str(e)) from None

    log_file = (env.get("PING_LOG_FILE") or "").strip() or None
    return Settings(db, prefix, user, password, read_interval(env), log_file)


def build_conninfo(db: Mapping[str, Any], user: str, password: str) -> str:
    validate_credentials(user, password)
    assert "user" not in db and "password" not in db

    params = {k: str(v) for k, v in db.items() if k != "statement_timeout"}
    params["options"] = f"-c statement_timeout={int(db['statement_timeout']) * 1000}"
    params["user"] = user
    params["password"] = password
    return make_conninfo("", **params)


class MaxLevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.level


def setup_logging(log_file: str | None) -> None:
    log.handlers.clear()
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"
    )

    out = logging.StreamHandler(sys.stdout)
    out.addFilter(MaxLevelFilter(logging.ERROR))
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.ERROR)
    for handler in (out, err):
        handler.setFormatter(fmt)
        log.addHandler(handler)

    if log_file:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8")
        except OSError as e:
            log.error(
                "Не удалось открыть лог-файл %s: %s. Продолжаю без файла.", log_file, e
            )
        else:
            fh.setFormatter(fmt)
            log.addHandler(fh)


def query_version(conninfo: str) -> list[tuple]:
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION();")
            return cur.fetchall()


def run_with_deadline(func: Callable[[], Any], deadline: float) -> Any:
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = func()
        except BaseException as e:
            box["error"] = e

    thread = threading.Thread(target=worker, daemon=True, name="db-check")
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        raise TimeoutError(f"проверка не завершилась за {deadline} с (жёсткий дедлайн)")
    if "error" in box:
        raise box["error"]
    return box["value"]


def classify(rows: list[tuple], expected_prefix: str) -> tuple[bool, str]:
    if len(rows) == 1 and len(rows[0]) == 1 and isinstance(rows[0][0], str):
        version = rows[0][0]
        if re.match(re.escape(expected_prefix) + r"(?![0-9])", version):
            return True, version
        return False, version
    return False, repr(rows)


def check_once(settings: Settings) -> bool:
    started = time.monotonic()
    try:
        conninfo = build_conninfo(settings.db, settings.user, settings.password)
        rows = run_with_deadline(lambda: query_version(conninfo), settings.deadline)
    except psycopg.Error as e:
        log.error(
            "DB check FAILED (%.2fs): %s",
            time.monotonic() - started,
            " ".join(str(e).split()),
        )
        return False
    except Exception as e:
        log.error(
            "DB check FAILED (%.2fs): %s: %s",
            time.monotonic() - started,
            type(e).__name__,
            e,
        )
        return False

    elapsed = time.monotonic() - started
    typical, text = classify(rows, settings.expected_prefix)
    if typical:
        log.info("DB check OK (%.2fs): %s", elapsed, text)
    else:
        log.warning(
            "DB check OK (%.2fs), but ATYPICAL version response (expected prefix %r): %s",
            elapsed,
            settings.expected_prefix,
            text,
        )
    return True


def main() -> int:
    try:
        settings = load_settings(os.environ)
    except ConfigError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 2

    setup_logging(settings.log_file)

    stop = threading.Event()

    def on_signal(signum: int, _frame: Any) -> None:
        log.info("Получен сигнал %s, останавливаюсь", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    db = settings.db
    log.info(
        "Pinger started: target=%s:%s/%s user=%s interval=%ss hard_deadline=%ss log_file=%s",
        db["host"],
        db["port"],
        db["dbname"],
        settings.user,
        settings.interval,
        settings.deadline,
        settings.log_file or "-",
    )

    next_run = time.monotonic()
    while not stop.is_set():
        check_once(settings)
        next_run += settings.interval
        now = time.monotonic()
        if next_run < now:
            next_run = now
        stop.wait(next_run - now)

    log.info("Pinger stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
