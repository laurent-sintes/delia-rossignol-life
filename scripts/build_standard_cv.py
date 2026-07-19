from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.document_builder import build_documents  # noqa: E402

print(json.dumps(build_documents(ROOT), ensure_ascii=False, indent=2, sort_keys=True))
