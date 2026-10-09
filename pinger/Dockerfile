FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --no-create-home pinger \
    && mkdir /logs && chown pinger:pinger /logs

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pinger.py config.toml ./

USER pinger
CMD ["python", "pinger.py"]
