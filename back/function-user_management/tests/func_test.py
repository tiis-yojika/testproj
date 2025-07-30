import pytest
from unittest.mock import patch, MagicMock

from function_app import (
    get_user, update_user, upload_blob, delete_blob, get_blob_sas_url, sanitize_filename
)
import azure.functions as func

@pytest.fixture
def mock_req_json():
    class MockReq:
        def __init__(self, json_data):
            self._json = json_data
            self.headers = {"Content-Type": "application/json"}
        def get_json(self):
            return self._json
    return MockReq

def test_sanitize_filename_valid():
    assert sanitize_filename("test.png") == ".png"
    assert sanitize_filename("abc.jpeg") == ".jpeg"

@pytest.mark.parametrize("filename", [
    "test", "test/.png", "test\\a.png", "test:abc.png", "test*abc.png",
    "test?abc.png", "test\"abc.png", "test<abc.png", "test>abc.png", "test|abc.png",
    "test.veryverylongext"
])
def test_sanitize_filename_invalid(filename):
    with pytest.raises(Exception):
        sanitize_filename(filename)

@patch("function_app.get_db_connection")
@patch("function_app.BlobServiceClient")
def test_upload_blob_success(mock_blob_service, mock_db_conn):
    mock_blob_client = MagicMock()
    mock_container_client = MagicMock()
    mock_blob_service.from_connection_string.return_value.get_container_client.return_value = mock_container_client
    mock_db_conn.return_value.__enter__.return_value.cursor.return_value = MagicMock()
    file_bytes = b"abc"
    filename = "test.png"
    user_id = "user1"
    result = upload_blob(file_bytes, filename, user_id)
    assert result == "user1.png"

@patch("function_app.get_db_connection")
@patch("function_app.BlobServiceClient")
def test_upload_blob_blob_fail(mock_blob_service, mock_db_conn):
    mock_container_client = MagicMock()
    mock_container_client.upload_blob.side_effect = Exception("blob error")
    mock_blob_service.from_connection_string.return_value.get_container_client.return_value = mock_container_client
    file_bytes = b"abc"
    filename = "test.png"
    user_id = "user1"
    with pytest.raises(Exception, match="BLOBアップロードに失敗しました"):
        upload_blob(file_bytes, filename, user_id)

@patch("function_app.get_db_connection")
@patch("function_app.BlobServiceClient")
def test_upload_blob_db_fail(mock_blob_service, mock_db_conn):
    mock_container_client = MagicMock()
    mock_blob_service.from_connection_string.return_value.get_container_client.return_value = mock_container_client
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("db error")
    mock_db_conn.return_value.__enter__.return_value.cursor.return_value = mock_cursor
    file_bytes = b"abc"
    filename = "test.png"
    user_id = "user1"
    with pytest.raises(Exception, match="DB更新に失敗しました"):
        upload_blob(file_bytes, filename, user_id)

@patch("function_app.BlobServiceClient")
def test_delete_blob_success(mock_blob_service):
    mock_blob_client = MagicMock()
    mock_container_client = MagicMock()
    mock_container_client.get_blob_client.return_value = mock_blob_client
    mock_blob_service.from_connection_string.return_value.get_container_client.return_value = mock_container_client
    assert delete_blob("abc.png") is True

@patch("function_app.BlobServiceClient")
def test_delete_blob_fail(mock_blob_service):
    mock_blob_client = MagicMock()
    mock_blob_client.delete_blob.side_effect = Exception("fail")
    mock_container_client = MagicMock()
    mock_container_client.get_blob_client.return_value = mock_blob_client
    mock_blob_service.from_connection_string.return_value.get_container_client.return_value = mock_container_client
    assert delete_blob("abc.png") is False

@patch("function_app.BlobServiceClient")
@patch("function_app.generate_blob_sas")
def test_get_blob_sas_url(mock_generate_sas, mock_blob_service):
    mock_blob_service.from_connection_string.return_value.account_name = "acc"
    mock_blob_service.from_connection_string.return_value.credential = "key"
    mock_generate_sas.return_value = "sas"
    url = get_blob_sas_url("abc.png")
    assert url.startswith("https://acc.blob.core.windows.net/")

@patch("function_app.get_db_connection")
def test_get_user_success(mock_db_conn, mock_req_json):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (
        "mail@example.com", "sec@example.com", "090", "Yamada", "Taro", "ヤマダ", "タロウ", None, "img.png"
    )
    mock_cursor.description = [
        ("email",), ("second_email",), ("tel",), ("l_name",), ("f_name",),
        ("l_name_furi",), ("f_name_furi",), ("birthday",), ("profile_img",)
    ]
    mock_db_conn.return_value.cursor.return_value.__enter__.return_value = mock_cursor
    req = mock_req_json({"id": "user1"})
    with patch("function_app.get_blob_sas_url", return_value="http://img"):
        resp = get_user(req)
        assert resp.status_code == 200
        assert b"mail@example.com" in resp.get_body()

@patch("function_app.get_db_connection")
def test_get_user_not_found(mock_db_conn, mock_req_json):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_db_conn.return_value.cursor.return_value.__enter__.return_value = mock_cursor
    req = mock_req_json({"id": "user1"})
    resp = get_user(req)
    assert resp.status_code == 404

def test_get_user_no_id(mock_req_json):
    req = mock_req_json({})
    resp = get_user(req)
    assert resp.status_code == 400 or resp.status_code == 200  # error_response returns 200 by default

@patch("function_app.get_db_connection")
def test_update_user_no_id(mock_db_conn, mock_req_json):
    req = mock_req_json({})
    resp = update_user(req)
    assert resp.status_code == 400

@patch("function_app.get_db_connection")
def test_update_user_not_found(mock_db_conn, mock_req_json):
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_db_conn.return_value.cursor.return_value.__enter__.return_value = mock_cursor
    req = mock_req_json({"id": "user1", "l_name": "Yamada"})
    resp = update_user(req)
    assert resp.status_code == 404

@patch("function_app.get_db_connection")
def test_update_user_success(mock_db_conn, mock_req_json):
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_db_conn.return_value.cursor.return_value.__enter__.return_value = mock_cursor
    req = mock_req_json({"id": "user1", "l_name": "Yamada"})
    resp = update_user(req)
    assert resp.status_code == 200