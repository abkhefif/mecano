import asyncio
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


def get_s3_client():
    """Create an S3-compatible client for R2/S3."""
    kwargs = {
        "service_name": "s3",
        "aws_access_key_id": settings.R2_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.R2_SECRET_ACCESS_KEY,
    }
    if settings.R2_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.R2_ENDPOINT_URL
    return boto3.client(**kwargs)


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
