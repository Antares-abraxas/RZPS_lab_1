import getpass
import os
import sys

import config
import console
import psycopg
from errors import CONNECT_FAILED, UserError, friendly
from repository import Repository

MAX_LOGIN_ATTEMPTS = 3
YES = {"y", "yes", "д", "да"}


def yes_no(prompt: str) -> bool:
    return console.ask(f"{prompt} [y/N]: ").lower() in YES


def pick_table(repo: Repository) -> str:
    names = repo.tables()
    for number, name in enumerate(names, 1):
        console.say(f"  {number}. {name}")
    raw = console.ask("Таблица (номер или имя): ")
    if raw.isdecimal() and len(raw) <= 3 and 1 <= int(raw) <= len(names):
        return names[int(raw) - 1]
    if raw.lower() in names:
        return raw.lower()
    raise UserError("Такой таблицы нет в списке.")


def pick_relation(repo: Repository):
    relations = repo.relations()
    if not relations:
        raise UserError("Связанные таблицы не настроены.")
    if len(relations) == 1:
        return relations[0]
    for number, rel in enumerate(relations, 1):
        console.say(f"  {number}. {rel.parent} -> {rel.child}")
    raw = console.ask("Связь (номер): ")
    if raw.isdecimal() and len(raw) <= 3 and 1 <= int(raw) <= len(relations):
        return relations[int(raw) - 1]
    raise UserError("Такой связи нет в списке.")


def show_columns(repo: Repository, table: str) -> None:
    console.say("Колонки: " + repo.describe(table))


def show_result(repo: Repository, names: list[str], rows: list[tuple]) -> None:
    if rows:
        console.say(console.format_table(names, rows))
    console.info(f"Запрос выполнен успешно, получено строк: {len(rows)}")
    if len(rows) >= repo.limit:
        console.say(f"Показаны первые {repo.limit} строк.")


def read_pairs(
    repo: Repository, table: str, writable: bool, title: str
) -> list[tuple[str, str]]:
    console.say(title)
    pairs: list[tuple[str, str]] = []
    while True:
        name = console.ask("  Колонка (Enter - закончить): ")
        if not name:
            return pairs
        try:
            col = repo.column(table, name, writable=writable)
        except UserError as exc:
            console.error(str(exc))
            continue
        value = console.ask(f"  Значение для {col.name} (пусто - NULL): ")
        pairs.append((col.name, value))


def read_row(
    repo: Repository, table: str, skip: tuple[str, ...] = ()
) -> list[tuple[str, str]]:
    pairs = []
    for col in repo.columns(table):
        if col.identity or col.name in skip:
            continue
        required = not col.nullable and not col.has_default
        hint = "обязательно" if required else "Enter - пропустить"
        while True:
            value = console.ask(f"  {col.name} [{col.data_type}, {hint}]: ")
            if value or not required:
                break
            console.error("Это поле обязательно.")
        if value:
            pairs.append((col.name, value))
    return pairs


def view_all(repo: Repository) -> None:
    table = pick_table(repo)
    show_result(repo, *repo.select(table))


def view_filter_one(repo: Repository) -> None:
    table = pick_table(repo)
    show_columns(repo, table)
    column = repo.column(table, console.ask("Колонка для фильтра: "))
    value = console.ask(f"Значение для {column.name} (пусто - NULL): ")
    show_result(repo, *repo.select(table, [(column.name, value)]))


def view_filter_many(repo: Repository) -> None:
    table = pick_table(repo)
    show_columns(repo, table)
    pairs = read_pairs(repo, table, False, "Условия отбора (объединяются через AND):")
    if not pairs:
        raise UserError("Не указано ни одного условия.")
    show_result(repo, *repo.select(table, pairs))


def update_one(repo: Repository) -> None:
    table = pick_table(repo)
    show_columns(repo, table)
    record_id = console.ask("Id записи: ")
    changes = read_pairs(repo, table, True, "Что изменить (id менять нельзя):")
    count = repo.update_one(table, record_id, changes)
    if count == 0:
        raise UserError("Запись с таким id не найдена, изменений нет.")
    console.info(f"Запись обновлена, изменено строк: {count}")


def update_many(repo: Repository) -> None:
    table = pick_table(repo)
    show_columns(repo, table)
    set_col = repo.column(table, console.ask("Колонка для изменения: "), writable=True)
    new_value = console.ask(f"Новое значение для {set_col.name} (пусто - NULL): ")
    where_col = repo.column(table, console.ask("Колонка для отбора: "))
    console.say("Значения для отбора (по одному в строке, пустая строка - конец):")
    values = []
    while True:
        value = console.ask("  > ")
        if not value:
            break
        values.append(value)
    count = repo.update_many(table, set_col.name, new_value, where_col.name, values)
    console.info(f"Изменено строк: {count}")


def insert_one(repo: Repository) -> None:
    table = pick_table(repo)
    show_columns(repo, table)
    new_id = repo.insert_one(table, read_row(repo, table))
    console.info(f"Строка добавлена в «{table}», id = {new_id}")


def insert_many_rows(repo: Repository) -> None:
    table = pick_table(repo)
    show_columns(repo, table)
    rows = []
    while True:
        console.say(f"Строка {len(rows) + 1}:")
        rows.append(read_row(repo, table))
        if not yes_no("Добавить ещё одну строку?"):
            break
    ids = repo.insert_many(table, rows)
    console.info(
        f"Добавлено строк в «{table}»: {len(ids)}, id: {', '.join(map(str, ids))}"
    )


