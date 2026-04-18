FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OCR_STORAGE_DIR=/data/files \
    OCR_TMP_DIR=/tmp/ocr-wrapper \
    OCR_MODEL_NAME=mistral-ocr-latest \
    TESSERACT_LANG=eng \
    OCR_TEXT_THRESHOLD=50 \
    FILE_TTL_SECONDS=604800 \
    DEFAULT_VISIBILITY=workspace \
    PUBLIC_BASE_URL=http://127.0.0.1:8089

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    ocrmypdf \
    ghostscript \
    qpdf \
    pngquant \
    unpaper \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py .
RUN mkdir -p /data/files /tmp/ocr-wrapper

EXPOSE 8089
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8089"]
