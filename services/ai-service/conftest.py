"""pytest 环境：保证可以从任意目录运行测试。"""

from __future__ import annotations

import sys
from pathlib import Path

AI_SERVICE_DIR = Path(__file__).resolve().parent
REPO_ROOT = AI_SERVICE_DIR.parents[1]

for p in (AI_SERVICE_DIR, REPO_ROOT / "packages" / "contracts" / "py"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
