from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fitz  # PyMuPDF
import pytesseract
import requests
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel

APP_TITLE = "Local Mistral OCR-Compatible Wrapper"
MODEL_NAME = os.getenv("OCR_MODEL_NAME", "mistral-ocr-latest")
STORAGE_DIR = Path(os.getenv("OCR_STORAGE_DIR", "/data/files"))
TMP_DIR = Path(os.getenv("OCR_TMP_DIR", "/tmp/ocr-wrapper"))
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng")
OCR_TEXT_THRESHOLD = int(os.getenv("OCR_TEXT_THRESHOLD", "50"))
FILE_TTL_SECONDS = int(os.getenv("FILE_TTL_SECONDS", str(7 * 24 * 3600)))
DEFAULT_VISIBILITY = os.getenv("DEFAULT_VISIBILITY", "workspace")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8089")

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=APP_TITLE)


def _check_auth(auth_header: str | None) -> None:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")


def _now() -> int:
    return int(time.time())


def _new_file_id() -> str:
    return f"file-{uuid.uuid4().hex}"


def _file_meta_path(file_id: str) -> Path:
    return STORAGE_DIR / f"{file_id}.json"


def _guess_mimetype(filename: str | None) -> str:
    mt, _ = mimetypes.guess_type(filename or "")
    return mt or "application/octet-stream"


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_meta(
    *,
    file_id: str,
    filename: str,
    purpose: str,
    path: Path,
    visibility: str,
) -> dict[str, Any]:
    created_at = _now()
    mimetype = _guess_mimetype(filename)
    signature = _sha256_of_file(path)
    return {
        "id": file_id,
        "object": "file",
        "bytes": path.stat().st_size,
        "created_at": created_at,
        "expires_at": created_at + FILE_TTL_SECONDS,
        "filename": filename,
        "mimetype": mimetype,
        "num_lines": None,
        "purpose": purpose,
        "sample_type": "ocr_input",
        "signature": signature,
        "source": "local",
        "visibility": visibility or DEFAULT_VISIBILITY,
        "path": str(path),
    }


