"""Local-first environment loading and repository paths."""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

# A developer's process environment always takes precedence over the ignored local file.
load_dotenv(ROOT / ".env", override=False)
