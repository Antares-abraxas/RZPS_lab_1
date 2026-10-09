# RZPS: lab 2

Сервис-pinger (heartbeat) на Python: раз в `PING_INTERVAL_SECONDS` секунд (по умолчанию 300, то есть 5 минут)
подключается к PostgreSQL 18 и выполняет `SELECT VERSION();`.

- успех и «нетипичный» ответ на запрос версии пишутся в **stdout**
- ошибка подключения пишется в **stderr**
- при необходимости весь вывод дублируется в файл (`PING_LOG_FILE`)
- сетевые проблемы не вешают сервис, а ошибка не отменяет следующую проверку

## Структура

- `docker-compose.yml` содержит сервисы `db` (PostgreSQL 18) и `pinger`
- `Dockerfile`, `postgresql.conf`, `docker/initdb/` описывают образ БД (из lab 1)
- `pinger/` содержит приложение: `pinger.py`, `config.toml`, `Dockerfile`, `requirements.txt`, `test_pinger.py`
- `db.env` содержит демо-переменные для PostgreSQL
- `pinger.env` содержит демо-переменные для pinger

Хост, порт и имя БД, таймауты берутся из `pinger/config.toml` (он упакован в образ).

## Запуск

1. `docker compose up -d --build`
2. `docker compose logs -f pinger`
3. Свой env-файл для pinger: `PINGER_ENV_FILE=./my.env docker compose up -d`
4. Остановка: `docker compose down` (с удалением данных БД: `docker compose down -v`)

## Образ приложения

```bash
docker build -t pg-pinger:1.0.0 ./pinger
```

## Тесты

```bash
cd pinger
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest -v
```
