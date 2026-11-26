"""
Multi-format exporters for Ozon SDK Pro (`ozon_parser.export`):
Styled Excel (`.xlsx`), UTF-8 BOM CSV, JSON, JSONL, Reviews Excel, Rank Excel, and Pandas DataFrame.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Union

from ozon_parser.models import OzonProduct, OzonReviewSummary

if TYPE_CHECKING:
    from ozon_parser.rank import RankResult


def _excel_safe(value: Any) -> Any:
    """Prevent CSV/Excel formula injection on strings starting with =, +, -, @."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def to_json(products: List[OzonProduct], filepath: Union[str, Path], indent: int = 2) -> Path:
    """Export Ozon products to formatted UTF-8 JSON file."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([p.to_dict() for p in products], ensure_ascii=False, indent=indent), encoding="utf-8")
    return path


def to_jsonl(products: List[OzonProduct], filepath: Union[str, Path]) -> Path:
    """Export Ozon products to newline-delimited JSON Lines (`.jsonl`)."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in products:
            f.write(p.to_json() + "\n")
    return path


def to_csv(products: List[OzonProduct], filepath: Union[str, Path], delimiter: str = ";") -> Path:
    """Export Ozon products to UTF-8 BOM CSV for clean Excel import."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "sku",
        "name",
        "brand",
        "price",
        "card_price",
        "original_price",
        "discount_pct",
        "old_price",
        "price_drop",
        "rating",
        "reviews_count",
        "seller_id",
        "seller_name",
        "company_name",
        "company_inn",
        "url",
        "image_url",
        "specs",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        for p in products:
            writer.writerow(
                {
                    "sku": p.id,
                    "name": _excel_safe(p.name),
                    "brand": _excel_safe(p.brand),
                    "price": p.price,
                    "card_price": p.card_price if p.card_price is not None else "",
                    "original_price": p.original_price,
                    "discount_pct": p.discount,
                    "old_price": p.old_price if p.old_price is not None else "",
                    "price_drop": p.price_drop if p.price_drop is not None else "",
                    "rating": p.rating,
                    "reviews_count": p.reviews_count,
                    "seller_id": p.seller_id,
                    "seller_name": _excel_safe(p.seller_name),
                    "company_name": _excel_safe(p.company_name),
                    "company_inn": p.company_inn,
                    "url": p.url,
                    "image_url": p.image_url,
                    "specs": _excel_safe("; ".join(f"{k}: {v}" for k, v in p.specs.items())),
                }
            )
    return path


def to_excel(
    products: List[OzonProduct],
    filepath: Union[str, Path],
    sheet_name: str = "Ozon Catalog",
) -> Path:
    """Export Ozon products to styled `.xlsx` with Ozon Blue headers, clickable links, Ozon Card & seller INN."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:  # pragma: no cover
        return to_csv(products, path.with_suffix(".csv"))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    headers = [
        "Артикул (SKU)",
        "Название",
        "Бренд",
        "Цена (₽)",
        "Ozon Карта (₽)",
        "До скидки (₽)",
        "Скидка (%)",
        "Снижение цены (₽)",
        "Рейтинг",
        "Отзывы",
        "Продавец",
        "Компания",
        "ИНН",
        "ID продавца",
        "Ссылка Ozon",
        "Фото",
        "Характеристики",
    ]
    header_fill = PatternFill(start_color="005BFF", end_color="005BFF", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    drop_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    link_font = Font(color="2563EB", underline="single")

    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"

    for row_idx, p in enumerate(products, start=2):
        drop_val = p.price_drop if p.price_drop is not None else 0
        specs_str = "\n".join(f"{k}: {v}" for k, v in p.specs.items())
        ws.append(
            [
                p.id,
                _excel_safe(p.name),
                _excel_safe(p.brand),
                p.price,
                p.card_price if p.card_price is not None else "",
                p.original_price,
                p.discount,
                drop_val if drop_val > 0 else "",
                p.rating,
                p.reviews_count,
                _excel_safe(p.seller_name),
                _excel_safe(p.company_name),
                p.company_inn,
                p.seller_id or "",
                p.url,
                p.image_url,
                _excel_safe(specs_str),
            ]
        )
        if p.url:
            c = ws.cell(row=row_idx, column=15)
            c.hyperlink = p.url
            c.font = link_font
        if p.image_url:
            c = ws.cell(row=row_idx, column=16)
            c.hyperlink = p.image_url
            c.font = link_font
        if drop_val > 0:
            ws.cell(row=row_idx, column=4).fill = drop_fill
            ws.cell(row=row_idx, column=8).fill = drop_fill

    widths = {
        1: 15, 2: 42, 3: 16, 4: 13, 5: 15, 6: 13, 7: 11, 8: 16,
        9: 10, 10: 10, 11: 24, 12: 26, 13: 15, 14: 13, 15: 38, 16: 38, 17: 38,
    }
    for col_idx, w in widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    if products:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(products) + 1}"

    wb.save(path)
    return path


