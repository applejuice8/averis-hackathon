"""Stage 2 — field extraction from SI/BL document text.

Deterministic first pass: map the many label synonyms to the 7 canonical
comparison fields. Handles two layouts:
  - inline `Label: value`            (txt, docx/xlsx reader output)
  - block layout: label on its own line, value on the next line (PDFs)
"""
import re

COMPARE_FIELDS = [
    "shipper", "consignee", "notify_party",
    "port_of_loading", "port_of_discharge",
    "container_count", "gross_weight_kg",
]

# canonical field -> label variants seen on SI/BL docs (from pools.LABELS)
LABELS = {
    "shipper": ["Shipper", "Shipper/Exporter", "Shipper (Principal or Seller)", "SHIPPER"],
    "consignee": ["Consignee", "Consignee (Non-Negotiable)", "CONSIGNEE", "To the Order of"],
    "notify_party": ["Notify Party", "Notify", "Notify Party/Intermediate Consignee", "NOTIFY PARTY"],
    "port_of_loading": ["Port of Loading", "Port of Loading (POL)", "Load Port", "POL", "PORT OF LOADING"],
    "port_of_discharge": ["Port of Discharge", "Port of Discharge (POD)", "Discharge Port", "POD", "PORT OF DISCHARGE"],
    "container_count": ["No. of Containers", "Total Containers", "No. of Containers or Packages", "Container Count"],
    "gross_weight_kg": ["Gross Weight (KG)", "Gross Wt (kgs)", "Gross Weight毛重(KGS)", "GROSS WEIGHT"],
}

# party/port fields whose value may live on the next line in block layout;
# numeric fields are only trusted inline ("No. of Containers: 6 x 40'HC")
BLOCK_VALUE_FIELDS = {
    "shipper", "consignee", "notify_party",
    "port_of_loading", "port_of_discharge",
}

BLANK_TOKENS = {"???", "_______", "TBA", "TBC", "", "N/A", "____MT"}
NUMERIC_FIELDS = {"container_count", "gross_weight_kg"}


def _norm_label(label: str) -> str:
    # strip parenthetical suffixes, CJK glosses, punctuation, case, TOTAL prefix
    label = re.sub(r"[(\[（].*?[)\]）]", " ", label)
    label = re.sub(r"[^\x00-\x7f]", " ", label)  # drop 毛重 etc.
    label = re.sub(r"[^a-z0-9/ ]", " ", label.lower())
    label = re.sub(r"\s+", " ", label).strip()
    return re.sub(r"^total\s+", "", label)


_LABEL2FIELD = {}
for _f, _variants in LABELS.items():
    for _v in _variants:
        _LABEL2FIELD[_norm_label(_v)] = _f


def _parse_number(text: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    return float(m.group(0).replace(",", "")) if m else None


def _clean_value(field: str, value: str) -> str:
    # name/address blocks joined as "NAME | addr; addr" -> keep the name part
    value = value.split(" | ")[0].strip()
    # ports carry "(UN/LOCODE)" suffixes in some formats -> drop the code
    if field in ("port_of_loading", "port_of_discharge"):
        value = re.sub(r"\([A-Z]{5}\)\s*$", "", value).strip()
    return value


def detect_doc_type(text: str) -> str:
    # the document title is the first non-empty line on txt/pdf/docx renders
    for line in text.splitlines():
        if line.strip():
            first = line.strip().upper()
            break
    else:
        return "unknown"
    if first.startswith("COMMERCIAL INVOICE"):
        return "invoice"
    if first.startswith("PACKING LIST"):
        return "packing_list"
    if first.startswith("CERTIFICATE OF ORIGIN"):
        return "coo"
    if first.startswith(("BILL OF LADING INSTRUCTION", "BL INSTRUCTION", "SHIPPING INSTRUCTION")):
        return "SI"
    if first.startswith("BILL OF LADING"):
        return "BL"
    # fallback: explicit self-labelling markers anywhere (e.g. "*** THIS IS A
    # COMMERCIAL INVOICE - NOT A SHIPPING INSTRUCTION ***")
    up = text.upper()
    if "NOT A SHIPPING INSTRUCTION" in up or "COMMERCIAL INVOICE" in up:
        return "invoice"
    if "PACKING LIST" in up:
        return "packing_list"
    if "CERTIFICATE OF ORIGIN" in up or "NOT AN SI OR BL" in up:
        return "coo"
    head = text[:600].upper()
    if "SHIPPING INSTRUCTION" in head or "BILL OF LADING INSTRUCTION" in head or "BL INSTRUCTION" in head:
        return "SI"
    if "BILL OF LADING" in head:
        return "BL"
    return "unknown"


def extract_fields(text: str) -> dict:
    """Extract the 7 compare fields. Returns {fields, raw, missing_fields}."""
    raw = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if ":" in line:
            label, _, value = line.partition(":")
            field = _LABEL2FIELD.get(_norm_label(label))
            if field and value.strip():
                raw.setdefault(field, _clean_value(field, value))
        else:
            field = _LABEL2FIELD.get(_norm_label(line))
            if field in BLOCK_VALUE_FIELDS:
                for nxt in lines[i + 1 : i + 4]:
                    if nxt.strip():
                        raw.setdefault(field, _clean_value(field, nxt))
                        break

    fields, missing = {}, []
    for f in COMPARE_FIELDS:
        v = raw.get(f)
        is_blank = v is None or v.strip().upper() in BLANK_TOKENS or (
            f in NUMERIC_FIELDS and _parse_number(v) is None
        )
        if is_blank:
            if v is not None:
                missing.append(f)
            fields[f] = None
        else:
            fields[f] = _parse_number(v) if f in NUMERIC_FIELDS else v
    return {"fields": fields, "raw": raw, "missing_fields": missing}
