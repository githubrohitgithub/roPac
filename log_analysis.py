"""
Structured parsing for kiosk / system log files attached in chat.
Extracts order counts, payment outcomes, and issues so the model can answer directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ingest import read_file

_ORDER_SUCCESS = re.compile(
    r"Place Order Success.*?\[(?P<ids>[^\]]+)\]",
    re.IGNORECASE,
)
_ORDER_FAIL = re.compile(
    r"Place Order Fail(?:ed|ure)?|Place Order Error|failed to place order",
    re.IGNORECASE,
)
_PAYMENT_ACCEPT = re.compile(r"Decision:\s*ACCEPT", re.IGNORECASE)
_PAYMENT_DECLINE = re.compile(
    r"Decision:\s*(?:DECLINE|REJECT|FAIL)|payment (?:failed|declined|rejected)",
    re.IGNORECASE,
)
_DB_ORDERS = re.compile(
    r"Orders in DB: total=(\d+), offline \(pending\)=(\d+)",
    re.IGNORECASE,
)
_OFFLINE_FOUND = re.compile(
    r"Found (\d+) (?:FreedomPay )?offline orders",
    re.IGNORECASE,
)
_SESSION_START = re.compile(r"New Session Started", re.IGNORECASE)
_LOG_TS = re.compile(r"^\[(\d{2}:\d{2}:\d{2} [^\]]+)\]")
_PRODUCT_JSON = re.compile(
    r"\[FreedomPayPaymentHandler\]\s*(\{.+?\})",
    re.IGNORECASE,
)
_ERROR_LINE = re.compile(r"\[Error\]", re.IGNORECASE)
_FALSE_ERROR = re.compile(
    r"successfully fetched|fetched menu successfully|successfully processed|no error",
    re.IGNORECASE,
)


@dataclass
class LogAnalysis:
    filename: str
    order_ids: list[str] = field(default_factory=list)
    order_events: list[str] = field(default_factory=list)
    payments_accepted: int = 0
    payments_declined: int = 0
    order_failures: int = 0
    db_total_latest: int | None = None
    db_pending_latest: int | None = None
    offline_orders_found_max: int = 0
    kiosk_sessions: int = 0
    products: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def total_orders_placed(self) -> int:
        return len(self.order_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "total_orders_placed": self.total_orders_placed,
            "order_ids": self.order_ids,
            "payments_accepted": self.payments_accepted,
            "payments_declined": self.payments_declined,
            "order_failures": self.order_failures,
            "db_total_latest": self.db_total_latest,
            "db_pending_latest": self.db_pending_latest,
            "offline_orders_found_max": self.offline_orders_found_max,
            "kiosk_sessions": self.kiosk_sessions,
            "products": self.products,
            "issues": self.issues,
        }


def is_log_path(path: str | Path) -> bool:
    name = Path(path).name.lower()
    if Path(path).suffix.lower() == ".log":
        return True
    return "log" in name or name.startswith("afcc")


def read_log_text(path: str | Path) -> str:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return ""
    return read_file(file_path)


def analyze_log_text(text: str, *, filename: str = "log") -> LogAnalysis:
    analysis = LogAnalysis(filename=filename)
    if not text.strip():
        return analysis

    seen_ids: set[str] = set()
    seen_products: set[str] = set()
    seen_issues: set[str] = set()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        ts_match = _LOG_TS.match(stripped)
        ts = ts_match.group(1) if ts_match else ""

        for match in _ORDER_SUCCESS.finditer(stripped):
            raw_ids = match.group("ids")
            ids = [i.strip() for i in raw_ids.split(",") if i.strip()]
            for oid in ids:
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    analysis.order_ids.append(oid)
            label = f"{ts} — placed {len(ids)} order(s): {', '.join(ids)}".strip(" —")
            analysis.order_events.append(label)

        if _ORDER_FAIL.search(stripped):
            analysis.order_failures += 1
            key = stripped[:220]
            if key not in seen_issues:
                seen_issues.add(key)
                analysis.issues.append(stripped[:300])

        if _PAYMENT_ACCEPT.search(stripped):
            analysis.payments_accepted += 1
        if _PAYMENT_DECLINE.search(stripped):
            analysis.payments_declined += 1
            key = stripped[:220]
            if key not in seen_issues:
                seen_issues.add(key)
                analysis.issues.append(stripped[:300])

        db_match = _DB_ORDERS.search(stripped)
        if db_match:
            analysis.db_total_latest = int(db_match.group(1))
            analysis.db_pending_latest = int(db_match.group(2))

        offline_match = _OFFLINE_FOUND.search(stripped)
        if offline_match:
            analysis.offline_orders_found_max = max(
                analysis.offline_orders_found_max, int(offline_match.group(1))
            )

        if _SESSION_START.search(stripped):
            analysis.kiosk_sessions += 1

        product_match = _PRODUCT_JSON.search(stripped)
        if product_match:
            try:
                payload = json.loads(product_match.group(1))
                name = (
                    str(payload.get("productName") or "").strip()
                    or str(payload.get("productDescription") or "").strip()
                )
                if name and name not in seen_products:
                    seen_products.add(name)
                    analysis.products.append(name)
            except json.JSONDecodeError:
                pass

        if _ERROR_LINE.search(stripped) and not _FALSE_ERROR.search(stripped):
            key = stripped[:220]
            if key not in seen_issues and len(analysis.issues) < 12:
                seen_issues.add(key)
                analysis.issues.append(stripped[:300])

    return analysis


def _query_tokens(query: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[a-zA-Z0-9_]+", query)
        if len(t) >= 3
    }


def _relevant_excerpts(text: str, query: str, *, max_lines: int = 8) -> list[str]:
    tokens = _query_tokens(query)
    if not tokens:
        tokens = {
            "order",
            "payment",
            "success",
            "fail",
            "error",
            "offline",
            "pending",
        }

    hits: list[tuple[int, str]] = []
    for line in text.splitlines():
        lower = line.lower()
        score = sum(1 for t in tokens if t in lower)
        if score <= 0:
            continue
        if any(
            k in lower
            for k in (
                "place order",
                "payment",
                "offline",
                "pending",
                "error",
                "fail",
                "success",
                "freedompay",
                "ordersync",
            )
        ):
            score += 2
        hits.append((score, line.strip()[:280]))

    hits.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _, line in hits:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
        if len(out) >= max_lines:
            break
    return out


def format_log_analysis_report(analysis: LogAnalysis) -> str:
    lines = [
        f"FILE: {analysis.filename}",
        "",
        "ORDER SUMMARY:",
        f"- Total orders placed (unique IDs): {analysis.total_orders_placed}",
    ]
    if analysis.order_ids:
        shown = analysis.order_ids[:20]
        suffix = f" … +{len(analysis.order_ids) - 20} more" if len(analysis.order_ids) > 20 else ""
        lines.append(f"- Order IDs: {', '.join(shown)}{suffix}")
    else:
        lines.append("- Order IDs: none found")

    lines.extend(
        [
            f"- Order failure events: {analysis.order_failures}",
            "",
            "PAYMENT SUMMARY:",
            f"- Payments ACCEPT: {analysis.payments_accepted}",
            f"- Payments DECLINED/FAILED: {analysis.payments_declined}",
            "",
            "SYNC / OFFLINE:",
        ]
    )
    if analysis.db_total_latest is not None:
        lines.append(
            f"- Latest DB snapshot: total={analysis.db_total_latest}, "
            f"offline/pending={analysis.db_pending_latest or 0}"
        )
    else:
        lines.append("- Latest DB snapshot: not found in log")
    lines.append(
        f"- Max offline orders queued for sync: {analysis.offline_orders_found_max}"
    )
    lines.append(f"- Kiosk sessions started: {analysis.kiosk_sessions}")

    if analysis.products:
        lines.extend(["", "PRODUCTS ORDERED (from payment handler):"])
        for product in analysis.products[:15]:
            lines.append(f"- {product}")
        if len(analysis.products) > 15:
            lines.append(f"- … +{len(analysis.products) - 15} more")

    if analysis.order_events:
        lines.extend(["", "ORDER TIMELINE (newest events):"])
        for event in analysis.order_events[-8:]:
            lines.append(f"- {event}")

    if analysis.issues:
        lines.extend(["", "ISSUES / ERRORS (real failures only):"])
        for issue in analysis.issues[:10]:
            lines.append(f"- {issue}")

    return "\n".join(lines)


def analyze_log_path(path: str | Path) -> LogAnalysis | None:
    file_path = Path(path).expanduser()
    if not is_log_path(file_path):
        return None
    text = read_log_text(file_path)
    if not text.strip():
        return None
    return analyze_log_text(text, filename=file_path.name)


def build_log_analysis_context(
    paths: list[str], *, query: str = ""
) -> str:
    """Structured log report for chat prompts — full file read, no truncation."""
    blocks: list[str] = []
    for raw in paths:
        file_path = Path(raw).expanduser()
        if not is_log_path(file_path):
            continue
        text = read_log_text(file_path)
        if not text.strip():
            continue
        analysis = analyze_log_text(text, filename=file_path.name)
        report = format_log_analysis_report(analysis)
        excerpts = _relevant_excerpts(text, query)
        if excerpts:
            report += "\n\nRELEVANT LOG LINES (for this question):\n"
            report += "\n".join(f"- {line}" for line in excerpts)
        blocks.append(report)

    if not blocks:
        return ""

    header = (
        "LOG ANALYSIS (pre-computed from attached file — answer the user's question "
        "using these facts; do not guess or ask them to wait):\n\n"
    )
    return header + "\n\n---\n\n".join(blocks)
