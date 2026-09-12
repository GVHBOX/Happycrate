from __future__ import annotations

from collections.abc import Iterable

from .. import log

logger = log.get_logger(__name__)

class DeliveryResult:

    __slots__ = ("added", "errors", "method", "ok", "total")

    def __init__(self, added: int, total: int,
                 errors: list[str] | None = None,
                 method: str = "", ok: bool | None = None):
        self.added = added
        self.total = total
        self.errors = errors or []
        self.method = method
        self.ok = (added > 0) if ok is None else ok

    def message(self) -> str:
        if self.total == 0:
            return "没有可提交的磁力链接"
        if self.ok and self.added == self.total:
            return f"已提交 {self.added} 个任务"
        if self.ok:
            return f"已提交 {self.added}/{self.total} 个任务"
        detail = f"：{self.errors[0]}" if self.errors else ""
        return f"提交失败（0/{self.total}）{detail}"

    def __repr__(self) -> str:
        return (f"DeliveryResult(added={self.added}, total={self.total}, "
                f"method={self.method!r}, errors={len(self.errors)})")

class Method:

    key: str = ""
    label: str = ""

    def available(self) -> bool:
        raise NotImplementedError

    def deliver(self, magnets: list[str], timeout: int) -> DeliveryResult:
        raise NotImplementedError

class Downloader:

    key: str = ""
    label: str = ""
    protocol: str = "magnet:"

    def methods(self) -> list[Method]:
        return [m for m in self._all_methods() if _safe_available(m)]

    def _all_methods(self) -> list[Method]:
        raise NotImplementedError

    def available(self) -> bool:
        return bool(self.methods())

    def add(self, magnets: Iterable[str], timeout: int = 15,
            order: list[str] | None = None) -> DeliveryResult:
        items = _clean(magnets)
        if not items:
            return DeliveryResult(0, 0, ["没有有效的磁力链接"])

        methods = self._ordered(order)
        if not methods:
            return DeliveryResult(0, len(items),
                                  [f"{self.label} 未找到或不可用"])

        errors: list[str] = []
        for method in methods:
            try:
                result = method.deliver(items, timeout)
            except Exception as exc:
                logger.warning("%s 的 %s 方式异常：%s: %s",
                               self.label, method.key, type(exc).__name__, exc)
                errors.append(f"{method.label}：{exc}")
                continue
            if result.ok:
                return result
            reason = result.errors[0] if result.errors else "未知原因"
            logger.warning("%s 的 %s 方式失败，尝试下一条路径：%s",
                           self.label, method.key, reason)
            errors.append(f"{method.label}：{reason}")

        return DeliveryResult(0, len(items), errors)

    def _ordered(self, order: list[str] | None) -> list[Method]:
        usable = self.methods()
        if not order:
            return usable
        rank = {k: i for i, k in enumerate(order)}
        return sorted(usable, key=lambda m: rank.get(m.key, len(rank)))

def _clean(magnets: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in magnets:
        if not raw:
            continue
        m = str(raw).strip()
        if not m.lower().startswith("magnet:"):
            continue
        if m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out

def _safe_available(method: Method) -> bool:
    try:
        return bool(method.available())
    except Exception as exc:
        logger.debug("%s 可用性探测异常：%s: %s", method.key, type(exc).__name__, exc)
        return False

