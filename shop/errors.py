import psycopg

CONNECT_FAILED = (
    "Не удалось подключиться к БД. Проверьте логин, пароль и доступность сервера."
)


class UserError(Exception):
    pass


_BY_SQLSTATE = {
    "23505": "Запись с таким уникальным значением уже существует.",
    "23503": "Нарушена связь между таблицами: связанная запись не найдена или на запись есть ссылки.",
    "23502": "Не заполнено обязательное поле.",
    "23514": "Значение не соответствует ограничениям таблицы.",
    "42501": "Недостаточно прав для выполнения операции.",
    "57014": "Запрос выполнялся слишком долго и был отменён.",
}


def friendly(exc: BaseException) -> str:
    if isinstance(exc, UserError):
        return str(exc)
    if isinstance(exc, psycopg.Error):
        state = exc.sqlstate or ""
        if state in _BY_SQLSTATE:
            return _BY_SQLSTATE[state]
        if state.startswith("22"):
            return "Значение имеет неверный формат или выходит за допустимые пределы."
        if state.startswith("23"):
            return "Операция нарушает ограничения целостности данных."
        if isinstance(exc, psycopg.OperationalError):
            return "Потеряно соединение с БД или сервер временно недоступен."
        return "Не удалось выполнить операцию в БД."
    return "Внутренняя ошибка приложения."