def reviews_to_excel(summary: OzonReviewSummary, filepath: Union[str, Path]) -> Path:
    """Export Ozon review summary (AI pros/cons + individual reviews) to `.xlsx`."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ozon Reviews"

    headers = ["SKU", "Оценка", "Автор", "Вариант", "Плюсы", "Минусы", "Комментарий", "Дата", "Полезно", "Фото", "Ответ продавца"]
    header_fill = PatternFill(start_color="005BFF", end_color="005BFF", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_idx)
        c.fill = header_fill
        c.font = header_font
    ws.freeze_panes = "A2"

    for r in summary.reviews:
        ws.append(
            [
                r.sku or summary.sku,
                r.rating,
                _excel_safe(r.author),
                _excel_safe(r.variant_text),
                _excel_safe(r.pros),
                _excel_safe(r.cons),
                _excel_safe(r.comment),
                r.created_at,
                r.useful_count,
                len(r.photos),
                _excel_safe(r.reply_text),
            ]
        )

    ws2 = wb.create_sheet("AI Summary")
    ws2.append(["Параметр", "Значение"])
    ws2.append(["SKU", summary.sku])
    ws2.append(["Товар", _excel_safe(summary.product_name)])
    ws2.append(["Средний рейтинг", summary.avg_rating])
    ws2.append(["Проанализировано / Всего", f"{summary.total_analyzed} / {summary.total_available}"])
    ws2.append(["Режим AI", summary.summary_mode])
    ws2.append([])
    ws2.append(["Главные плюсы", "Главные минусы"])
    max_rows = max(len(summary.top_pros), len(summary.top_cons))
    for i in range(max_rows):
        ws2.append(
            [
                _excel_safe(summary.top_pros[i]) if i < len(summary.top_pros) else "",
                _excel_safe(summary.top_cons[i]) if i < len(summary.top_cons) else "",
            ]
        )

    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 24 if col_idx in (5, 6, 7) else 14
    ws2.column_dimensions["A"].width = 45
    ws2.column_dimensions["B"].width = 45

    wb.save(path)
    return path


def rank_results_to_excel(results: List["RankResult"], filepath: Union[str, Path]) -> Path:
    """Export Ozon search rank checks to styled `.xlsx`."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ozon Rank Tracker"

    headers = [
        "SKU",
        "Запрос",
        "Позиция",
        "Страница",
        "Место на стр.",
        "Прошлая поз.",
        "Динамика",
        "Название",
        "Цена (₽)",
        "Ozon Карта (₽)",
        "Дата",
    ]
    header_fill = PatternFill(start_color="005BFF", end_color="005BFF", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_idx)
        c.fill = header_fill
        c.font = header_font
    ws.freeze_panes = "A2"

    for r in results:
        ws.append(
            [
                r.sku,
                _excel_safe(r.query),
                r.position if r.position is not None else "Не найден",
                r.page if r.page is not None else "",
                r.page_position if r.page_position is not None else "",
                r.previous_position if r.previous_position is not None else "",
                r.rank_delta if r.rank_delta is not None else "",
                _excel_safe(r.title),
                r.price,
                r.card_price if r.card_price is not None else "",
                r.checked_at,
            ]
        )

    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 32 if col_idx in (2, 8) else 14

    wb.save(path)
    return path


def to_dataframe(products: List[OzonProduct]) -> Any:
    """Convert `OzonProduct` list into a `pandas.DataFrame` (`uv add "ozon-sdk-pro[dataframe]"`)."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('pandas is required for to_dataframe(). Run: uv add "ozon-sdk-pro[dataframe]"') from exc
    return pd.DataFrame([p.to_dict() for p in products])
