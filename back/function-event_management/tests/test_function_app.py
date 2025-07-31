import pytest
from unittest.mock import MagicMock, patch
import function_app
import os

@pytest.fixture
def mock_db(monkeypatch):
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "get_db_connection", lambda: mock_conn)
    return mock_cursor

def test_create_event_success(monkeypatch):
    mock_cursor = MagicMock()
    mock_cursor.lastrowid = 123  # ← 追加
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "get_db_connection", lambda: mock_conn)
    monkeypatch.setattr(function_app, "parse_multipart", lambda req: ({
        "title": "テストイベント",
        "date": "2025-01-01T10:00",
        "location": "東京",
        "category": "1",
        "keywords": ["1", "2"],
        "summary": "概要",
        "detail": "詳細",
        "deadline": "2024-12-31T23:59",
        "creator": "0738",
        "is_draft": 0,
        "max_participants": "10",
        "image": None
    }, None))
    req = MagicMock()
    resp = function_app.create_event(req)
    assert resp.status_code == 200
    assert "イベント登録完了" in resp.get_body().decode("utf-8")

def test_create_event_missing_required(monkeypatch):
    monkeypatch.setattr(function_app, "parse_multipart", lambda req: ({
        "title": "",
        "date": "",
        "location": "",
        "category": "",
        "keywords": [],
        "summary": "",
        "detail": "",
        "deadline": "",
        "creator": "",
        "is_draft": 0
    }, None))
    req = MagicMock()
    resp = function_app.create_event(req)
    assert resp.status_code == 400

def test_delete_event_not_found(monkeypatch):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "get_db_connection", lambda: mock_conn)
    req = MagicMock()
    req.route_params = {"event_id": "999"}
    req.get_json.return_value = {"creator": "0738"}
    resp = function_app.delete_event(req)
    assert resp.status_code == 404

def test_delete_event_forbidden(monkeypatch):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = MagicMock(creator="9999")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "get_db_connection", lambda: mock_conn)
    req = MagicMock()
    req.route_params = {"event_id": "1"}
    req.get_json.return_value = {"creator": "0738"}
    resp = function_app.delete_event(req)
    assert resp.status_code == 403

def test_get_participants_success(monkeypatch):
    os.environ["CONNECTION_STRING"] = "dummy"
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("l_name",), ("f_name",), ("email",)]
    mock_cursor.fetchall.return_value = [
        (1, "山田", "太郎", "taro@example.com"),
        (2, "佐藤", "花子", "hanako@example.com")
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "pyodbc", MagicMock(connect=lambda *a, **kw: mock_conn))
    req = MagicMock()
    req.params = {"event_id": "1"}
    resp = function_app.get_participants(req)
    assert resp.status_code == 200
    body = resp.get_body().decode("utf-8")
    assert "山田" in body or "太郎" in body

def test_get_participants_no_event_id():
    req = MagicMock()
    req.params = {}
    resp = function_app.get_participants(req)
    assert resp.status_code == 400

def test_update_event_not_found(monkeypatch):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "get_db_connection", lambda: mock_conn)
    req = MagicMock()
    req.route_params = {"event_id": "999"}
    req.headers = {}
    req.get_json.return_value = {"creator": "0738"}
    resp = function_app.update_event(req)
    assert resp.status_code == 404

def test_update_event_forbidden(monkeypatch):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = MagicMock(creator="9999")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(function_app, "get_db_connection", lambda: mock_conn)
    req = MagicMock()
    req.route_params = {"event_id": "1"}
    req.headers = {}
    req.get_json.return_value = {"creator": "0738"}
    resp = function_app.update_event(req)
    assert resp.status_code == 403

def test_get_event_detail_no_id():
    req = MagicMock()
    req.params = {}
    resp = function_app.get_event_detail(req)
    assert resp.status_code == 400

def test_get_event_detail_invalid_id():
    req = MagicMock()
    req.params = {"event_id": "abc"}
    resp = function_app.get_event_detail(req)
    assert resp.status_code == 400