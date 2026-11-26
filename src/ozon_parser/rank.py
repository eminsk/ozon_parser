"""
Ozon Search Position (Rank) Tracker (`ozon_parser.rank`).

Scans paginated Ozon search results (`1..max_pages`), locates target SKU position
(global rank + per-page slot), computes Ozon Card price, and logs historical deltas in SQLite.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

from ozon_parser._model import BaseModel, Field
from ozon_parser.endpoints import extract_sku

if TYPE_CHECKING:
    from ozon_parser.client import OzonClient

logger = logging.getLogger("ozon_parser.rank")


class RankResult(BaseModel):
    """Single keyword rank check snapshot for an Ozon product SKU."""

    sku: int
    query: str
    position: Optional[int] = None
    page: Optional[int] = None
    page_position: Optional[int] = None
    previous_position: Optional[int] = None
    rank_delta: Optional[int] = None
    title: str = ""
    price: float = 0.0
    card_price: Optional[float] = None
    total_scanned: int = 0
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OzonRankTracker:
    """Multi-page Ozon search rank checker with SQLite position history."""

    def __init__(
        self,
        client: "OzonClient",
        *,
        db_path: Union[str, Path] = "ozon_prices.db",
    ) -> None:
        self.client = client
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ozon_rank_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sku INTEGER NOT NULL,
                        query TEXT NOT NULL,
                        position INTEGER,
                        page INTEGER,
                        price REAL NOT NULL DEFAULT 0,
                        checked_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ozon_rank_sku_q ON ozon_rank_history(sku, query)"
                )

    def _get_previous_position(self, sku: int, query: str) -> Optional[int]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT position FROM ozon_rank_history
                    WHERE sku = ? AND query = ? AND position IS NOT NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    (sku, query),
                ).fetchone()
                return int(row["position"]) if row else None

    def _record_rank(self, res: RankResult) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO ozon_rank_history (sku, query, position, page, price, checked_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (res.sku, res.query, res.position, res.page, res.price, res.checked_at),
                )

    def check_rank(
        self,
        sku_or_url: Union[int, str],
        query: str,
        *,
        max_pages: int = 3,
        sort: str = "score",
    ) -> RankResult:
        """Scan `1..max_pages` search result pages for `sku_or_url` under `query`."""
        sku = extract_sku(sku_or_url)
        clean_query = query.strip()
        prev_pos = self._get_previous_position(sku, clean_query)

        scanned = 0
        next_page_path: Optional[str] = None
        for page in range(1, max(1, int(max_pages)) + 1):
            page_items, next_page_path = self.client.fetch_search_page(
                clean_query,
                page=page,
                sort=sort,
                next_page_path=next_page_path if page > 1 else None,
            )
            if not page_items:
                break

            for idx, item in enumerate(page_items, start=1):
                global_pos = scanned + idx
                if item.id == sku:
                    delta = (prev_pos - global_pos) if prev_pos is not None else None
                    res = RankResult(
                        sku=sku,
                        query=clean_query,
                        position=global_pos,
                        page=page,
                        page_position=idx,
                        previous_position=prev_pos,
                        rank_delta=delta,
                        title=item.name,
                        price=item.price,
                        card_price=item.card_price,
                        total_scanned=scanned + len(page_items),
                    )
                    self._record_rank(res)
                    return res

            scanned += len(page_items)
            if page > 1 and not next_page_path and len(page_items) == 0:
                break

        res = RankResult(
            sku=sku,
            query=clean_query,
            position=None,
            previous_position=prev_pos,
            rank_delta=None,
            total_scanned=scanned,
        )
        self._record_rank(res)
        return res

    def check_batch(
        self,
        pairs: Sequence[Tuple[Union[int, str], str]],
        *,
        max_pages: int = 3,
        sort: str = "score",
    ) -> List[RankResult]:
        """Run rank checks across a batch of `(sku_or_url, query)` pairs."""
        results: List[RankResult] = []
        for sku_or_url, query in pairs:
            if not str(query).strip():
                continue
            results.append(self.check_rank(sku_or_url, query, max_pages=max_pages, sort=sort))
        return results

    def get_history(self, sku: int, query: Optional[str] = None, limit: int = 50) -> List[RankResult]:
        """Retrieve historical rank checks from SQLite."""
        with self._lock:
            with self._connect() as conn:
                if query:
                    rows = conn.execute(
                        "SELECT * FROM ozon_rank_history WHERE sku = ? AND query = ? ORDER BY id DESC LIMIT ?",
                        (sku, query, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM ozon_rank_history WHERE sku = ? ORDER BY id DESC LIMIT ?",
                        (sku, limit),
                    ).fetchall()

        return [
            RankResult(
                sku=r["sku"],
                query=r["query"],
                position=r["position"],
                page=r["page"],
                price=r["price"],
                checked_at=r["checked_at"],
            )
            for r in rows
        ]