def insert_linked(repo: Repository) -> None:
    rel = pick_relation(repo)
    console.say(f"Родительская запись ({rel.parent}):")
    parent = read_row(repo, rel.parent)
    console.say(
        f"Связанная запись ({rel.child}), колонка {rel.fk} заполнится автоматически:"
    )
    child = read_row(repo, rel.child, skip=(rel.fk,))
    parent_id, child_ids = repo.insert_linked_many(rel, [(parent, [child])])[0]
    console.info(
        f"Добавлено: {rel.parent}.id = {parent_id}, {rel.child}.id = {child_ids[0]}"
    )


def insert_linked_many(repo: Repository) -> None:
    rel = pick_relation(repo)
    groups = []
    while True:
        console.say(f"Родительская запись ({rel.parent}):")
        parent = read_row(repo, rel.parent)
        children = []
        while True:
            console.say(
                f"Связанная строка ({rel.child}), колонка {rel.fk} заполнится автоматически:"
            )
            children.append(read_row(repo, rel.child, skip=(rel.fk,)))
            if not yes_no("Добавить ещё одну связанную строку?"):
                break
        groups.append((parent, children))
        if not yes_no("Добавить ещё одну родительскую запись?"):
            break
    results = repo.insert_linked_many(rel, groups)
    for parent_id, child_ids in results:
        console.info(
            f"Добавлено: {rel.parent}.id = {parent_id}, "
            f"{rel.child}.id = {', '.join(map(str, child_ids))}"
        )


ACTIONS = {
    "1": ("Просмотр таблицы без фильтра", view_all),
    "2": ("Просмотр с фильтром по одному значению", view_filter_one),
    "3": ("Просмотр с фильтром по нескольким значениям", view_filter_many),
    "4": ("Обновить одну запись по id", update_one),
    "5": ("Обновить несколько записей (WHERE ... IN)", update_many),
    "6": ("Добавить одну строку в таблицу", insert_one),
    "7": ("Добавить одну строку в связанные таблицы", insert_linked),
    "8": ("Добавить несколько строк в одну таблицу", insert_many_rows),
    "9": ("Добавить несколько строк в связанные таблицы", insert_linked_many),
}


def run_action(repo: Repository, action) -> None:
    try:
        action(repo)
    except EOFError:
        raise
    except KeyboardInterrupt:
        console.say()
        console.info("Операция отменена.")
    except UserError as exc:
        console.error(str(exc))
    except psycopg.Error as exc:
        console.raw_error(f"Ошибка БД: {exc!r}", exc)
        console.error(friendly(exc))
    except Exception as exc:
        console.raw_error(f"Необработанная ошибка: {exc!r}", exc)
        console.error(friendly(exc))


def login(settings: config.Settings):
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        user = console.ask("Логин: ")
        password = getpass.getpass("Пароль: ")
        try:
            config.validate_credentials(user, password)
            conninfo = config.build_conninfo(settings.db, user, password)
        except ValueError as exc:
            console.error(f"Некорректный ввод: {exc}")
            continue
        try:
            conn = psycopg.connect(conninfo, autocommit=True)
        except psycopg.Error as exc:
            console.raw_error(f"Ошибка подключения (пользователь {user!r}): {exc!r}")
            console.error(f"{CONNECT_FAILED} (попытка {attempt}/{MAX_LOGIN_ATTEMPTS})")
            continue
        console.info(f"Подключение к БД выполнено успешно, пользователь: {user}")
        return conn
    console.error("Число попыток исчерпано.")
    return None


def menu_loop(repo: Repository, conn) -> int:
    while True:
        if conn.closed or conn.broken:
            console.error("Соединение с БД потеряно. Перезапустите приложение.")
            return 1
        console.say()
        console.say("=== Меню ===")
        for key, (title, _) in ACTIONS.items():
            console.say(f"  {key}. {title}")
        console.say("  0. Выход")
        try:
            choice = console.ask("Выбор: ")
        except (EOFError, KeyboardInterrupt):
            console.say()
            return 0
        if choice == "0":
            return 0
        entry = ACTIONS.get(choice)
        if entry is None:
            console.error("Нет такого пункта меню.")
            continue
        try:
            run_action(repo, entry[1])
        except EOFError:
            return 0


def main() -> int:
    try:
        settings = config.load_settings(os.environ)
    except config.ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    console.setup_logging(settings.log_file)

    try:
        conn = login(settings)
    except (EOFError, KeyboardInterrupt):
        console.say()
        return 130
    if conn is None:
        return 1

    with conn:
        repo = Repository(
            conn, settings.tables, settings.display_limit, settings.relations
        )
        try:
            repo.load_schema()
        except psycopg.Error as exc:
            console.raw_error(f"Ошибка чтения схемы: {exc!r}", exc)
            console.error("Не удалось получить список таблиц.")
            return 1
        if not repo.tables():
            console.error("Нет доступных таблиц для этого пользователя.")
            return 1
        code = menu_loop(repo, conn)
    console.info("Работа завершена.")
    return code


if __name__ == "__main__":
    sys.exit(main())
