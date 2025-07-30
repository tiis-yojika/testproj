import azure.functions as func
import logging
import pyodbc
import os
import json
from datetime import datetime

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

if os.environ.get("IS_MAIN_PRODUCT") == "true":
    CONNECTION_STRING = os.environ.get("CONNECTION_STRING_PRODUCT")
else:
    CONNECTION_STRING = os.environ.get("CONNECTION_STRING_TEST")

@app.route(route="get_favorites")
def get_favorites(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # クエリパラメータからユーザーIDを取得
    user_id = req.params.get("id")
    if not user_id:
        try:
            req_body = req.get_json()
        except Exception:
            req_body = None
        if req_body:
            user_id = req_body.get("id")

    if not user_id:
        return func.HttpResponse("ユーザーIDが指定されていません", status_code=400)

    if not CONNECTION_STRING:
        logging.error("CONNECTION_STRING is not set in environment variables.")
        return func.HttpResponse("DB connection string not found.", status_code=500)

    try:
        with pyodbc.connect(CONNECTION_STRING) as conn:
            cursor = conn.cursor()
            # お気に入りイベント一覧を取得
            cursor.execute("""
                SELECT f.event_id, e.event_title, e.event_datetime, e.location, e.description, e.content
                FROM favorites f
                JOIN EVENTS e ON f.event_id = e.event_id
                WHERE f.id = ?
            """, (user_id,))
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            favorites_list = []
            for row in rows:
                item = dict(zip(columns, row))
                # datetime型を文字列に変換
                for k, v in item.items():
                    if isinstance(v, datetime):
                        item[k] = v.isoformat()
                favorites_list.append(item)

        return func.HttpResponse(
            json.dumps(favorites_list, ensure_ascii=False),
            mimetype="application/json",
            status_code=200
        )
    except Exception as e:
        logging.error(f"DB error: {e}")
        return func.HttpResponse("DB error", status_code=500)
    

@app.route(route="add_favorite", methods=["POST"])
def add_favorite(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse("リクエストボディが不正です", status_code=400)
    event_id = req_body.get("event_id")
    user_id = req_body.get("id")
    if not event_id or not user_id:
        return func.HttpResponse("event_idまたはidが指定されていません", status_code=400)
    try:
        if not CONNECTION_STRING:
            logging.error("CONNECTION_STRINGが環境変数に設定されていません")
            return func.HttpResponse("DB接続情報がありません", status_code=500)
        conn = pyodbc.connect(CONNECTION_STRING)
        cursor = conn.cursor()
        sql = "INSERT INTO favorites (event_id, id) VALUES (?, ?)"
        cursor.execute(sql, (event_id, user_id))
        conn.commit()
        conn.close()
        return func.HttpResponse("お気に入り登録完了", status_code=200)
    except Exception as e:
        logging.error(f"お気に入り登録DBエラー: {e}")
        return func.HttpResponse(f"DB接続エラー: {e}", status_code=500)


@app.route(route="remove_favorite", methods=["DELETE"])
def remove_favorite(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
        user_id = req_body.get("id")
        event_id = req_body.get("event_id")
        # 以降、user_idとevent_idを使って処理
    except ValueError:
        return func.HttpResponse("リクエストボディが不正です", status_code=400)
    if not CONNECTION_STRING:
        logging.error("CONNECTION_STRING is not set in environment variables.")
        return func.HttpResponse("DB connection string not found.", status_code=500)
    try:
        with pyodbc.connect(CONNECTION_STRING) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM favorites WHERE event_id = ? AND id = ?",
                (event_id, user_id)
            )
            conn.commit()
        return func.HttpResponse("OK", status_code=200)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return func.HttpResponse("DB error", status_code=500)