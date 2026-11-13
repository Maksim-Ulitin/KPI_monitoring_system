import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "kpi.sqlite3"


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS data_rows (
            dataset_id INTEGER NOT NULL REFERENCES datasets(id),
            row_number INTEGER NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (dataset_id, row_number)
        );
        CREATE TABLE IF NOT EXISTS kpis (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            dataset_id INTEGER NOT NULL REFERENCES datasets(id),
            date_column TEXT NOT NULL,
            operation TEXT NOT NULL CHECK(operation IN ('sum', 'count', 'mean', 'percent')),
            value_column TEXT,
            filter_column TEXT,
            filter_value TEXT,
            percent_basis TEXT CHECK(percent_basis IN ('count', 'sum') OR percent_basis IS NULL),
            target REAL NOT NULL
        );
        """)


def list_datasets():
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM datasets ORDER BY id DESC")]


def add_dataset(filename, sha256, dataframe):
    """Save raw rows, preserving source types as JSON-serializable strings."""
    with connect() as db:
        existing = db.execute("SELECT id FROM datasets WHERE sha256=?", (sha256,)).fetchone()
        if existing:
            return existing["id"], False
        cur = db.execute("INSERT INTO datasets(filename, sha256, row_count) VALUES(?,?,?)",
                         (filename, sha256, len(dataframe)))
        dataset_id = cur.lastrowid
        records = dataframe.where(dataframe.notna(), None).to_dict(orient="records")
        db.executemany(
            "INSERT INTO data_rows(dataset_id,row_number,payload) VALUES(?,?,?)",
            [(dataset_id, idx, json.dumps(rec, ensure_ascii=False, default=str))
             for idx, rec in enumerate(records)],
        )
    return dataset_id, True


def read_dataset(dataset_id):
    import pandas as pd
    with connect() as db:
        rows = db.execute("SELECT payload FROM data_rows WHERE dataset_id=? ORDER BY row_number",
                          (dataset_id,)).fetchall()
    return pd.DataFrame([json.loads(row["payload"]) for row in rows])


def list_kpis():
    with connect() as db:
        return [dict(row) for row in db.execute("""
            SELECT k.*, d.filename AS dataset_name FROM kpis k
            JOIN datasets d ON d.id = k.dataset_id ORDER BY k.id DESC
        """)]


def add_kpi(config):
    keys = ("name", "description", "unit", "dataset_id", "date_column", "operation",
            "value_column", "filter_column", "filter_value", "percent_basis", "target")
    with connect() as db:
        db.execute(f"INSERT INTO kpis ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                   [config.get(key) for key in keys])


def update_target(kpi_id, target):
    with connect() as db:
        db.execute("UPDATE kpis SET target=? WHERE id=?", (target, kpi_id))


def delete_kpi(kpi_id):
    with connect() as db:
        db.execute("DELETE FROM kpis WHERE id=?", (kpi_id,))


def delete_dataset(dataset_id):
    """Delete a dataset and its rows only when no KPI uses it."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM kpis WHERE dataset_id=? LIMIT 1", (dataset_id,)).fetchone():
            raise ValueError("Набор используется в KPI. Сначала удалите связанные показатели на вкладке «Мониторинг».")
        db.execute("DELETE FROM data_rows WHERE dataset_id=?", (dataset_id,))
        db.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
