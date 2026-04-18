# Local Mistral OCR-Compatible Wrapper for LibreChat

A self-hosted, Docker-based wrapper that exposes a **Mistral OCR-compatible API** for **LibreChat**, while performing OCR entirely with **local tools**.

This project is designed for users who want to integrate LibreChat with a **local OCR service** without relying on the official Mistral cloud endpoint. The wrapper mimics the API surface needed by LibreChat and translates OCR requests into a fully local processing pipeline.

## What this project is

This wrapper provides a **local API endpoint compatible with the Mistral OCR flow used by LibreChat**.

It is intended to let LibreChat interact with a local OCR backend as if it were speaking to a Mistral-style OCR service. The service accepts file uploads, stores them locally, and processes supported documents through local OCR tools.

Under the hood, it uses:

- `ocrmypdf`
- `tesseract`
- `PyMuPDF`

This means the OCR process runs **entirely on your own machine or server**.

## What it does

The wrapper exposes endpoints used by LibreChat for OCR workflows, including:

- `POST /v1/files`
- `GET /v1/files`
- `GET /v1/files/{id}`
- `GET /v1/files/{id}/url`
- `GET /v1/files/{id}/content`
- `DELETE /v1/files/{id}`
- `POST /v1/ocr`
- `GET /v1/models`
- `GET /healthz`

It supports the most relevant LibreChat OCR flow:

1. LibreChat uploads a file to the wrapper.
2. The wrapper stores the file locally.
3. LibreChat can request file metadata and a file URL.
4. LibreChat submits an OCR request referencing the uploaded file.
5. The wrapper extracts text locally and returns a Mistral-compatible response structure.

## Main features

- Local OCR processing only
- Mistral OCR-compatible API surface for LibreChat
- Docker-based deployment
- File upload and local file storage
- Signed URL-style flow compatibility for LibreChat
- Support for text extraction from PDFs and images
- Health check endpoint
- No dependency on the official Mistral cloud OCR service

## OCR behavior

The wrapper follows this logic:

- For text-based PDFs, it first attempts native text extraction.
- If the extracted text is too poor or insufficient, it forces OCR using `ocrmypdf`.
- For images, it uses `tesseract`.
- The output is shaped to match the structure that LibreChat expects, especially `pages[].markdown`.

## Requirements

Before starting, make sure you have:

- Docker installed
- Docker Compose available
- LibreChat already installed or available on the same machine or reachable network
- A free local port for the wrapper, by default `8089`

## Start the container

Build and start the container with:

```bash
docker compose up -d --build
```

If you need to rebuild cleanly, you can use:

```bash
docker compose down
docker compose up -d --build
```

## Health check

After startup, verify that the service is running:

```bash
curl http://127.0.0.1:8089/healthz
```

If the service is healthy, it should respond successfully.

## LibreChat configuration

LibreChat must be configured to use this wrapper as its OCR backend.

### Variables to add in LibreChat

In your LibreChat `.env` file, add:

```env
OCR_API_KEY=localtest
OCR_BASEURL=http://127.0.0.1:8089/v1
```

### If LibreChat runs in a separate Docker container

If LibreChat is running in Docker separately and must reach the wrapper through the Docker host, use:

```env
OCR_API_KEY=localtest
OCR_BASEURL=http://host.docker.internal:8089/v1
```

### LibreChat YAML configuration

In `librechat.yaml`, configure OCR like this:

```yaml
ocr:
  strategy: "mistral_ocr"
  apiKey: "${OCR_API_KEY}"
  baseURL: "${OCR_BASEURL}"
  mistralModel: "mistral-ocr-latest"
```

## Important runtime variable

In the wrapper `docker-compose.yml`, make sure the public base URL matches the address used to reach the service.

Example:

```yaml
PUBLIC_BASE_URL: "http://127.0.0.1:8089"
```

This value must be reachable by LibreChat.

If LibreChat accesses the wrapper through another hostname or IP, adjust `PUBLIC_BASE_URL` accordingly.

## Quick manual tests

### Upload a file

```bash
curl -s http://127.0.0.1:8089/v1/files \
  -H "Authorization: Bearer localtest" \
  -F "purpose=ocr" \
  -F "file=@/path/to/test.pdf;type=application/pdf"
```

### List uploaded files

```bash
curl -s http://127.0.0.1:8089/v1/files \
  -H "Authorization: Bearer localtest"
```

### Run OCR on an uploaded file

```bash
curl -s http://127.0.0.1:8089/v1/ocr \
  -H "Authorization: Bearer localtest" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral-ocr-latest",
    "document": {
      "type": "file",
      "file_id": "file-XXXX"
    }
  }'
```

### Delete an uploaded file

```bash
curl -s -X DELETE http://127.0.0.1:8089/v1/files/file-XXXX \
  -H "Authorization: Bearer localtest"
```

## Authentication note

The wrapper requires the `Authorization: Bearer ...` header, but the token is not validated against an external database or identity provider.

Its purpose is simply to emulate the behavior expected from an API service.

Example token used in this project:

```env
OCR_API_KEY=localtest
```

## Current limitations

- This project emulates only the OCR functionality needed by LibreChat.
- It does not implement the full Mistral OCR API surface.
- Advanced fields such as full bbox and annotation structures are not fully implemented.
- Compatibility is focused on practical LibreChat integration rather than full vendor parity.

## Typical use case

This project is useful when you want:

- a local OCR backend for LibreChat
- no dependency on external OCR cloud services
- a Docker-deployable OCR wrapper
- a Mistral-style OCR endpoint for self-hosted environments

## Summary

This wrapper gives LibreChat a **local OCR backend with a Mistral-compatible interface**.

LibreChat continues to use the `mistral_ocr` strategy, while the actual OCR work is handled locally by your own containerized service.

That makes it suitable for self-hosted deployments where you want more control over privacy, infrastructure, and local processing.
