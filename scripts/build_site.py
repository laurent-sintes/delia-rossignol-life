from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delia_life.site_builder import build_site  # noqa: E402

parser = argparse.ArgumentParser(description="Build the allowlisted GitHub Pages site")
parser.add_argument("--output", type=Path, default=ROOT / "_site")
args = parser.parse_args()
print(json.dumps(build_site(ROOT, args.output), ensure_ascii=False, indent=2))
