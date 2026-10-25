FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WENGU_DATA_DIR=/app/data \
    WENGU_UPLOADS_DIR=/app/data/uploads \
    WENGU_DB_PATH=/app/data/wengu.db \
    WENGU_PROMPTS_DIR=/app/llm_prompts \
    WENGU_APP_CONFIG_PATH=/app/config/app-config.json

WORKDIR /app

COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# rapidocr-onnxruntime 依赖 opencv-python（GUI 版，需 libGL/libxcb），容器里必须换回
# headless 版：先卸载 GUI 包再强制重装 headless，确保 cv2 文件归属 headless。
RUN pip install -i ${PIP_INDEX_URL} -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install -i ${PIP_INDEX_URL} --no-deps --force-reinstall "opencv-python-headless>=4.10,<5"

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
