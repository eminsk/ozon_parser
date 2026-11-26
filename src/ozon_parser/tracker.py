"""
SQLite Price Tracker for Ozon SDK Pro (`ozon_parser.tracker`).

Tracks regular and Ozon Card checkout prices across runs, updates `product.old_price`,
and queries historical drops.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from ozon_parser.models import OzonProduct, PriceRecord


class OzonPriceTracker:
    """Thread-safe SQLite price history and drop detector for Ozon products."""

    def __init__(self, db_path: Union[str, Path] = "ozon_prices.db") -> None:
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
                    CREATE TABLE IF NOT EXISTS ozon_latest_prices (
                        sku INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        price REAL NOT NULL,
                        card_price REAL,
                        original_price REAL NOT NULL DEFAULT 0,
                        old_price REAL,
                        discount INTEGER NOT NULL DEFAULT 0,
                        seller_id INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ozon_price_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sku INTEGER NOT NULL,
                        price REAL NOT NULL,
                        card_price REAL,
                        original_price REAL NOT NULL DEFAULT 0,
                        discount INTEGER NOT NULL DEFAULT 0,
                        recorded_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ozon_hist_sku ON ozon_price_history(sku)"
                )

    def track_products(self, products: List[OzonProduct]) -> List[OzonProduct]:
        """Update stored prices and mutate `product.old_price` if previous price differed."""
        if not products:
            return products

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                for p in products:
                    if p.price <= 0:
                        continue
                    row = conn.execute(
                        "SELECT price, old_price FROM ozon_latest_prices WHERE sku = ?",
                        (p.id,),
                    ).fetchone()

                    prev_price: Optional[float] = row["price"] if row else None
                    recorded_old: Optional[float] = row["old_price"] if row else None

                    if prev_price is not None and prev_price != p.price:
                        p.old_price = prev_price
                    elif recorded_old is not None and recorded_old != p.price:
                        p.old_price = recorded_old

                    conn.execute(
                        """
                        INSERT INTO ozon_latest_prices (
                            sku, name, price, card_price, original_price, old_price, discount, seller_id, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(sku) DO UPDATE SET
                            name = excluded.name,
                            old_price = CASE
                                WHEN ozon_latest_prices.price != excluded.price THEN ozon_latest_prices.price
                                ELSE ozon_latest_prices.old_price
                            END,
                            price = excluded.price,
                            card_price = excluded.card_price,
                            original_price = excluded.original_price,
                            discount = excluded.discount,
                            seller_id = CASE
                                WHEN excluded.seller_id > 0 THEN excluded.seller_id
                                ELSE ozon_latest_prices.seller_id
                            END,
                            updated_at = excluded.updated_at
                        """,
                        (
                            p.id,
                            p.name,
                            p.price,
                            p.card_price,
                            p.original_price,
                            p.old_price,
                            p.discount,
                            p.seller_id,
                            now,
                        ),
                    )

                    if prev_price is None or prev_price != p.price:
                        conn.execute(
                            """
                            INSERT INTO ozon_price_history (sku, price, card_price, original_price, discount, recorded_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (p.id, p.price, p.card_price, p.original_price, p.discount, now),
                        )
        return products

    def get_price_drops(self, limit: int = 100) -> List[PriceRecord]:
        """Return tracked products whose current price dropped below their previous `old_price`."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT sku, name, price, card_price, original_price, old_price, discount, seller_id, updated_at
                    FROM ozon_latest_prices
                    WHERE old_price IS NOT NULL AND old_price > price AND price > 0
                    ORDER BY (old_price - price) DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        return [
            PriceRecord(
                sku=r["sku"],
                name=r["name"],
                price=r["price"],
                card_price=r["card_price"],
                original_price=r["original_price"],
                old_price=r["old_price"],
                discount=r["discount"],
                seller_id=r["seller_id"],
                recorded_at=r["updated_at"],
            )
            for r in rows
        ]

    def get_history(self, sku: int) -> List[PriceRecord]:
        """Return chronological price snapshots for a given Ozon SKU."""
        with self._lock:
            with self._connect() as conn:
                meta = conn.execute(
                    "SELECT name, seller_id FROM ozon_latest_prices WHERE sku = ?",
                    (sku,),
                ).fetchone()
                name = meta["name"] if meta else str(sku)
                seller_id = meta["seller_id"] if meta else 0

                rows = conn.execute(
                    """
                    SELECT price, card_price, original_price, discount, recorded_at
                    FROM ozon_price_history
                    WHERE sku = ?
                    ORDER BY id ASC
                    """,
                    (sku,),
                ).fetchall()

        return [
            PriceRecord(
                sku=sku,
                name=name,
                price=r["price"],
                card_price=r["card_price"],
                original_price=r["original_price"],
                discount=r["discount"],
                seller_id=seller_id,
                recorded_at=r["recorded_at"],
            )
            for r in rows
        ]
