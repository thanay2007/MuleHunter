"""DuckDB analytical store.

Division of labour, on purpose:

* **Polars** holds the hot path. Incident slicing, feature building and the
  solver all run against in-memory frames, because they run inside a request
  and a round trip through SQL would cost more than it saves.
* **DuckDB** is the analytical store. Anything that scans the whole dataset to
  produce a rollup -- the data overview, ring summaries, distribution tables --
  is a SQL query against `chakravyuh.duckdb`. That is what an embedded
  analytical database is for, and it keeps those queries out of Python loops.

The warehouse is built from the parquet artifacts, so it is a derived file and
never a source of truth. Delete it and `ensure_warehouse()` rebuilds it.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import duckdb

from app.config import settings

log = logging.getLogger(__name__)

# DuckDB connections are not thread-safe, and uvicorn serves requests from a
# thread pool. One lock around one shared connection is simpler and quite fast
# enough for rollup queries that take single-digit milliseconds.
_lock = threading.Lock()
_conn: duckdb.DuckDBPyConnection | None = None


class WarehouseMissingError(RuntimeError):
    """Raised when the parquet artifacts needed to build the warehouse are absent."""


def _sources() -> dict[str, Path]:
    return {
        "accounts": settings.accounts_path,
        "transactions": settings.transactions_path,
        "labels": settings.labels_path,
    }


def build_warehouse(force: bool = False) -> Path:
    """Create `data/chakravyuh.duckdb` from the parquet artifacts."""
    missing = [name for name, path in _sources().items() if not path.exists()]
    if missing:
        raise WarehouseMissingError(
            f"Missing parquet for {', '.join(missing)}. "
            "Run: python -m app.simulator.generator"
        )

    target = settings.duckdb_path
    if target.exists() and not force:
        return target

    close()
    target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(target))
    try:
        for table, path in _sources().items():
            con.execute(
                f"CREATE OR REPLACE TABLE {table} AS "
                f"SELECT * FROM read_parquet(?)",
                [str(path)],
            )

        # A denormalised account view is what almost every rollup actually
        # wants, and it keeps the join out of a dozen query strings.
        con.execute(
            """
            CREATE OR REPLACE VIEW account_facts AS
            SELECT a.*,
                   COALESCE(l.is_mule, FALSE)        AS is_mule,
                   COALESCE(l.ring_id, '')           AS ring_id,
                   COALESCE(l.layer_index, -1)       AS layer_index,
                   COALESCE(l.is_cashout_node, FALSE) AS is_cashout_node,
                   COALESCE(l.typology, '')          AS typology
            FROM accounts a
            LEFT JOIN labels l USING (account_id)
            """
        )
        con.execute(
            """
            CREATE OR REPLACE VIEW retail_accounts AS
            SELECT * FROM account_facts WHERE archetype <> 'exit_point'
            """
        )
    finally:
        con.close()

    log.info("built warehouse at %s", target)
    return target


def ensure_warehouse() -> Path:
    """Build the warehouse if it is not already on disk."""
    return build_warehouse(force=False)


def connect() -> duckdb.DuckDBPyConnection:
    """Shared read connection, built on first use."""
    global _conn
    if _conn is None:
        ensure_warehouse()
        _conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
    return _conn


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """Run a rollup query and return rows as dictionaries."""
    with _lock:
        con = connect()
        cursor = con.execute(sql, params or [])
        columns = [d[0] for d in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def scalar(sql: str, params: list[Any] | None = None) -> Any:
    rows = query(sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def main() -> None:
    logging.basicConfig(level="INFO", format="%(message)s")
    path = build_warehouse(force=True)
    tables = query("SELECT table_name FROM duckdb_tables() ORDER BY table_name")
    counts = {
        row["table_name"]: scalar(f"SELECT count(*) FROM {row['table_name']}")
        for row in tables
    }
    print(f"Built {path}")
    for name, count in counts.items():
        print(f"  {name:<14} {count:>10,}")


if __name__ == "__main__":
    main()
