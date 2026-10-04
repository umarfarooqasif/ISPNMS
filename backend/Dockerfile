FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY src ./src

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home app \
    && mkdir -p /data/storage && chown -R app:app /data
USER app

EXPOSE 8000
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", "-w", "3", "--timeout", "60", "--access-logfile", "-"]
