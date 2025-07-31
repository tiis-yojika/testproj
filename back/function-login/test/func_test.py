from unittest.mock import patch, MagicMock
import function_app
import pyodbc

class DummyRequest:
    def __init__(self, json_data, raise_on_get_json=False):
        self._json = json_data
        self._raise_on_get_json = raise_on_get_json
    def get_json(self):
        if self._raise_on_get_json:
            raise ValueError
        return self._json

def test_validate_credentials_success():
    data = {"id": "user1", "password": "pass"}
    id, password, error = function_app.validate_credentials(data)
    assert id == "user1"
    assert password == "pass"
    assert error is None

def test_validate_credentials_missing_id():
    data = {"password": "pass"}
    id, password, error = function_app.validate_credentials(data)
    assert error is not None

def test_validate_credentials_missing_password():
    data = {"id": "user1"}
    id, password, error = function_app.validate_credentials(data)
    assert error is not None

def test_validate_credentials_empty_fields():
    data = {"id": " ", "password": ""}
    id, password, error = function_app.validate_credentials(data)
    assert error is not None

@patch("function_app.pyodbc.connect")
def test_check_user_success(mock_connect):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [1]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value.__enter__.return_value = mock_conn
    assert function_app.check_user("user1", "pass") is True

@patch("function_app.pyodbc.connect")
def test_check_user_failure(mock_connect):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [0]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value.__enter__.return_value = mock_conn
    assert function_app.check_user("user1", "wrongpass") is False

@patch("function_app.pyodbc.connect", side_effect=pyodbc.Error)
def test_check_user_db_error(mock_connect):
    result = function_app.check_user("user1", "pass")
    assert result is None

@patch("function_app.check_user", return_value=True)
@patch("function_app.validate_credentials", return_value=("user1", "pass", None))
def test_login_success(mock_validate, mock_check):
    function_app.CONNECTION_STRING = "dummy"
    req = DummyRequest({"id": "user1", "password": "pass"})
    resp = function_app.login(req)
    assert resp.status_code == 200
    body = resp.get_body().decode("utf-8")
    import json
    data = json.loads(body)
    assert data.get("id") == "user1"

@patch("function_app.check_user", return_value=False)
@patch("function_app.validate_credentials", return_value=("user1", "pass", None))
def test_login_invalid_credentials(mock_validate, mock_check):
    req = DummyRequest({"id": "user1", "password": "wrong"})
    resp = function_app.login(req)
    assert resp.status_code == 401

@patch("function_app.validate_credentials", return_value=(None, None, function_app.error_response("err", status=400)))
def test_login_validation_error(mock_validate):
    req = DummyRequest({})
    resp = function_app.login(req)
    assert resp.status_code == 400

@patch("function_app.check_user", return_value=None)
@patch("function_app.validate_credentials", return_value=("user1", "pass", None))
def test_login_db_error(mock_validate, mock_check):
    req = DummyRequest({"id": "user1", "password": "pass"})
    resp = function_app.login(req)
    assert resp.status_code == 500

def test_login_invalid_json():
    req = DummyRequest({}, raise_on_get_json=True)
    resp = function_app.login(req)
    assert resp.status_code == 400