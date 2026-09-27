"""后端 Api 方法 ↔ 前端调用的双向对账，判定口径来自 api_contract.py（与测试共用）。

输出里 missing_in_backend / backend_never_called 是缺陷；
dispatchers / dispatch_targets / python_calls 是解释性字段，
用来说明「这几个名字凭什么算被调用了」。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scan import api_contract

report = api_contract.call_report()

print(json.dumps({
    "backend_count": report["backend_count"],
    "front_count": report["front_count"],
    "missing_in_backend": report["missing_in_backend"],
    "backend_never_called": report["backend_never_called"],
    "dispatchers": report["dispatchers"],
    "dispatch_targets": sorted(report["dispatch_targets"]),
    "python_only_calls": {k: v for k, v in sorted(report["python_calls"].items())
                          if k not in report["web_calls"]},
}, ensure_ascii=False, indent=1))
