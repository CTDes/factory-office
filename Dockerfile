# factory-office: standard library only, so the image is Python and this package.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FACTORY_OFFICE_DB=/data/office.db

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --disable-pip-version-check . \
 && rm -rf /app/src \
 && useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin office \
 && mkdir -p /data && chown office /data

USER office
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2)"]

# Inside the container it listens on every interface; compose.yaml publishes it on 127.0.0.1 only.
CMD ["factory-office", "serve", "--host", "0.0.0.0", "--port", "8765"]
