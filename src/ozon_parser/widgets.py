"""
Ozon Composer JSON & HTML `data-state` widget parsers (`ozon_parser.widgets`).

Handles:
- `webStickyProducts-*`, `webPrice-*`, `webCharacteristics-*`, `webDetailDescription-*`, `webGallery-*`, `webBrand-*`
- Seller info modal `textBlock-*` & `cellList-*` (company, INN, orders, working time, rating, reviews)
- Search / category / seller catalog grids (`searchResultsV2-*`, `tileGrid*`)
- Product buyer reviews (`webListReviews-*`, `webReviewProductScore-*`, `webAspects-*`, HTML `data-state`)
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ozon_parser.endpoints import (
    OZON_BASE_URL,
    clean_company_name,
    extract_inn,
    extract_seller_id,
    extract_sku,
    parse_price_number,
)
from ozon_parser.models import OzonProduct, OzonReviewItem, SellerInfo

_UNWANTED_SELLER_PHRASES = (
    "о магазине",
    "оригинальные товары",
    "premium магазин",
    "понятно",
    "заказов",
    "работает с ozon",
    "средняя оценка",
    "количество отзывов",
    "это крупный магазин",
)
_LEGAL_FORMS = ("ООО", "ИП", "АО", "ЗАО", "ПАО", "Ltd", "LLC", "Inc", "Co")
_WORK_SCHEDULE_KEYWORDS = ("график", "работает", "согласно", "ozon", "время")


def _decode_json_value(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def extract_widget_states(payload: Any) -> Dict[str, Dict[str, Any]]:
    """
    Extract and decode Ozon `widgetStates` dictionary from composer JSON OR HTML `data-state` tags.
    """
    decoded: Dict[str, Dict[str, Any]] = {}
    if isinstance(payload, dict):
        raw_states = payload.get("widgetStates") or payload
        if isinstance(raw_states, dict):
            for key, val in raw_states.items():
                parsed = _decode_json_value(val)
                if parsed is not None:
                    decoded[str(key)] = parsed
        return decoded

    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith("{"):
            parsed_root = _decode_json_value(stripped)
            if parsed_root is not None:
                return extract_widget_states(parsed_root)

        # HTML `<div id="state-webListReviews-..." data-state="...">` fallback
        pattern = re.compile(r'id=["\']state-([^"\']+)["\'][^>]*data-state=["\']([^"\']+)["\']', re.DOTALL)
        for match in pattern.finditer(payload):
            w_key = match.group(1)
            raw_json = html.unescape(match.group(2))
            parsed = _decode_json_value(raw_json)
            if parsed is not None:
                decoded[w_key] = parsed
    return decoded


def _find_widget(states: Dict[str, Dict[str, Any]], prefix: str) -> Optional[Dict[str, Any]]:
    for key, val in states.items():
        if key.startswith(prefix):
            return val
    return None


def _extract_seller_from_text_block(block: Dict[str, Any]) -> Tuple[str, str]:
    body = block.get("body")
    if not isinstance(body, list):
        return "", ""
    texts: List[str] = []
    for item in body:
        if isinstance(item, dict) and item.get("type") == "textAtom":
            txt = ((item.get("textAtom") or {}).get("text") or "").strip()
            if txt:
                texts.append(txt)
    if not texts:
        return "", ""

    company = clean_company_name(texts[0])
    inn = ""
    for t in texts:
        found = extract_inn(t)
        if found:
            inn = found
            break
    return company, inn


def _score_seller_text_block(company: str, inn: str, block: Dict[str, Any]) -> int:
    score = 0
    if company:
        score += 10
    if inn:
        score += 15
    lowered = company.lower()
    for phrase in _UNWANTED_SELLER_PHRASES:
        if phrase in lowered:
            score -= 20
    if company:
        if any(form in company for form in _LEGAL_FORMS):
            score += 5
        if any(q in company for q in ('"', "«", "»")):
            score += 3
        if 5 <= len(company.strip()) <= 100:
            score += 2
    body = block.get("body")
    if isinstance(body, list):
        atoms = [i for i in body if isinstance(i, dict) and i.get("type") == "textAtom"]
        if len(atoms) == 2:
            t1 = ((atoms[0].get("textAtom") or {}).get("text") or "").lower()
            t2 = ((atoms[1].get("textAtom") or {}).get("text") or "").lower()
            if any(k in t2 for k in _WORK_SCHEDULE_KEYWORDS):
                score += 8
            if t1 and not any(p in t1 for p in _UNWANTED_SELLER_PHRASES):
                score += 5
    return score


def parse_seller_modal(payload: Any, seller_id: int) -> SellerInfo:
    """Parse Ozon `/modal/shop-in-shop-info?seller_id=...` payload into `SellerInfo`."""
    states = extract_widget_states(payload)
    best_company, best_inn, best_score = "", "", -999
    fallback_candidates: List[Tuple[int, str, str]] = []

    for key, block in states.items():
        if not key.startswith("textBlock-"):
            continue
        company, inn = _extract_seller_from_text_block(block)
        if not (company or inn):
            continue
        score = _score_seller_text_block(company, inn, block)
        if score > best_score:
            best_company, best_inn, best_score = company, inn, score
        pos_m = re.search(r"textBlock-(\d+)", key)
        if pos_m and company:
            fallback_candidates.append((int(pos_m.group(1)), company, inn))

    if best_score <= 0 and fallback_candidates:
        fallback_candidates.sort(key=lambda x: x[0])
        for _, comp, inn in fallback_candidates:
            if not any(p in comp.lower() for p in ("о магазине", "оригинальные товары", "premium")):
                best_company, best_inn = comp, inn
                break

    orders_count = ""
    working_time = ""
    average_rating = ""
    reviews_count = ""

    for key, cell_block in states.items():
        if not key.startswith("cellList-"):
            continue
        cells = cell_block.get("cells")
        if not isinstance(cells, list):
            continue
        for cell in cells:
            ds_cell = cell.get("dsCell") if isinstance(cell, dict) else None
            if not isinstance(ds_cell, dict):
                continue
            title = (
                ((ds_cell.get("centerBlock") or {}).get("title") or {}).get("text") or ""
            ).lower()
            value = str(((ds_cell.get("rightBlock") or {}).get("badge") or {}).get("text") or "").strip()
            if "заказов" in title:
                orders_count = value
            elif "работает с ozon" in title:
                working_time = value
            elif "средняя оценка" in title:
                average_rating = value
            elif "количество отзывов" in title:
                reviews_count = value
        if any((orders_count, working_time, average_rating, reviews_count)):
            break

    return SellerInfo(
        seller_id=seller_id,
        name=best_company,
        company_name=best_company,
        inn=best_inn,
        orders_count=orders_count,
        working_time=working_time,
        average_rating=average_rating,
        reviews_count=reviews_count,
    )


def parse_product_composer(payload: Any, sku: int = 0) -> OzonProduct:
    """Parse Ozon `/product/...` Composer v2 JSON payload into `OzonProduct`."""
    states = extract_widget_states(payload)
    sticky = _find_widget(states, "webStickyProducts-") or {}
    price_widget = _find_widget(states, "webPrice-") or {}
    heading = _find_widget(states, "webProductHeading-") or {}
    chars = _find_widget(states, "webCharacteristics-") or {}
    desc_w = _find_widget(states, "webDetailDescription-") or {}
    gallery = _find_widget(states, "webGallery-") or {}
    score_w = _find_widget(states, "webReviewProductScore-") or {}
    brand_w = _find_widget(states, "webBrand-") or {}

    resolved_sku = sku or int(sticky.get("id") or 0)
    name = str(sticky.get("name") or heading.get("title") or "").strip()
    cover = str(sticky.get("coverImageUrl") or gallery.get("coverImage") or "").strip()

    images: List[str] = []
    if cover:
        images.append(cover)
    for img_entry in (gallery.get("images") or []):
        src = img_entry.get("src") if isinstance(img_entry, dict) else img_entry
        if isinstance(src, str) and src.startswith("http") and src not in images:
            images.append(src)

    seller = sticky.get("seller") or {}
    seller_name = clean_company_name(seller.get("name") or "")
    seller_inn = extract_inn(seller.get("inn") or "")
    seller_link = str(seller.get("link") or "").strip()
    seller_id = extract_seller_id(seller_link) or 0

    if not seller_id and states:
        raw_dump = json.dumps(states, ensure_ascii=False)
        m = re.search(r"/seller/(?:[^/\"']*-)?(\d+)/?", raw_dump)
        if m:
            seller_id = int(m.group(1))

    card_price = parse_price_number(price_widget.get("cardPrice"))
    price = parse_price_number(price_widget.get("price"))
    original_price = parse_price_number(price_widget.get("originalPrice"))
    in_stock = bool(price_widget.get("isAvailable", True))

    specs: Dict[str, str] = {}
    for block_name in ("characteristics", "short"):
        groups = chars.get(block_name)
        if not isinstance(groups, list):
            continue
        for grp in groups:
            if not isinstance(grp, dict):
                continue
            iter_items = grp.get("short") or grp.get("long") or ([grp] if "values" in grp else [])
            for spec_item in iter_items:
                if not isinstance(spec_item, dict):
                    continue
                k = str(spec_item.get("name") or spec_item.get("key") or "").strip()
                vals = spec_item.get("values") or []
                v_parts = [
                    str(v.get("text") if isinstance(v, dict) else v).strip()
                    for v in vals
                    if v
                ]
                if k and v_parts:
                    specs[k] = ", ".join(v_parts)

    description = str(desc_w.get("richAnnotation") or desc_w.get("description") or "").strip()
    brand = str(brand_w.get("name") or specs.get("Бренд") or "").strip()

    try:
        rating = float(str(score_w.get("totalScore") or score_w.get("score") or 0).replace(",", "."))
    except ValueError:
        rating = 0.0
    reviews_count = int(score_w.get("reviewsCount") or score_w.get("count") or 0)

    return OzonProduct(
        id=resolved_sku,
        name=name,
        brand=brand,
        description=description,
        price=price,
        card_price=card_price if card_price > 0 else None,
        original_price=original_price,
        rating=rating,
        reviews_count=reviews_count,
        in_stock=in_stock,
        seller_id=seller_id,
        seller_name=seller_name,
        company_name=seller_name,
        company_inn=seller_inn,
        seller_link=f"{OZON_BASE_URL}/seller/{seller_id}/" if seller_id else "",
        image_url=cover,
        image_links=images,
        specs=specs,
    )


def _extract_grid_item(item: Dict[str, Any]) -> Optional[OzonProduct]:
    link = str(((item.get("action") or {}).get("link") or item.get("link") or "")).strip()
    raw_sku = item.get("skuId") or item.get("id")
    sku = 0
    if raw_sku and str(raw_sku).isdigit():
        sku = int(raw_sku)
    elif link:
        try:
            sku = extract_sku(link)
        except Exception:
            sku = 0
    if sku <= 0:
        return None

    name = str(item.get("title") or item.get("name") or "").strip()
    price = parse_price_number(item.get("price"))
    card_price = parse_price_number(item.get("cardPrice"))
    orig_price = parse_price_number(item.get("originalPrice"))
    rating = 0.0
    reviews_count = 0
    seller_id = int(item.get("sellerId") or 0)
    seller_name = str(item.get("sellerName") or "")

    for state in item.get("mainState") or []:
        if not isinstance(state, dict):
            continue
        stype = state.get("type") or state.get("id") or ""
        atom = state.get("atom") if isinstance(state.get("atom"), dict) else state
        atom_type = atom.get("type") or stype

        if stype == "priceV2" or atom_type == "priceV2":
            p_obj = atom.get("priceV2") or atom.get("price") or atom
            if isinstance(p_obj, dict):
                price_list = p_obj.get("price") or []
                if isinstance(price_list, list):
                    vals = [parse_price_number(entry.get("text")) for entry in price_list if isinstance(entry, dict)]
                    vals = [v for v in vals if v > 0]
                    if vals and price <= 0:
                        price = vals[0]
                    if len(vals) > 1 and orig_price <= 0:
                        orig_price = max(vals)
                if not price:
                    price = parse_price_number(p_obj.get("current"))
                if not card_price:
                    card_price = parse_price_number(p_obj.get("cardPrice"))
                if not orig_price:
                    orig_price = parse_price_number(p_obj.get("original"))
        elif state.get("id") == "name" or (atom_type == "textAtom" and not name):
            txt = ((atom.get("textAtom") or {}).get("text") or atom.get("text") or "").strip()
            if txt and len(txt) > len(name):
                name = txt
        elif atom_type == "labelList":
            for lbl in ((atom.get("labelList") or {}).get("items") or []):
                title = str(lbl.get("title") or "").strip()
                if not title:
                    continue
                if re.match(r"^\d(?:[.,]\d)?$", title) and rating == 0.0:
                    rating = float(title.replace(",", "."))
                m_rev = re.search(r"(\d[\d\s\xa0]*)\s+отзыв", title.lower())
                if m_rev and reviews_count == 0:
                    reviews_count = int(re.sub(r"\s+", "", m_rev.group(1)))

    images: List[str] = []
    for t_img in ((item.get("tileImage") or {}).get("items") or []):
        img_link = ((t_img.get("image") or {}).get("link") or "").strip()
        if img_link and img_link not in images:
            images.append(img_link)
    if item.get("image") and item["image"] not in images:
        images.append(str(item["image"]))

    full_url = f"{OZON_BASE_URL}{link.split('?')[0]}" if link.startswith("/") else (link or f"{OZON_BASE_URL}/product/{sku}/")

    return OzonProduct(
        id=sku,
        name=name,
        price=price,
        card_price=card_price if card_price > 0 else None,
        original_price=orig_price,
        rating=rating,
        reviews_count=reviews_count,
        seller_id=seller_id,
        seller_name=seller_name,
        company_name=seller_name,
        url=full_url,
        image_url=images[0] if images else "",
        image_links=images,
    )


def parse_catalog_composer(payload: Any) -> Tuple[List[OzonProduct], Optional[str]]:
    """
    Parse Ozon search, category, or seller catalog composer payload.
    Returns `(products, next_page_relative_url)`.
    """
    states = extract_widget_states(payload)
    products: List[OzonProduct] = []
    seen_skus: set = set()
    next_page: Optional[str] = None

    if isinstance(payload, dict) and isinstance(payload.get("nextPage"), str):
        next_page = payload["nextPage"]

    for key, w in states.items():
        if key.startswith(("searchResultsV2-", "tileGrid")):
            for raw_item in (w.get("items") or []):
                if isinstance(raw_item, dict):
                    prod = _extract_grid_item(raw_item)
                    if prod and prod.id not in seen_skus:
                        seen_skus.add(prod.id)
                        products.append(prod)
        elif key.startswith("paginator-") and not next_page:
            np_val = w.get("nextPage") or ((w.get("nextButton") or {}).get("link"))
            if isinstance(np_val, str) and np_val.strip():
                next_page = np_val.strip()

    return products, next_page


def _format_timestamp(ts: Any) -> str:
    if isinstance(ts, (int, float)) and ts > 1_000_000_000:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except Exception:
            return str(ts)
    return str(ts or "").strip()


def parse_reviews_composer(
    payload: Any,
    sku: int = 0,
) -> Tuple[List[OzonReviewItem], float, int, Optional[str], List[str]]:
    """
    Parse Ozon product reviews from `webListReviews-*`, `webReviewProductScore-*`, `webAspects-*`.
    Returns `(reviews, avg_rating, total_count, next_page_relative_url, aspect_tags)`.
    """
    states = extract_widget_states(payload)
    reviews_w = _find_widget(states, "webListReviews-") or {}
    score_w = _find_widget(states, "webReviewProductScore-") or {}
    aspects_w = _find_widget(states, "webAspects-") or {}

    try:
        avg_rating = float(str(score_w.get("totalScore") or score_w.get("score") or 0).replace(",", "."))
    except ValueError:
        avg_rating = 0.0
    total_count = int(score_w.get("reviewsCount") or score_w.get("count") or 0)

    aspects_tags: List[str] = []
    for asp in (aspects_w.get("aspects") or aspects_w.get("items") or []):
        if isinstance(asp, dict):
            label = str(asp.get("name") or asp.get("title") or "").strip()
            if label and label not in aspects_tags:
                aspects_tags.append(label)

    items: List[OzonReviewItem] = []
    for raw in (reviews_w.get("reviews") or []):
        if not isinstance(raw, dict):
            continue
        content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
        score = int(content.get("score") or content.get("rating") or raw.get("rating") or 5)
        comment = str(content.get("comment") or content.get("text") or "").strip()
        pros = str(content.get("positive") or content.get("pros") or "").strip()
        cons = str(content.get("negative") or content.get("cons") or "").strip()

        if not any((comment, pros, cons)):
            continue

        photos: List[str] = []
        for ph in (content.get("photos") or []):
            url = ph.get("url") if isinstance(ph, dict) else ph
            if isinstance(url, str) and url.strip():
                photos.append(url.strip())

        usefulness = raw.get("usefulness") or {}
        author_obj = raw.get("author") or {}
        author_name = (
            str(author_obj.get("firstName") or author_obj.get("name") or "")
            if isinstance(author_obj, dict)
            else str(author_obj or "")
        ).strip()

        reply_obj = raw.get("reply") or raw.get("sellerComment") or {}
        reply_text = (
            str(reply_obj.get("text") or reply_obj.get("comment") or "").strip()
            if isinstance(reply_obj, dict)
            else ""
        )

        item_sku = int(raw.get("itemId") or raw.get("skuId") or sku or 0)
        items.append(
            OzonReviewItem(
                id=str(raw.get("id") or raw.get("uuid") or ""),
                sku=item_sku,
                author=author_name,
                rating=min(5, max(1, score)),
                comment=comment,
                pros=pros,
                cons=cons,
                created_at=_format_timestamp(raw.get("createdAt") or raw.get("publishedAt")),
                variant_text=str(raw.get("variantText") or content.get("variant") or "").strip(),
                photos=photos,
                useful_count=int(usefulness.get("useful") or raw.get("usefulCount") or 0),
                unuseful_count=int(usefulness.get("unuseful") or raw.get("unusefulCount") or 0),
                has_reply=bool(reply_text or raw.get("hasReply")),
                reply_text=reply_text,
            )
        )

    paging = reviews_w.get("paging") or {}
    next_page = paging.get("nextPage") or ((paging.get("nextButton") or {}).get("link"))
    if isinstance(next_page, str):
        next_page = next_page.strip() or None
    else:
        next_page = None
    if total_count == 0 and paging.get("total"):
        total_count = int(paging["total"])

    return items, avg_rating, total_count, next_page, aspects_tags
