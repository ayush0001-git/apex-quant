# apex-quant/src/apex/adapters/storage/sqlite_audit.py
"""SQLiteAuditAdapter: Immutable local audit logging for trade decisions."""
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Sequence, List, Mapping, Any
from ...domain.models import AuditRecord, Bar
from ...domain.enums import Timeframe
from ...ports.storage_port import StoragePort


class SQLiteAuditAdapter(StoragePort):
    """Persists immutable audit trails to local SQLite database with cryptographic chaining."""

    def __init__(self, db_path: Path | str = "apex_audit.db") -> None:
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    algo_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry REAL NOT NULL,
                    stop REAL NOT NULL,
                    status TEXT NOT NULL,
                    risk_reason TEXT,
                    net_rr REAL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT,
                    prev_hash TEXT
                )
                """
            )
            # Ensure columns exist if table was already created
            cursor = conn.execute("PRAGMA table_info(audit_logs)")
            cols = {row[1] for row in cursor.fetchall()}
            if "payload_hash" not in cols:
                conn.execute("ALTER TABLE audit_logs ADD COLUMN payload_hash TEXT")
            if "prev_hash" not in cols:
                conn.execute("ALTER TABLE audit_logs ADD COLUMN prev_hash TEXT")
            conn.commit()

    async def save_audit(self, record: AuditRecord) -> None:
        payload = {
            "audit_id": record.audit_id,
            "timestamp": record.timestamp_utc.isoformat(),
            "algo_id": record.algo_id,
            "symbol": record.symbol,
            "intent": {
                "direction": record.intent.direction.value,
                "entry": record.intent.entry,
                "stop": record.intent.stop,
                "targets": list(record.intent.targets),
                "conviction": record.intent.conviction,
                "spot_price": record.intent.feature_snapshot.spot_price,
            },
            "risk": {
                "status": record.risk.status.value,
                "reason": record.risk.reason,
                "kill_reason": record.risk.kill_reason.value,
                "position_size": record.risk.position_size,
                "net_rr_ratio": record.risk.net_rr_ratio,
                "estimated_friction": record.risk.estimated_statutory_friction,
            },
        }

        payload_str = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        with sqlite3.connect(self.db_path) as conn:
            # Chained previous hash for tamper-evident provenance (P1-11)
            cursor = conn.execute("SELECT payload_hash FROM audit_logs ORDER BY rowid DESC LIMIT 1")
            last_row = cursor.fetchone()
            prev_hash = last_row[0] if last_row and last_row[0] else "GENESIS_ROOT"

            conn.execute(
                """
                INSERT INTO audit_logs (
                    audit_id, timestamp_utc, algo_id, symbol, direction, entry, stop, status, risk_reason, net_rr, payload_json, payload_hash, prev_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.audit_id,
                    record.timestamp_utc.isoformat(),
                    record.algo_id,
                    record.symbol,
                    record.intent.direction.value,
                    record.intent.entry,
                    record.intent.stop,
                    record.risk.status.value,
                    record.risk.reason,
                    record.risk.net_rr_ratio,
                    payload_str,
                    payload_hash,
                    prev_hash,
                ),
            )
            conn.commit()

    async def load_history(
        self, symbol: str, timeframe: Timeframe, lookback: int
    ) -> Sequence[Bar]:
        return ()

    async def get_recent_logs(self, limit: int = 50) -> List[Mapping[str, Any]]:
        """Retrieve recent immutable audit records."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT audit_id, timestamp_utc, algo_id, symbol, direction, entry, stop, status, risk_reason, net_rr, payload_json
                FROM audit_logs
                ORDER BY timestamp_utc DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            logs = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    payload = {}
                logs.append({
                    "audit_id": row["audit_id"],
                    "timestamp_utc": row["timestamp_utc"],
                    "algo_id": row["algo_id"],
                    "symbol": row["symbol"],
                    "direction": row["direction"],
                    "entry": row["entry"],
                    "stop": row["stop"],
                    "status": row["status"],
                    "risk_reason": row["risk_reason"],
                    "net_rr": row["net_rr"],
                    "details": payload,
                })
            return logs
