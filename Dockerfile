FROM python:3.12-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="spectro" \
      org.opencontainers.image.description="Spektralanalyse von Audiodateien" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

# ffmpeg deckt die Dekodierung aller Formate ab (FLAC, DSD, APE, TrueHD,
# Opus, Videocontainer ...); fonts-dejavu wird von matplotlib gebraucht.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR=/tmp/mpl \
    UPLOAD_DIR=/data/uploads \
    CACHE_DIR=/data/cache \
    SIDECAR_DIR=/data/index

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY spectro.py .

RUN useradd -m -u 1000 spectro && mkdir -p /data/uploads /data/cache /data/index \
    && chown -R spectro:spectro /data /app
USER spectro

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)"

CMD ["uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "8080"]