def _save_upload_to_storage(upload: UploadFile, purpose: str, visibility: str) -> dict[str, Any]:
    file_id = _new_file_id()
    suffix = Path(upload.filename or "upload.bin").suffix or ".bin"
    bin_path = STORAGE_DIR / f"{file_id}{suffix}"
    with bin_path.open("wb") as f:
        shutil.copyfileobj(upload.file, f)

    meta = _build_meta(
        file_id=file_id,
        filename=upload.filename or bin_path.name,
        purpose=purpose,
        path=bin_path,
        visibility=visibility,
    )
    _file_meta_path(file_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _load_file_meta(file_id: str) -> dict[str, Any]:
    meta_path = _file_meta_path(file_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown file id: {file_id}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _public_meta(meta: dict[str, Any]) -> dict[str, Any]:
    clean = dict(meta)
    clean.pop("path", None)
    return clean


def _list_file_meta() -> list[dict[str, Any]]:
    out = []
    for meta_path in sorted(STORAGE_DIR.glob("file-*.json")):
        try:
            out.append(_public_meta(json.loads(meta_path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def _delete_file_meta(file_id: str) -> bool:
    deleted = False
    meta_path = _file_meta_path(file_id)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            file_path = Path(meta.get("path", ""))
            if file_path.exists():
                file_path.unlink(missing_ok=True)
                deleted = True
        except Exception:
            pass
        meta_path.unlink(missing_ok=True)
        deleted = True

    for p in STORAGE_DIR.glob(f"{file_id}.*"):
        if p.name.endswith(".json"):
            continue
        if p.exists():
            p.unlink(missing_ok=True)
            deleted = True

    return deleted


def _pdf_page_texts(pdf_path: Path) -> list[str]:
    doc = fitz.open(pdf_path)
    texts = []
    for page in doc:
        texts.append(page.get_text("text").strip())
    doc.close()
    return texts


def _ocr_pdf_if_needed(src_pdf: Path, workdir: Path) -> Path:
    page_texts = _pdf_page_texts(src_pdf)
    if all(len(t) >= OCR_TEXT_THRESHOLD for t in page_texts):
        return src_pdf

    out_pdf = workdir / "ocr_output.pdf"
    cmd = [
        "ocrmypdf",
        "--force-ocr",
        "--optimize",
        "0",
        "-l",
        TESSERACT_LANG,
        str(src_pdf),
        str(out_pdf),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"OCRmyPDF failed: {e.stderr.decode('utf-8', errors='ignore')[:800]}",
        )
    return out_pdf


def _extract_pdf_pages(
    pdf_path: Path,
    include_image_base64: bool = False,
    requested_pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    doc = fitz.open(pdf_path)
    pages = []
    wanted = set(requested_pages) if requested_pages else None
    for page in doc:
        page_index = page.number
        one_based = page_index + 1
        if wanted is not None and one_based not in wanted and page_index not in wanted:
            continue

        try:
            markdown = page.get_text("text").strip()
        except Exception:
            markdown = ""

        images = []
        if include_image_base64:
            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img_bytes = pix.tobytes("png")
                images.append(
                    {
                        "id": f"img-{page_index}-{img_index}",
                        "top_left_x": 0,
                        "top_left_y": 0,
                        "bottom_right_x": 0,
                        "bottom_right_y": 0,
                        "image_base64": base64.b64encode(img_bytes).decode("ascii"),
                    }
                )

        pages.append(
            {
                "index": page_index,
                "markdown": markdown,
                "images": images,
                "dimensions": {
                    "dpi": 72,
                    "height": int(page.rect.height),
                    "width": int(page.rect.width),
                },
            }
        )
    doc.close()
    return pages


def _ocr_image(image_path: Path) -> list[dict[str, Any]]:
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image, lang=TESSERACT_LANG).strip()
    return [
        {
            "index": 0,
            "markdown": text,
            "images": [],
            "dimensions": {
                "dpi": 72,
                "height": int(image.height),
                "width": int(image.width),
            },
        }
    ]


class OCRDocument(BaseModel):
    type: str | None = None
    file_id: str | None = None
    document_url: str | None = None
    image_url: str | None = None


class OCRRequest(BaseModel):
    model: str | None = None
    document: OCRDocument | None = None
    pages: list[int] | None = None
    include_image_base64: bool | None = False
    image_limit: int | None = None
    image_min_size: int | None = None
    extract_header: bool | None = False
    extract_footer: bool | None = False
    table_format: str | None = None
    id: str | None = None
    bbox_annotation_format: str | None = None
    confidence_scores_granularity: str | None = None
    document_annotation_format: str | None = None
    document_annotation_prompt: str | None = None


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": MODEL_NAME}


@app.get("/v1/models")
def list_models(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": _now(),
                "owned_by": "local",
                "capabilities": ["ocr"],
            }
        ],
    }


@app.post("/v1/files")
async def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form("ocr"),
    visibility: str = Form(DEFAULT_VISIBILITY),
    authorization: str | None = Header(default=None),
):
    _check_auth(authorization)
    meta = _save_upload_to_storage(file, purpose, visibility)
    return _public_meta(meta)


@app.get("/v1/files")
def list_files(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    data = _list_file_meta()
    return {"data": data, "object": "list", "total": len(data)}


@app.get("/v1/files/{file_id}")
def get_file(file_id: str, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return _public_meta(_load_file_meta(file_id))


@app.get("/v1/files/{file_id}/url")
def get_file_url(file_id: str, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    _load_file_meta(file_id)
    return {"url": f"{PUBLIC_BASE_URL}/v1/files/{file_id}/content"}


@app.get("/v1/files/{file_id}/content")
def get_file_content(file_id: str, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    meta = _load_file_meta(file_id)
    file_path = Path(meta["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file content for id: {file_id}")
    return FileResponse(
        path=str(file_path),
        media_type=meta.get("mimetype", "application/octet-stream"),
        filename=meta.get("filename", file_path.name),
    )


@app.delete("/v1/files/{file_id}")
def delete_file(file_id: str, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    existed = _delete_file_meta(file_id)
    if not existed:
        raise HTTPException(status_code=404, detail=f"Unknown file id: {file_id}")
    return {"id": file_id, "object": "file.deleted", "deleted": True}


@app.post("/v1/ocr")
async def process_ocr(
    request: Request,
    authorization: str | None = Header(default=None),
):
    _check_auth(authorization)
    content_type = request.headers.get("content-type", "")
    tmp_work = Path(tempfile.mkdtemp(dir=TMP_DIR))
    try:
        uploaded_tmp: Path | None = None
        include_image_base64 = False
        model_name = MODEL_NAME
        requested_pages = None
        doc_annotation_format = None
        doc_annotation_prompt = None

        if "multipart/form-data" in content_type:
            form = await request.form()
            model_name = str(form.get("model") or MODEL_NAME)
            include_image_base64 = str(form.get("include_image_base64") or "").lower() == "true"
            up = form.get("file")
            if up is None:
                raise HTTPException(status_code=400, detail="multipart /v1/ocr requires file field")
            assert isinstance(up, UploadFile)
            suffix = Path(up.filename or "upload.bin").suffix or ".bin"
            uploaded_tmp = tmp_work / f"upload{suffix}"
            with uploaded_tmp.open("wb") as f:
                shutil.copyfileobj(up.file, f)
        else:
            body = await request.json()
            req = OCRRequest(**body)
            model_name = req.model or MODEL_NAME
            include_image_base64 = bool(req.include_image_base64)
            requested_pages = req.pages
            doc_annotation_format = req.document_annotation_format
            doc_annotation_prompt = req.document_annotation_prompt
            payload_doc = req.document.model_dump() if req.document else None
            if not payload_doc:
                raise HTTPException(status_code=400, detail="JSON /v1/ocr requires document")

            dtype = payload_doc.get("type")
            if dtype == "file":
                file_id = payload_doc.get("file_id") or payload_doc.get("id")
                if not file_id:
                    raise HTTPException(status_code=400, detail="document.file_id is required for file type")
                meta = _load_file_meta(file_id)
                uploaded_tmp = Path(meta["path"])

            elif dtype == "document_url":
                url = payload_doc.get("document_url")
                if not url:
                    raise HTTPException(status_code=400, detail="document.document_url is required")

                parsed = urlparse(url)
                public_base = urlparse(PUBLIC_BASE_URL)

                if (
                    parsed.scheme == public_base.scheme
                    and parsed.netloc == public_base.netloc
                    and parsed.path.startswith("/v1/files/")
                    and parsed.path.endswith("/content")
                ):
                    parts = parsed.path.strip("/").split("/")
                    if len(parts) >= 4:
                        file_id = parts[2]
                        meta = _load_file_meta(file_id)
                        uploaded_tmp = Path(meta["path"])
                    else:
                        raise HTTPException(status_code=400, detail="Invalid local document_url format")
                else:
                    auth_header = request.headers.get("authorization")
                    headers = {}
                    if auth_header:
                        headers["Authorization"] = auth_header
                    resp = requests.get(url, headers=headers, timeout=120)
                    resp.raise_for_status()
                    suffix = ".pdf" if "pdf" in resp.headers.get("content-type", "").lower() else ".bin"
                    uploaded_tmp = tmp_work / f"download{suffix}"
                    uploaded_tmp.write_bytes(resp.content)

            elif dtype == "image_url":
                url = payload_doc.get("image_url")
                if not url:
                    raise HTTPException(status_code=400, detail="document.image_url is required")
                auth_header = request.headers.get("authorization")
                headers = {}
                if auth_header:
                    headers["Authorization"] = auth_header
                resp = requests.get(url, headers=headers, timeout=120)
                resp.raise_for_status()
                uploaded_tmp = tmp_work / "image.bin"
                uploaded_tmp.write_bytes(resp.content)

            else:
                raise HTTPException(status_code=400, detail=f"Unsupported document.type: {dtype}")

        if uploaded_tmp is None or not uploaded_tmp.exists():
            raise HTTPException(status_code=400, detail="No input file resolved for OCR")

        suffix = uploaded_tmp.suffix.lower()
        if suffix == ".pdf":
            effective_pdf = _ocr_pdf_if_needed(uploaded_tmp, tmp_work)
            pages = _extract_pdf_pages(
                effective_pdf,
                include_image_base64=include_image_base64,
                requested_pages=requested_pages,
            )
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
            pages = _ocr_image(uploaded_tmp)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported input type: {suffix or 'unknown'}")

        document_annotation = None
        if doc_annotation_format:
            full_text = "\n\n".join([p.get("markdown", "") for p in pages]).strip()
            document_annotation = {
                "format": doc_annotation_format,
                "prompt": doc_annotation_prompt,
                "content": full_text,
            }

        return JSONResponse(
            {
                "model": model_name,
                "pages": pages,
                "document_annotation": document_annotation,
                "usage_info": {
                    "pages_processed": len(pages),
                    "doc_size_bytes": uploaded_tmp.stat().st_size,
                },
            }
        )
    finally:
        if tmp_work.exists():
            shutil.rmtree(tmp_work, ignore_errors=True)
