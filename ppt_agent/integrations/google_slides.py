"""
Export a Google Slides presentation as PPTX bytes using a service account.

The service account JSON is stored base64-encoded in GOOGLE_SERVICE_ACCOUNT_JSON.
The presentation must be shared with the service account email (Viewer role is enough).
"""
from __future__ import annotations

import base64
import io
import json

import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request

from ppt_agent.config.settings import settings

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _credentials() -> service_account.Credentials:
    raw = settings.google_service_account_json.strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set in .env")

    # Accept plain JSON or base64-encoded JSON
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        info = json.loads(base64.b64decode(raw).decode())

    creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    creds.refresh(Request())
    return creds


async def export_as_pptx(presentation_id: str) -> bytes:
    """
    Download a Google Slides deck as PPTX bytes.
    Raises RuntimeError on auth failure or non-2xx response.
    """
    creds = _credentials()
    url = (
        f"https://www.googleapis.com/drive/v3/files/{presentation_id}/export"
        f"?mimeType={_EXPORT_MIME}"
    )
    headers = {"Authorization": f"Bearer {creds.token}"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Drive export returned {resp.status_code}: {resp.text[:200]}"
        )

    return resp.content
