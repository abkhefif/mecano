import asyncio
import threading
import uuid

import boto3
import structlog
from fastapi import UploadFile

from app.config import settings

logger = structlog.get_logger()

# Maximum file size: 5 MB
MAX_FILE_SIZE = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}
# SEC-023: Whitelist of allowed upload folders to prevent path traversal
ALLOWED_UPLOAD_FOLDERS = {"identity", "proofs", "cv", "avatars", "diplomas", "disputes"}

# Magic bytes for file type validation
MAGIC_BYTES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG"],
    "application/pdf": [b"%PDF"],
}


def _validate_magic_bytes(content: bytes, content_type: str) -> bool:
    """Validate file content matches declared content type via magic bytes."""
    signatures = MAGIC_BYTES.get(content_type, [])
    for sig in signatures:
        if content[:len(sig)] == sig:
            return True
    return False


# AUD-M02: Cache the S3 client at module level to avoid recreating on each upload
# AUD-009: Use a lock for thread-safe client creation (double-check pattern)
_s3_client = None
_s3_lock = threading.Lock()


def get_s3_client():
    """Get or create a cached S3-compatible client for R2/S3.

    Thread-safe via double-checked locking. The boto3 low-level client is
    safe for concurrent use once created; only creation needs synchronization.
    """
    global _s3_client
    if _s3_client is None:
        with _s3_lock:
            if _s3_client is None:  # double-check
                kwargs = {
                    "service_name": "s3",
                    "aws_access_key_id": settings.R2_ACCESS_KEY_ID,
                    "aws_secret_access_key": settings.R2_SECRET_ACCESS_KEY,
                }
                if settings.R2_ENDPOINT_URL:
                    kwargs["endpoint_url"] = settings.R2_ENDPOINT_URL
                _s3_client = boto3.client(**kwargs)
    return _s3_client


async def upload_file(file: UploadFile, folder: str) -> str:
    """Upload a file to R2/S3 and return the public URL.

    Args:
        file: The uploaded file.
        folder: Subfolder in the bucket (e.g., "identity", "proofs").

    Returns:
        Public URL of the uploaded file.

    Raises:
        ValueError: If file type or size is invalid.
    """
    # SEC-023: Validate folder against whitelist to prevent path traversal
    if folder not in ALLOWED_UPLOAD_FOLDERS:
        raise ValueError(f"Upload folder '{folder}' is not allowed.")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"File type {file.content_type} not allowed. Use JPEG or PNG.")

    # Early rejection: check the Content-Length header before reading any bytes.
    # This avoids buffering an oversized file into memory when the client
    # declares its size upfront.
    if file.size is not None and file.size > MAX_FILE_SIZE:
        raise ValueError(f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.")

    # Read file in bounded chunks. Use a bytearray to avoid quadratic
    # concatenation cost, and enforce the size limit incrementally so we
    # never hold more than MAX_FILE_SIZE + CHUNK_SIZE in memory.
    CHUNK_SIZE = 64 * 1024  # 64KB chunks
    content = bytearray()

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break

        content.extend(chunk)

        # Check size early and abort if exceeded
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.")

    content = bytes(content)

    # After reading is complete and size is OK, validate magic bytes
    if not _validate_magic_bytes(content, file.content_type):
        raise ValueError(
            f"File content does not match declared type {file.content_type}. "
            "The file may be corrupted or mislabeled."
        )

    ext_map = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
    ext = ext_map.get(file.content_type, "bin")
    key = f"{folder}/{uuid.uuid4()}.{ext}"

    if not settings.R2_ENDPOINT_URL:
        # Development mode: return a mock URL
        mock_url = f"https://storage.emecano.dev/{key}"
        logger.info("file_upload_mock", key=key, url=mock_url)
        return mock_url

    client = get_s3_client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=content,
        ContentType=file.content_type,
    )

    url = f"{settings.R2_PUBLIC_URL}/{key}"
    logger.info("file_uploaded", key=key, url=url)
    return url


# MED-01: Sensitive folders whose files should use pre-signed URLs
SENSITIVE_FOLDERS = {"identity", "proofs", "cv"}


async def generate_presigned_url(key: str, expires_in: int = 900) -> str:
    """Generate a time-limited pre-signed URL for an R2/S3 object.

    Use this for files in sensitive folders (identity, cv, proofs) to avoid
    exposing permanent public URLs for PII documents.

    Args:
        key: The object key (e.g., "identity/uuid.jpg").
        expires_in: URL validity in seconds (default 15 minutes).

    Returns:
        Pre-signed URL string, or a mock URL in development.
    """
    if not settings.R2_ENDPOINT_URL:
        return f"https://storage.emecano.dev/{key}?presigned=mock&expires={expires_in}"

    client = get_s3_client()
    url = await asyncio.to_thread(
        client.generate_presigned_url,
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in,
    )
    logger.info("presigned_url_generated", key=key, expires_in=expires_in)
    return url


def get_key_from_url(url: str) -> str | None:
    """Extract the object key from a public R2 URL."""
    if not url or not settings.R2_PUBLIC_URL:
        return None
    prefix = f"{settings.R2_PUBLIC_URL}/"
    if url.startswith(prefix):
        return url[len(prefix):]
    # Mock URL in dev mode
    mock_prefix = "https://storage.emecano.dev/"
    if url.startswith(mock_prefix):
        return url[len(mock_prefix):]
    return None


async def get_sensitive_url(url: str | None, expires_in: int = 900) -> str | None:
    """Convert a public URL to a pre-signed URL if it points to a sensitive file.

    Returns the pre-signed URL, or None if the input URL is None/empty.
    """
    if not url:
        return None
    key = get_key_from_url(url)
    if not key:
        return url  # Can't extract key, return as-is
    return await generate_presigned_url(key, expires_in)


MAX_FILE_BYTES_SIZE = 10 * 1024 * 1024  # 10 MB


async def upload_file_bytes(content: bytes, key: str, content_type: str) -> str:
    """Upload raw bytes to R2/S3 and return the public URL.

    This function is intended for trusted, server-generated content only
    (e.g., PDF reports). It does NOT validate magic bytes or content type.
    Callers must ensure the content is safe before invoking this function.

    Raises:
        ValueError: If content exceeds the 10 MB size limit.
    """
    if len(content) > MAX_FILE_BYTES_SIZE:
        raise ValueError(f"Content too large. Maximum size is {MAX_FILE_BYTES_SIZE // (1024 * 1024)} MB.")

    if not settings.R2_ENDPOINT_URL:
        mock_url = f"https://storage.emecano.dev/{key}"
        logger.info("file_upload_mock", key=key, url=mock_url)
        return mock_url

    client = get_s3_client()
    await asyncio.to_thread(
        client.put_object,
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=content,
        ContentType=content_type,
    )

    url = f"{settings.R2_PUBLIC_URL}/{key}"
    logger.info("file_uploaded", key=key, url=url)
    return url
