import os
import sys
import types
import pytest
import json
from unittest.mock import patch, MagicMock
import function_app

# Import the function_app module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class DummyRequest:
    def __init__(self, method="GET", params=None, headers=None, body=None, route_params=None, json_data=None):
        self.method = method
        self.params = params or {}
        self.headers = headers or {}
        self._body = body
        self.route_params = route_params or {}
        self._json_data = json_data

    def get_body(self):
        return self._body or b""

    def get_json(self):
        if self._json_data is not None:
            return self._json_data
        raise Exception("No JSON data")

@pytest.fixture
def mock_db(monkeypatch):
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn   # ← 追加
    conn.__exit__.return_value = None    # ← 追加
    monkeypatch.setattr(function_app, "pyodbc", MagicMock(connect=MagicMock(return_value=conn)))
    monkeypatch.setattr(function_app, "get_db_connection", lambda: conn)
    return conn  # ← cursorは返さずconnだけ返す

def test_error_response():
    resp = function_app.error_response("error", 404, "traceback")
    assert resp.status_code == 404
    body = json.loads(resp.get_body())
    assert body["error"] == "error"
    assert "trace" in body

def test_to_db_date_iso():
    val = "2024-06-01T12:34"
    result = function_app.to_db_date(val)
    assert result == "2024-06-01 12:34:00"

def test_to_db_date_none():
    assert function_app.to_db_date("") is None
    assert function_app.to_db_date(None) is None

def test_fetch_events(mock_db, monkeypatch):
    conn = mock_db
    cursor = conn.cursor.return_value
    cursor.description = [
        ("event_id",), ("event_title",), ("event_category",), ("event_datetime",), ("deadline",), ("location",), ("max_participants",), ("current_participants",), ("description",), ("content",), ("image",)
    ]
    cursor.fetchall.return_value = [
        (2, "title2", 1, "2099-07-01 10:00:00", "2099-06-30 23:59:00", "A", 10, 5, "desc2", "content2", "img2"),
        (1, "title1", 1, "2099-07-02 10:00:00", "2099-07-01 23:59:00", "B", 20, 10, "desc1", "content1", "img1"),
    ]
    cursor.execute.return_value = None
    monkeypatch.setattr(function_app, "get_db_connection", lambda: conn)
    monkeypatch.setattr(function_app, "pyodbc", MagicMock(connect=MagicMock(return_value=conn)))
    events = function_app.fetch_events("user", 0)
    assert isinstance(events, list)
    assert events[0]["event_id"] == 1  # reversed

def test_get_self_created_events_success(monkeypatch, mock_db):
    req = DummyRequest(params={"user_id": "u1"})
    monkeypatch.setattr(function_app, "fetch_events", lambda uid, d: [{"event_id": 1}])
    resp = function_app.get_self_created_events(req)
    assert resp.status_code == 200
    assert json.loads(resp.get_body())[0]["event_id"] == 1

def test_get_self_created_events_no_user(monkeypatch):
    req = DummyRequest(params={})
    req._json_data = {}
    resp = function_app.get_self_created_events(req)
    assert resp.status_code == 400

def test_get_categories_success(mock_db, monkeypatch):
    conn = mock_db
    cursor = conn.cursor.return_value
    cursor.description = [("category_id",), ("category_name",)]
    cursor.fetchall.return_value = [types.SimpleNamespace(category_id=1, category_name="cat1")]
    cursor.execute.return_value = None
    monkeypatch.setattr(function_app, "get_db_connection", lambda: conn)
    req = DummyRequest()
    resp = function_app.get_categories(req)
    assert resp.status_code == 200
    data = json.loads(resp.get_body())
    assert data[0]["category_id"] == 1

def test_get_keywords_success(mock_db, monkeypatch):
    conn = mock_db
    cursor = conn.cursor.return_value
    cursor.fetchall.return_value = [types.SimpleNamespace(keyword_id=1, keyword_name="kw1")]
    monkeypatch.setattr(function_app, "get_db_connection", lambda: conn)
    req = DummyRequest()
    resp = function_app.get_keywords(req)
    assert resp.status_code == 200
    data = json.loads(resp.get_body())
    assert data[0]["keyword_id"] == 1

def test_delete_event_not_found(mock_db, monkeypatch):
    conn = mock_db
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = None
    monkeypatch.setattr(function_app, "get_db_connection", lambda: conn)
    req = DummyRequest(route_params={"event_id": "1"})
    resp = function_app.delete_event(req)
    assert resp.status_code in (400, 403, 404, 500)