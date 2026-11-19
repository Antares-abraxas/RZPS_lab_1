import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from psycopg.conninfo import make_conninfo

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"

DB_KEYS = {
    "host": str,
    "port": int,
    "dbname": str,
    "sslmode": str,
    "connect_timeout": int,
    "statement_timeout": int,
    "application_name": str,
}
DB_REQUIRED = {"host", "port", "dbname", "connect_timeout", "statement_timeout"}
APP_KEYS = {"display_limit": int, "tables": list}
RELATION_KEYS = {"parent": str, "child": str, "fk": str}
SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

MAX_USER_BYTES = 63
MAX_PASSWORD_LEN = 1024


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Relation:
    parent: str
    child: str
    fk: str


@dataclass(frozen=True)
class Settings:
    db: dict[str, Any]
    display_limit: int
    tables: tuple[str, ...]
    relations: tuple[Relation, ...]
    log_file: str | None


def _check_section(
    section: Any, spec: dict[str, type], required: set[str], name: str
) -> None:
    if not isinstance(section, dict):
        raise ConfigError(f"Секция [{name}] отсутствует или имеет неверный формат")
    unknown = set(section) - set(spec)
    if unknown:
        raise ConfigError(f"Недопустимые ключи в [{name}]: {sorted(unknown)}")
    missing = required - set(section)
    if missing:
        raise ConfigError(f"В [{name}] не хватает ключей: {sorted(missing)}")
    for key, expected in spec.items():
        if key not in section:
            continue
        value = section[key]
        if type(value) is not expected:
            raise ConfigError(
                f"Ключ '{key}' в [{name}] должен иметь тип {expected.__name__}"
            )
        if isinstance(value, str) and "\x00" in value:
            raise ConfigError(f"Ключ '{key}' в [{name}] содержит NUL-символ")


def _check_ident(value: Any, what: str) -> str:
    if not isinstance(value, str) or not IDENT_RE.match(value):
        raise ConfigError(f"Недопустимое имя ({what}): {value!r}")
    return value


def load_settings(env: Mapping[str, str], path: Path | None = None) -> Settings:
    path = Path(path or DEFAULT_CONFIG)
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Файл конфигурации не найден: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Некорректный TOML в {path}: {exc}") from None

    unknown_top = set(data) - {"database", "app", "relations"}
    if unknown_top:
        raise ConfigError(f"Недопустимые секции: {sorted(unknown_top)}")

    db = data.get("database")
    _check_section(db, DB_KEYS, DB_REQUIRED, "database")
    if not 1 <= db["port"] <= 65535:
        raise ConfigError("port должен быть в диапазоне 1..65535")
    if "sslmode" in db and db["sslmode"] not in SSL_MODES:
        raise ConfigError(f"sslmode должен быть одним из {sorted(SSL_MODES)}")
    for key in ("connect_timeout", "statement_timeout"):
        if db[key] < 1:
            raise ConfigError(f"{key} должен быть >= 1")

    app = data.get("app")
    _check_section(app, APP_KEYS, set(APP_KEYS), "app")
    if not 1 <= app["display_limit"] <= 10000:
        raise ConfigError("display_limit должен быть в диапазоне 1..10000")
    if not app["tables"]:
        raise ConfigError("Список tables не может быть пустым")
    tables = tuple(_check_ident(t, "таблица") for t in app["tables"])

    relations = []
    raw_relations = data.get("relations", [])
    if not isinstance(raw_relations, list):
        raise ConfigError("relations должна быть массивом таблиц")
    for raw in raw_relations:
        _check_section(raw, RELATION_KEYS, set(RELATION_KEYS), "relations")
        relation = Relation(
            _check_ident(raw["parent"], "parent"),
            _check_ident(raw["child"], "child"),
            _check_ident(raw["fk"], "fk"),
        )
        if relation.parent not in tables or relation.child not in tables:
            raise ConfigError("Таблицы связи должны входить в список app.tables")
        relations.append(relation)

    log_file = (env.get("SHOP_LOG_FILE") or "").strip() or None
    return Settings(dict(db), app["display_limit"], tables, tuple(relations), log_file)


def validate_credentials(user: str, password: str) -> None:
    if not user:
        raise ValueError("Логин не может быть пустым")
    if not password:
        raise ValueError("Пароль не может быть пустым")
    if "\x00" in user or "\x00" in password:
        raise ValueError("Логин и пароль не должны содержать NUL-символ")
    if len(user.encode("utf-8")) > MAX_USER_BYTES:
        raise ValueError(f"Логин длиннее {MAX_USER_BYTES} байт")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"Пароль длиннее {MAX_PASSWORD_LEN} символов")


def build_conninfo(db: Mapping[str, Any], user: str, password: str) -> str:
    validate_credentials(user, password)
    assert "user" not in db and "password" not in db
    params = {k: str(v) for k, v in db.items() if k != "statement_timeout"}
    params["options"] = f"-c statement_timeout={int(db['statement_timeout']) * 1000}"
    params["user"] = user
    params["password"] = password
    return make_conninfo("", **params)
