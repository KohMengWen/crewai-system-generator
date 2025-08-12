import csv
import json
from pathlib import Path

import pytest

from transaction_logging import TransactionLogger


def _read_logged_entries(path: Path, fmt: str):
    entries = []
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if fmt == "json":
                try:
                    entries.append(json.loads(line))
                except Exception:
                    entries.append({"raw": line})
            else:
                entries.append({"raw": line})
    return entries


def test_invalid_format_raises():
    with pytest.raises(ValueError):
        TransactionLogger(fmt="xml")


def test_log_non_dict_raises(tmp_path):
    logf = tmp_path / "t1.log"
    logger = TransactionLogger(log_file=str(logf))
    with pytest.raises(TypeError):
        logger.log("not a dict")
    # cleanup handlers
    logger.__exit__(None, None, None)


def test_json_logging_and_basic_fields(tmp_path):
    logf = tmp_path / "t2.log"
    with TransactionLogger(log_file=str(logf), fmt="json") as logger:
        logger.log({"id": 1, "amount": 9.99})
    entries = _read_logged_entries(logf, "json")
    assert len(entries) == 1
    e = entries[0]
    assert "timestamp" in e and e["timestamp"].endswith("Z")
    assert e["level"] == "INFO"
    assert isinstance(e["transaction"], dict)
    assert e["transaction"]["id"] == 1
    # explicit close done by context manager


def test_buffering_triggers_flush(tmp_path):
    logf = tmp_path / "t3.log"
    with TransactionLogger(log_file=str(logf), fmt="json", buffer_size=2) as logger:
        logger.log({"id": "a"})
        # nothing should be written until buffer_size reached
        entries_before = _read_logged_entries(logf, "json")
        assert entries_before == []
        logger.log({"id": "b"})
        # buffer reached; should flush automatically
    entries = _read_logged_entries(logf, "json")
    assert len(entries) == 2
    ids = [e["transaction"]["id"] for e in entries]
    assert set(ids) == {"a", "b"}


def test_text_format_writes_plain_text(tmp_path):
    logf = tmp_path / "t4.log"
    with TransactionLogger(log_file=str(logf), fmt="text") as logger:
        logger.info({"k": "v"})
    entries = _read_logged_entries(logf, "text")
    assert len(entries) == 1
    raw = entries[0]["raw"]
    assert "INFO:" in raw
    assert "{'k': 'v'}" in raw or '"k": "v"' in raw


def test_export_json_and_csv(tmp_path):
    logf = tmp_path / "t5.log"
    out_json = tmp_path / "export.json"
    out_csv = tmp_path / "export.csv"

    with TransactionLogger(log_file=str(logf), fmt="json") as logger:
        logger.log({"a": 1, "amount": 2.5})
        logger.log({"b": "x", "amount": 3.5})

        # export json
        logger.export(str(out_json), fmt="json")
        # export csv
        logger.export(str(out_csv), fmt="csv")

    # Validate exported JSON
    with out_json.open("r", encoding="utf-8") as fh:
        lines = [json.loads(l) for l in fh.read().splitlines() if l.strip()]
    assert len(lines) >= 2
    # Validate CSV structure
    with out_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) >= 2
    # Ensure metadata columns exist
    assert any("_timestamp" in r for r in rows)


def test_count_sum_avg_and_query(tmp_path):
    logf = tmp_path / "t6.log"
    with TransactionLogger(log_file=str(logf), fmt="json") as logger:
        logger.log({"id": 1, "amount": 10, "status": "ok"})
        logger.log({"id": 2, "amount": 20, "status": "failed"})
        logger.log({"id": 3, "amount": "not-a-number", "status": "ok"})

    # Count all
    logger = TransactionLogger(log_file=str(logf), fmt="json")
    try:
        assert logger.count() == 3
        # Sum field should ignore non-numeric
        assert abs(logger.sum_field("amount") - 30.0) < 1e-6
        # Average should be computed over numeric values only
        avg = logger.avg_field("amount")
        assert abs(avg - 15.0) < 1e-6
        # Query for failed
        failed = logger.query(
            lambda e: isinstance(e, dict) and e.get("transaction", {}).get("status") == "failed"
        )
        assert len(failed) == 1
        assert failed[0]["transaction"]["id"] == 2
    finally:
        logger.__exit__(None, None, None)


def test_context_manager_flushes_and_closes(tmp_path):
    logf = tmp_path / "t7.log"
    with TransactionLogger(log_file=str(logf), fmt="json") as logger:
        logger.log({"x": 1})
    # After context exit, file should be present and readable
    entries = _read_logged_entries(logf, "json")
    assert len(entries) == 1


def test_enable_console_and_set_level(tmp_path):
    logf = tmp_path / "t8.log"
    logger = TransactionLogger(log_file=str(logf), fmt="json")
    try:
        # Enable console handler at DEBUG
        logger.enable_console(True, level="DEBUG")
        # Should not raise when disabling
        logger.enable_console(False)
        # Setting invalid level raises
        with pytest.raises(ValueError):
            logger.set_level("NO_SUCH_LEVEL")
        # Setting a valid level should not raise
        logger.set_level("DEBUG")
    finally:
        logger.__exit__(None, None, None)


def test_export_on_missing_file_creates_empty(tmp_path):
    # When log file does not exist, export should create an export file but contain no entries
    logf = tmp_path / "doesnotexist.log"
    out_json = tmp_path / "out_empty.json"
    logger = TransactionLogger(log_file=str(logf), fmt="json")
    try:
        # Ensure file is not present
        if logf.exists():
            logf.unlink()
        logger.export(str(out_json), fmt="json")
        # Export file should exist but be empty
        assert out_json.exists()
        with out_json.open("r", encoding="utf-8") as fh:
            content = fh.read().strip()
            assert content == ""
    finally:
        logger.__exit__(None, None, None)


def test_clear_buffer_without_flush(tmp_path):
    logf = tmp_path / "t9.log"
    logger = TransactionLogger(log_file=str(logf), fmt="json", buffer_size=10)
    try:
        logger.log({"id": 1})
        assert len(logger._buffer) == 1
        logger.clear_buffer()
        assert len(logger._buffer) == 0
        # Nothing written to disk
        assert _read_logged_entries(logf, "json") == []
    finally:
        logger.__exit__(None, None, None)
