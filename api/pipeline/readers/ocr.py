"""Vision OCR path: render a scanned PDF to page images and let the VL model
read fields. Opt-in (ENABLE_VISION_OCR) — ground truth scores image-only docs
as `unreadable`, so this exists to demo capability without changing verdicts."""
import io

from ..extract import COMPARE_FIELDS


def render_pdf_images(path, max_pages=2) -> list[bytes]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    out = []
    for i in range(min(len(pdf), max_pages)):
        bitmap = pdf[i].render(scale=2).to_pil()
        buf = io.BytesIO()
        bitmap.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


_OCR_SYS = """Read this scanned shipping document page.
Reply with ONLY JSON:
{"doc_type": "SI"|"BL"|"invoice"|"packing_list"|"coo"|"unknown",
 "shipper": ..., "consignee": ..., "notify_party": ...,
 "port_of_loading": ..., "port_of_discharge": ...,
 "container_count": int|null, "gross_weight_kg": number|null}
Use null for anything not legible."""


def ocr_extract_fields(path) -> dict | None:
    """Vision-model extraction for image-only PDFs.
    Returns {"doc_type": ..., "fields": {7 canonical fields}} or None."""
    try:
        from app.services.llm import vision_json

        merged, doc_type = {}, None
        for png in render_pdf_images(path):
            r = vision_json(_OCR_SYS, png)
            doc_type = doc_type or r.get("doc_type")
            for k in COMPARE_FIELDS:
                if r.get(k) is not None and merged.get(k) is None:
                    merged[k] = r[k]
        if not merged:
            return None
        return {"doc_type": doc_type or "unknown",
                "fields": {k: merged.get(k) for k in COMPARE_FIELDS}}
    except Exception:
        return None
