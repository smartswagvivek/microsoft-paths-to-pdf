FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers \
    HOST=0.0.0.0 \
    PORT=8501 \
    DATA_DIR=/data
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && python -m playwright install --with-deps --no-shell chromium \
    && useradd --create-home appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data /opt/browsers
COPY --chown=appuser:appuser backend/*.py backend/
COPY --chown=appuser:appuser frontend/ frontend/
USER appuser
EXPOSE 8501
CMD ["python", "-B", "backend/app.py"]
