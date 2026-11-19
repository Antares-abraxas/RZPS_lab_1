import logging
import sys

log = logging.getLogger("shop")


def setup_logging(log_file: str | None) -> None:
    log.handlers.clear()
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.addHandler(logging.NullHandler())
    if not log_file:
        return
    try:
        handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError:
        error("Файл журнала недоступен, работа продолжится без него.")
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)


def say(text: str = "") -> None:
    print(text, flush=True)


def info(message: str) -> None:
    print(message, flush=True)
    log.info(message)


def error(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    log.error(message)


def audit(message: str) -> None:
    log.info(message)


def raw_error(message: str, exc: BaseException | None = None) -> None:
    log.error(message, exc_info=exc)


def ask(prompt: str) -> str:
    return input(prompt).strip()


def _cell(value: object, width: int) -> str:
    text = "NULL" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def format_table(names: list[str], rows: list[tuple], width: int = 40) -> str:
    body = [[_cell(v, width) for v in row] for row in rows]
    widths = [
        max([len(name)] + [len(row[i]) for row in body]) for i, name in enumerate(names)
    ]
    head = " | ".join(n.ljust(w) for n, w in zip(names, widths))
    line = "-+-".join("-" * w for w in widths)
    lines = [head, line]
    lines += [" | ".join(c.ljust(w) for c, w in zip(row, widths)) for row in body]
    return "\n".join(lines)
