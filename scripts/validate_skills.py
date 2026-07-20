from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.skill_validation import validate_skill_catalog  # noqa: E402

result = validate_skill_catalog(ROOT)
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
raise SystemExit(0 if result["ok"] else 1)
