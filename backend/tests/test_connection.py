# backend/tests/test_connection.py
"""Tests for database connection utilities and safety guards."""

import builtins
import types
from unittest import mock

import pytest

# Import the module after monkeypatching config values.

@pytest.fixture
def dummy_psycopg():
    class DummyCursor:
        def __init__(self):
            self.commands = []
        def execute(self, sql, params=None):
            self.commands.append((sql, params))
        def fetchone(self):
            return ("dummy_id",)
        def close(self):
            pass
    class DummyConn:
        def __init__(self):
            self.closed = False
            self.cur = DummyCursor()
        def cursor(self):
            return self.cur
        def commit(self):
            pass
        def rollback(self):
            pass
        def close(self):
            self.closed = True
    return types.SimpleNamespace(connect=mock.Mock(return_value=DummyConn()))

def test_target_connection_guard(monkeypatch, dummy_psycopg):
    # Patch psycopg in the module
    import importlib
    conn_mod = importlib.import_module('backend.app.db.connection')
    monkeypatch.setattr(conn_mod, 'psycopg', dummy_psycopg)
    # Set config values – equivalent URLs with different query params
    monkeypatch.setattr(conn_mod.config, 'PROJECT_DATABASE_URL', 'postgresql://user:pass@localhost:5432/project_db')
    monkeypatch.setattr(conn_mod.config, 'TARGET_DATABASE_URL', 'postgresql://user:pass@localhost:5432/project_db?sslmode=require')
    with pytest.raises(RuntimeError) as exc:
        with conn_mod.get_target_connection():
            pass
    assert 'must not refer to the same database' in str(exc.value)

def test_target_connection_success(monkeypatch, dummy_psycopg):
    conn_mod = __import__('backend.app.db.connection', fromlist=['*'])
    monkeypatch.setattr(conn_mod, 'psycopg', dummy_psycopg)
    monkeypatch.setattr(conn_mod.config, 'PROJECT_DATABASE_URL', 'postgresql://user@localhost/project')
    monkeypatch.setattr(conn_mod.config, 'TARGET_DATABASE_URL', 'postgresql://user@localhost/target')
    with conn_mod.get_target_connection() as conn:
        assert not conn.closed
        # Verify read‑only settings were executed
        cur = conn.cursor()
        executed_sql = [cmd[0] for cmd in cur.commands]
        assert "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY" in executed_sql[0]
        assert "SET statement_timeout = 30000" in executed_sql[1]
