"""
transaction_logging.py

Provides TransactionLogger class for structured, thread-safe logging of transactions
with optional in-memory buffering, rotating file output, JSON or plain text formats,
export utilities, simple querying and statistics.

Usage:
    from transaction_logging import TransactionLogger
    logger = TransactionLogger("transactions.log")
    logger.log({"id": 1, "amount": 9.99, "status": "completed"})
    logger.flush()  # ensure buffered entries are written

This module intentionally uses only the Python standard library.
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import logging.handlers
import os
import threading
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

__all__ = ["TransactionLogger"]


class TransactionLogger:
    """A thread-safe transaction logger.

    Features:
    - Writes logs as JSON lines or plain text to a rotating file.
    - Optional in-memory buffer with flush semantics.
    - Simple filtering and exporting (JSON/CSV).
    - Basic statistics (count, total, average for a numeric field).
    - Context manager support.

    Parameters
    - log_file: path to the log file
    - fmt: 'json' or 'text' (default: 'json')
    - max_bytes, backup_count: rotation settings
    - buffer_size: number of items to hold in memory before automatic flush (0 = disabled)
    - level: logging level name as string (DEBUG/INFO/etc.)
    - logger_name: optional base name for the internal logger (unique name used if not provided)
    """

    def __init__(
        self,
        log_file: str = "transactions.log",
        fmt: str = "json",
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        buffer_size: int = 0,
        level: str = "INFO",
        logger_name: Optional[str] = None,
    ) -> None:
        if fmt not in ("json", "text"):
            raise ValueError("fmt must be 'json' or 'text'")

        self.log_file = log_file
        self.fmt = fmt
        self.buffer_size = int(buffer_size)
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._id = uuid.uuid4().hex

        # Setup Python logger with rotating file handler
        name = logger_name or f"TransactionLogger-{self._id}"
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        self._logger.propagate = False

        # Normalize for reliable comparisons on all OSes
        desired_path = os.path.abspath(log_file)
        created_handler = None

        # Avoid adding duplicate handlers for the same file
        def _is_match(h: logging.Handler) -> bool:
            if not isinstance(h, logging.handlers.RotatingFileHandler):
                return False
            base = getattr(h, "baseFilename", "")
            if not base:
                return False
            return os.path.abspath(base) == desired_path

        if not any(_is_match(h) for h in self._logger.handlers):
            created_handler = logging.handlers.RotatingFileHandler(
                filename=desired_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            created_handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(created_handler)

        # Keep a reference for direct flushing
        if created_handler is not None:
            self._handler = created_handler
        else:
            # Find the already-attached matching handler
            match = next((h for h in self._logger.handlers if _is_match(h)), None)
            if match is None:
                # Fallback: any RotatingFileHandler, if present
                match = next((h for h in self._logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)), None)
            if match is None:
                raise RuntimeError("Failed to locate or create a RotatingFileHandler for the logger.")
            self._handler = match


    # Context manager support
    def __enter__(self) -> "TransactionLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.flush()
        finally:
            # Close handlers to release file descriptors
            with self._lock:
                for h in list(self._logger.handlers):
                    try:
                        h.flush()
                        h.close()
                    except Exception:
                        pass
                self._logger.handlers.clear()

    # Public API
    def log(self, transaction: Dict[str, Any], level: str = "INFO") -> None:
        """Log a transaction dict.

        The transaction is enriched with a timestamp (ISO 8601) and an internal id.
        If buffering is enabled, the entry is appended to memory and flushed when buffer_size is reached.
        """
        if not isinstance(transaction, dict):
            raise TypeError("transaction must be a dict")

        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": level.upper(),
            "transaction": transaction,
        }

        with self._lock:
            if self.buffer_size > 0:
                self._buffer.append(entry)
                if len(self._buffer) >= self.buffer_size:
                    self.flush()
            else:
                self._emit(entry)

    # Level convenience methods
    def debug(self, transaction: Dict[str, Any]) -> None:
        self.log(transaction, level="DEBUG")

    def info(self, transaction: Dict[str, Any]) -> None:
        self.log(transaction, level="INFO")

    def warning(self, transaction: Dict[str, Any]) -> None:
        self.log(transaction, level="WARNING")

    def error(self, transaction: Dict[str, Any]) -> None:
        self.log(transaction, level="ERROR")

    # Internal emit
    def _emit(self, entry: Dict[str, Any]) -> None:
        text = self._format_entry(entry)
        # Use the internal logger to write to the rotating file handler
        # We call .log with level number derived from textual level to retain semantics
        lvl = getattr(logging, entry.get("level", "INFO"), logging.INFO)
        # logger.log will call handler.emit and handler's formatter will return the message unchanged
        self._logger.log(lvl, text)
        # Attempt to flush handler so that content reaches disk promptly
        try:
            self._handler.flush()
        except Exception:
            pass

    def _format_entry(self, entry: Dict[str, Any]) -> str:
        if self.fmt == "json":
            # Ensure all values are JSON-serializable; fallback to str()
            def _safe(o: Any) -> Any:
                try:
                    json.dumps(o)
                    return o
                except Exception:
                    return str(o)

            safe_entry = {
                "timestamp": entry["timestamp"],
                "level": entry["level"],
                "transaction": {k: _safe(v) for k, v in entry["transaction"].items()},
            }
            return json.dumps(safe_entry, separators=(",", ":"))
        else:
            # Plain text simple representation
            return f"[{entry['timestamp']}] {entry['level']}: {entry['transaction']}"

    def flush(self) -> None:
        """Flush any buffered entries to the file.

        This writes all buffered entries using the same formatting as immediate logs.
        """
        with self._lock:
            if not self._buffer:
                return
            # Emit in insertion order
            for entry in self._buffer:
                try:
                    self._emit(entry)
                except Exception:
                    # Avoid stopping on single bad entry; continue
                    continue
            self._buffer.clear()

    def clear_buffer(self) -> None:
        """Clear the in-memory buffer without flushing."""
        with self._lock:
            self._buffer.clear()

    def export(self, path: str, fmt: str = "json") -> None:
        """Export logged transactions to a file.

        This will include buffered entries as well (they are flushed first) and then
        read the log file content to produce the requested export format.

        Supported fmt: 'json' (newline-delimited JSON) or 'csv'.

        Note: For large log files this reads the entire file into memory.
        """
        fmt = fmt.lower()
        if fmt not in ("json", "csv"):
            raise ValueError("fmt must be 'json' or 'csv'")

        # Ensure all buffered entries are on disk
        self.flush()

        # Read the log file and parse entries
        entries: List[Dict[str, Any]] = []
        try:
            with open(self.log_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    if self.fmt == "json":
                        try:
                            e = json.loads(line)
                            entries.append(e)
                        except Exception:
                            # Non-json line; try to create fallback entry
                            entries.append({"raw": line})
                    else:
                        # If original format is text we store raw lines
                        entries.append({"raw": line})
        except FileNotFoundError:
            # Nothing to export
            entries = []

        if fmt == "json":
            with open(path, "w", encoding="utf-8") as out:
                for e in entries:
                    out.write(json.dumps(e, separators=(",", ":")) + "\n")
        else:
            # CSV export: flatten top-level keys across transactions
            # Build header from union of transaction keys and top-level keys
            headers = set()
            rows: List[Dict[str, Any]] = []
            for e in entries:
                # If structure matches {timestamp, level, transaction}
                if isinstance(e, dict) and "transaction" in e and isinstance(e.get("transaction"), dict):
                    row = {k: v for k, v in e["transaction"].items()}
                    # include metadata
                    row["_timestamp"] = e.get("timestamp")
                    row["_level"] = e.get("level")
                else:
                    row = {"raw": str(e)}
                rows.append(row)
                headers.update(row.keys())

            headers_list = sorted(headers)
            with open(path, "w", encoding="utf-8", newline="") as outcsv:
                writer = csv.DictWriter(outcsv, fieldnames=headers_list)
                writer.writeheader()
                for r in rows:
                    # Convert non-scalar values to JSON strings for CSV
                    cleaned = {k: (json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int, float, type(None))) else v) for k, v in r.items()}
                    writer.writerow(cleaned)

    def query(self, predicate: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
        """Return list of log entries that match the predicate.

        The predicate receives the full parsed log entry (if readable as JSON) or a dict with 'raw'.
        This reads the log file and includes buffered entries.
        """
        self.flush()
        result: List[Dict[str, Any]] = []
        try:
            with open(self.log_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parsed: Dict[str, Any]
                    if self.fmt == "json":
                        try:
                            parsed = json.loads(line)
                        except Exception:
                            parsed = {"raw": line}
                    else:
                        parsed = {"raw": line}
                    try:
                        if predicate(parsed):
                            result.append(parsed)
                    except Exception:
                        # predicate failed for this entry, skip
                        continue
        except FileNotFoundError:
            return []
        return result

    # Convenience statistics methods
    def count(self, predicate: Optional[Callable[[Dict[str, Any]], bool]] = None) -> int:
        """Count entries optionally matching predicate."""
        if predicate is None:
            predicate = lambda e: True
        return len(self.query(predicate))

    def sum_field(self, field: str) -> float:
        """Sum numeric field from transaction dicts (ignores non-numeric or missing).

        Field should be a top-level key inside the `transaction` dict.
        """
        total = 0.0
        def pred(e: Dict[str, Any]) -> bool:
            return isinstance(e, dict) and "transaction" in e and isinstance(e["transaction"], dict) and field in e["transaction"]

        for e in self.query(pred):
            try:
                v = e["transaction"][field]
                total += float(v)
            except Exception:
                continue
        return total

    def avg_field(self, field: str) -> Optional[float]:
        """Average of numeric field from transaction dicts. Returns None if no values."""
        values = []
        def pred(e: Dict[str, Any]) -> bool:
            return isinstance(e, dict) and "transaction" in e and isinstance(e["transaction"], dict) and field in e["transaction"]

        for e in self.query(pred):
            try:
                values.append(float(e["transaction"][field]))
            except Exception:
                continue
        if not values:
            return None
        return sum(values) / len(values)

    # Utility
    def enable_console(self, enable: bool = True, level: Optional[str] = None) -> None:
        """Attach or detach a console (stream) handler for real-time output.

        If level is provided, sets the console handler to that level.
        """
        with self._lock:
            if enable:
                # Avoid adding multiple console handlers
                if not any(isinstance(h, logging.StreamHandler) for h in self._logger.handlers):
                    ch = logging.StreamHandler()
                    ch.setFormatter(logging.Formatter("%(message)s"))
                    if level:
                        ch.setLevel(getattr(logging, level.upper(), logging.INFO))
                    self._logger.addHandler(ch)
            else:
                for h in list(self._logger.handlers):
                    if isinstance(h, logging.StreamHandler):
                        try:
                            h.flush()
                            h.close()
                        except Exception:
                            pass
                        self._logger.removeHandler(h)

    def set_level(self, level: str) -> None:
        """Set the logging level for the internal logger (and handlers if present)."""
        lvl = getattr(logging, level.upper(), None)
        if lvl is None:
            raise ValueError("invalid logging level: %r" % (level,))
        with self._lock:
            self._logger.setLevel(lvl)
            for h in self._logger.handlers:
                try:
                    h.setLevel(lvl)
                except Exception:
                    continue