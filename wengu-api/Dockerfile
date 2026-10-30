FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WENGU_DATA_DIR=/app/data \
    WENGU_DB_PATH=/app/data/wengu.db

WORKDIR /app

COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install -i ${PIP_INDEX_URL} -r requirements.txt

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
