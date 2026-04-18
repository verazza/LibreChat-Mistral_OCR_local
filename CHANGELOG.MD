# Local Mistral-OCR-Compatible Wrapper for LibreChat (v5)

v5 fixes:
- no HTTP self-call in the `document_url` branch
- if `document_url` points to the wrapper itself, the file is read directly from disk

## Start
```bash
docker compose down
docker compose up -d --build
```

## LibreChat
`.env`
```env
OCR_API_KEY=localtest
OCR_BASEURL=http://127.0.0.1:8089/v1
```

=========================================================
# Local Mistral-OCR-Compatible Wrapper for LibreChat (v4)

v4 additions:
- `GET /v1/files/{id}/url`
- `GET /v1/files/{id}/content`

This fixes the LibreChat flow that requests a signed file URL before running OCR.

## Start
```bash
docker compose up -d --build
```

## Important variable
In `docker-compose.yml`:
```yaml
PUBLIC_BASE_URL: "http://127.0.0.1:8089"
```

It must be reachable from LibreChat.

## LibreChat
`.env`
```env
OCR_API_KEY=localtest
OCR_BASEURL=http://127.0.0.1:8089/v1
```

`librechat.yaml`
```yaml
ocr:
  strategy: "mistral_ocr"
  apiKey: "${OCR_API_KEY}"
  baseURL: "${OCR_BASEURL}"
  mistralModel: "mistral-ocr-latest"
```

=========================================================
# Local Mistral-OCR-Compatible Wrapper for LibreChat (v3)

Extended compatibility:
- `POST /v1/files`
- `GET /v1/files`
- `GET /v1/files/{id}`
- `DELETE /v1/files/{id}`
- `POST /v1/ocr`
- `GET /v1/models`
- `GET /healthz`

v3 additions:
- file metadata closer to Mistral (`created_at`, `expires_at`, `mimetype`, `source`, `visibility`, `signature`, `sample_type`)
- `GET /v1/files` with `total`
- `POST /v1/ocr` also accepts:
  - `bbox_annotation_format`
  - `confidence_scores_granularity`
  - `document_annotation_format`
  - `document_annotation_prompt`
- `POST /v1/ocr` also returns `document_annotation` when requested
- `pages` filter support

## Start
```bash
docker compose up -d --build
```

## LibreChat
`.env`
```env
OCR_API_KEY=localtest
OCR_BASEURL=http://127.0.0.1:8089/v1
```

If LibreChat runs in a separate Docker container:
```env
OCR_API_KEY=localtest
OCR_BASEURL=http://host.docker.internal:8089/v1
```

`librechat.yaml`
```yaml
ocr:
  strategy: "mistral_ocr"
  apiKey: "${OCR_API_KEY}"
  baseURL: "${OCR_BASEURL}"
  mistralModel: "mistral-ocr-latest"
```

=========================================================
# Local Mistral-OCR-Compatible Wrapper for LibreChat (v2)

Implemented endpoints:
- `POST /v1/files`
- `GET /v1/files`
- `GET /v1/files/{id}`
- `DELETE /v1/files/{id}`
- `POST /v1/ocr`
- `GET /healthz`

## Start
```bash
docker compose up -d --build
```

## LibreChat
`.env`
```env
OCR_API_KEY=localtest
OCR_BASEURL=http://127.0.0.1:8089/v1
```

If LibreChat runs in a separate Docker container:
```env
OCR_API_KEY=localtest
OCR_BASEURL=http://host.docker.internal:8089/v1
```

`librechat.yaml`
```yaml
ocr:
  strategy: "mistral_ocr"
  apiKey: "${OCR_API_KEY}"
  baseURL: "${OCR_BASEURL}"
  mistralModel: "mistral-ocr-latest"
```

## Quick tests

Upload:
```bash
curl -s http://127.0.0.1:8089/v1/files \
  -H "Authorization: Bearer localtest" \
  -F "purpose=ocr" \
  -F "file=@/path/to/test.pdf;type=application/pdf"
```

List:
```bash
curl -s http://127.0.0.1:8089/v1/files \
  -H "Authorization: Bearer localtest"
```

Delete:
```bash
curl -s -X DELETE http://127.0.0.1:8089/v1/files/file-XXXX \
  -H "Authorization: Bearer localtest"
```

====================================================
# Local Mistral-OCR-Compatible Wrapper for LibreChat

This wrapper exposes two endpoints compatible with the most common Mistral OCR flow:

- `POST /v1/files`
- `POST /v1/ocr`

Under the hood it uses only local OCR:
- `ocrmypdf`
- `tesseract`
- `PyMuPDF`

## Start

```bash
docker compose up -d --build
```

Health check:

```bash
curl http://127.0.0.1:8089/healthz
```

## LibreChat configuration

In `.env`:

```env
OCR_API_KEY=localtest
OCR_BASEURL=http://host.docker.internal:8089/v1
```

or, if LibreChat runs on the Linux host and not in Docker:

```env
OCR_API_KEY=localtest
OCR_BASEURL=http://127.0.0.1:8089/v1
```

In `librechat.yaml`:

```yaml
ocr:
  strategy: "mistral_ocr"
  apiKey: "${OCR_API_KEY}"
  baseURL: "${OCR_BASEURL}"
  mistralModel: "mistral-ocr-latest"
```

## Manual test

### 1) File upload
```bash
curl -s http://127.0.0.1:8089/v1/files \
  -H "Authorization: Bearer localtest" \
  -F "purpose=ocr" \
  -F "file=@/path/to/test.pdf;type=application/pdf"
```

### 2) OCR using `file_id`
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

## Notes
- For already text-based PDFs, the wrapper first tries native text extraction.
- If the extracted text is too poor, it forces OCR with `ocrmypdf`.
- For images, it uses `tesseract`.
- The `Authorization: Bearer ...` header is required, but the token is not validated against a database; it is only used to mimic the behavior of an API service.

## Limits
- It only emulates the part needed by LibreChat.
- It does not implement the full Mistral OCR API surface.
- The `pages[].markdown` structure is the most useful part for LibreChat; advanced fields such as bbox and annotations are not fully implemented.
