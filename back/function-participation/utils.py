import os
import azure.functions as func
import json
import pyodbc

from datetime import datetime, timezone, timedelta

def get_connection_string():
    if os.environ.get("IS_MAIN_PRODUCT") and os.environ.get("IS_MAIN_PRODUCT") == "true":
        return os.environ.get("CONNECTION_STRING_PRODUCT")
    else:
        return os.environ.get("CONNECTION_STRING_TEST")

def get_db_connection():
    conn_str = get_connection_string()
    if not conn_str:
        raise Exception("DB接続情報がありません")
    return pyodbc.connect(conn_str)
    
def get_azure_storage_connection_string():
    if os.environ.get("IS_MAIN_PRODUCT") == "true":
        return os.environ.get("AZURE_STORAGE_CONNECTION_STRING_PRODUCT")
    else:
        return os.environ.get("AZURE_STORAGE_CONNECTION_STRING_TEST")

def error_response(message, status=400):
    return func.HttpResponse(
        body=json.dumps({"error": message}, ensure_ascii=False),
        status_code=status,
        mimetype="application/json"
    )

def success_response(data=None, message=None, status=200):
    body = data if data is not None else {}
    if message:
        body["message"] = message
    return func.HttpResponse(
        body=json.dumps(body, ensure_ascii=False),
        status_code=status,
        mimetype="application/json"
    )

def to_jst_isoformat(dt):
    """datetime型をJST（東京）タイムゾーンのISO8601文字列に変換"""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    jst = timezone(timedelta(hours=9))
    return dt.astimezone(jst).isoformat()