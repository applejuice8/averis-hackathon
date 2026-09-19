"""Stage 3 — deterministic SI-vs-BL comparison. Never LLM-judged."""
import re

from .extract import COMPARE_FIELDS


def norm_party(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def norm_port(s) -> str:
    # compare on the port name proper: "SHANGHAI, CHINA (CNSHA)" == "SHANGHAI"
    name = (s or "").split(",")[0]
    return norm_party(name)


def norm_num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d][\d,]*(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def _eq(field: str, a, b) -> bool:
    if field in ("container_count", "gross_weight_kg"):
        return norm_num(a) == norm_num(b)
    if field in ("port_of_loading", "port_of_discharge"):
        return norm_port(a) == norm_port(b)
    return norm_party(a) == norm_party(b)


def verdict(si_fields: dict, bl_fields: dict) -> tuple[str, list[str]]:
    diffs = [f for f in COMPARE_FIELDS if not _eq(f, si_fields.get(f), bl_fields.get(f))]
    return ("MISMATCH", diffs) if diffs else ("OK", [])
