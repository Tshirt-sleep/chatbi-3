"""Small, non-sensitive deployment metadata shared by health and log events."""

from __future__ import annotations

import os
import re

APP_VERSION = "0.1.0"


def release_fields() -> dict[str, str]:
    """Return a bounded version and sanitized platform-provided build identifier."""
    build_id = os.getenv("RENDER_GIT_COMMIT") or os.getenv("CHATBI_BUILD_ID") or "unknown"
    build_id = re.sub(r"[^A-Za-z0-9._-]", "", build_id)[:40] or "unknown"
    return {"service": "chatbi-api", "version": APP_VERSION, "build_id": build_id}
