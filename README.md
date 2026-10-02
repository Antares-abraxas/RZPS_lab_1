# RZPS: lab 1

Консольное приложение на Python: читает параметры подключения из `config.toml`,
запрашивает логин/пароль, подключается к PostgreSQL 18 (Docker) и выполняет `SELECT VERSION();`.

## Запуск

1. `cp .env.example .env` и задать пароли
2. `docker compose up -d --build`# pg-version-app
3. `python -m venv .venv && source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. `python app.py`
6. Тесты: `python -m unittest -v`
