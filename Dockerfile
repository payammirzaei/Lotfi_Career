FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    UPLOAD_PATH=/usr/src/app/uploads \
    PORT=8000

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user; the uploads directory is the mount point for the persistent volume
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /usr/src/app/uploads \
    && chown -R appuser:appuser /usr/src/app/uploads
USER appuser

# Persistent storage is attached at /usr/src/app/uploads by the platform
# (Railway volume, Liara disk, or the "uploads" volume in docker-compose.yml).
EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn -w ${WEB_CONCURRENCY:-3} -b 0.0.0.0:${PORT} --access-logfile - wsgi:app"]
