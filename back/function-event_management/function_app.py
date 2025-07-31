import os
import json
import logging
import traceback
import azure.functions as func
from requests_toolbelt.multipart import decoder
import uuid
from datetime import datetime, date

from utils import get_db_connection, get_azure_storage_connection_string, error_response, success_response
from utils_blob import upload_blob, get_blob_sas_url

# 追加: Azure Blob Storage用
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

CONTAINER_NAME = "event-images"


def to_db_date(val):
    if not val or (isinstance(val, str) and val.strip() == ""):
        return None
    if isinstance(val, str) and 'T' in val:
        try:
            date_part, time_part = val.split('T')
            if len(time_part) == 5:
                time_part += ':00'
            return f"{date_part} {time_part}"
        except Exception:
            return val
    return val


def parse_multipart(req):
    content_type = req.headers.get("Content-Type", "")
    data, image_path, image_bytes, image_filename = {}, None, None, None
    if content_type.startswith("multipart/form-data"):
        body = req.get_body()
        multipart_data = decoder.MultipartDecoder(body, content_type)
        for part in multipart_data.parts:
            cd = part.headers.get(b'Content-Disposition', b'').decode()
            if 'filename=' in cd:
                filename = cd.split('filename="')[1].split('"')[0]
                ext = os.path.splitext(filename)[1]
                user_id = str(data.get("creator", "unknown"))
                unique_id = uuid.uuid4().hex[:8]
                save_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{user_id}_{unique_id}{ext}"
                image_bytes = part.content
                image_filename = save_name
                # image_pathは後でAzureアップロード後にセット
            else:
                name = cd.split('name="')[1].split('"')[0]
                value = part.text
                if name == "keywords":
                    data.setdefault("keywords", []).append(value)
                else:
                    data[name] = value
        if "image" not in data:
            data["image"] = None
    else:
        data = req.get_json()
        image_path = data.get("image")
    return data, image_path, image_bytes, image_filename

def fetch_events(user_id, is_draft):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT event_id, event_title, event_category, event_datetime, deadline, location, max_participants, current_participants, description, content, image
            FROM EVENTS
            WHERE creator = ? AND is_draft = ? AND (event_datetime > GETDATE() OR event_datetime IS NULL)
            ORDER BY event_datetime DESC
        '''
        cursor.execute(query, (user_id, is_draft))
        columns = [column[0] for column in cursor.description]
        events = []
        for row in cursor.fetchall():
            event = dict(zip(columns, row))
            for k, v in event.items():
                if hasattr(v, 'isoformat'):
                    event[k] = v.isoformat()
            events.append(event)
        events.reverse()
        return events


@app.route(route="create_event", methods=["POST"])
def create_event(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data, image_path, image_bytes, image_filename = parse_multipart(req)
        logging.info(f"image_bytes: {type(image_bytes)}, image_filename: {image_filename}")

        data["category"] = data.get("category") or None
        data["max_participants"] = data.get("max_participants") or None
        is_draft = int(data.get("is_draft", 1))
        data["is_draft"] = is_draft
        required_fields = ["title", "date", "location", "category", "keywords", "summary", "detail", "deadline"]
        if is_draft:
            data.setdefault("title", "（未入力）")
            data.setdefault("creator", "")
            data.setdefault("is_draft", 1)
        else:
            for f in required_fields:
                if not data.get(f):
                    return error_response(f"{f}は必須です")

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO EVENTS (event_title, event_category, event_datetime, deadline, location, max_participants, creator, description, content, is_draft)
                OUTPUT INSERTED.event_id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                data.get("title"),
                int(data.get("category")) if data.get("category") else None,
                to_db_date(data.get("date")),
                to_db_date(data.get("deadline")),
                data.get("location"),
                int(data.get("max_participants")) if data.get("max_participants") else None,
                str(data.get("creator")),
                data.get("summary"),
                data.get("detail"),
                is_draft
            )
            event_id = int(cursor.fetchone()[0])

            # 画像があればAzureストレージにアップロード
            if image_bytes and image_filename:
                blob_name = upload_blob("event-images", image_bytes, image_filename, "eventimg_" + str(event_id))
                cursor.execute(
                    '''
                    UPDATE EVENTS
                    SET image = ?
                    WHERE event_id = ?
                    ''',
                    blob_name, event_id
                )


            if data.get("keywords"):
                for kw in data["keywords"]:
                    if kw:
                        cursor.execute(
                            '''
                            INSERT INTO EVENTS_KEYWORDS (event_id, keyword_id)
                            VALUES (?, ?)
                            ''',
                            event_id, int(kw)
                        )
            conn.commit()
        return func.HttpResponse(json.dumps({"message": "イベント登録完了", "event_id": event_id}), mimetype="application/json", status_code=200)
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(tb)
        return error_response(str(e), 500)

@app.route(route="get_self_created_events")
def get_self_created_events(req: func.HttpRequest) -> func.HttpResponse:
    user_id = req.params.get('user_id')
    if not user_id:
        return error_response("user_id is required", 400)
    try:
        events = fetch_events(user_id, 0)
        return func.HttpResponse(
            json.dumps(events, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        return error_response(str(e), 500)

@app.route(route="get_draft")
def get_draft(req: func.HttpRequest) -> func.HttpResponse:
    user_id = req.params.get('id')
    if not user_id:
        try:
            user_id = req.get_json().get('id')
        except Exception:
            return error_response("user_id is required")
    try:
        events = fetch_events(user_id, 1)
        return func.HttpResponse(json.dumps(events, ensure_ascii=False), mimetype="application/json")
    except Exception as e:
        logging.error(str(e))
        return error_response("DB error", 500)

@app.route(route="delete_event/{event_id}", methods=["DELETE"])
def delete_event(req: func.HttpRequest) -> func.HttpResponse:
    event_id = req.route_params.get('event_id')
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT creator FROM EVENTS WHERE event_id=?", (event_id,))
            row = cursor.fetchone()
            if not row:
                return error_response("イベントが存在しません", 404)
            event_creator = row.creator if hasattr(row, "creator") else row[0]
            try:
                data = req.get_json()
            except Exception:
                data = {}
            request_creator = str(data.get("creator", ""))
            if not request_creator or request_creator != str(event_creator):
                return error_response("イベント作成者のみ削除可能です", 403)
            cursor.execute("DELETE FROM EVENTS_KEYWORDS WHERE event_id=?", (event_id,))
            cursor.execute("DELETE FROM EVENTS_PARTICIPANTS WHERE event_id=?", (event_id,))
            cursor.execute("DELETE FROM favorites WHERE event_id=?", (event_id,))  # ←追加
            cursor.execute("DELETE FROM EVENTS WHERE event_id=?", (event_id,))
            conn.commit()
        return func.HttpResponse(json.dumps({"message": "イベント削除完了", "event_id": event_id}), mimetype="application/json", status_code=200)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logging.error(tb)
        return error_response(str(e), 500, tb)

@app.route(route="get_categories", methods=["GET"])
def get_categories(req: func.HttpRequest) -> func.HttpResponse:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category_id, category_name FROM CATEGORIES")
            rows = cursor.fetchall()
            result = [{"category_id": row.category_id, "category_name": row.category_name} for row in rows]
        return func.HttpResponse(json.dumps(result), mimetype="application/json")
    except Exception as e:
        logging.error(str(e))
        return error_response(f"Error: {str(e)}", 500)

@app.route(route="get_keywords", methods=["GET"])
def get_keywords(req: func.HttpRequest) -> func.HttpResponse:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT keyword_id, keyword_name FROM KEYWORDS")
            rows = cursor.fetchall()
            result = [{"keyword_id": row.keyword_id, "keyword_name": row.keyword_name} for row in rows]
        return func.HttpResponse(json.dumps(result), mimetype="application/json")
    except Exception as e:
        logging.error(str(e))
        return error_response(f"Error: {str(e)}", 500)

@app.route(route="search_events", methods=["GET", "POST"])
def search_events(req: func.HttpRequest) -> func.HttpResponse:
    try:
        if req.method == "POST":
            body = req.get_json()
            keyword = body.get("keyword")
            event_title = body.get("event_title", "").strip()
        else:
            keyword = req.params.get("keyword", "").strip()
            event_title = req.params.get("event_title", "").strip()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            sql = '''
                SELECT DISTINCT e.*, c.category_name
                FROM events e
                LEFT JOIN CATEGORIES c ON e.event_category = c.category_id
                LEFT JOIN EVENTS_KEYWORDS ek ON e.event_id = ek.event_id
                LEFT JOIN KEYWORDS k ON ek.keyword_id = k.keyword_id
                WHERE e.is_draft=0
            '''
            params = []
            if event_title:
                sql += " AND e.event_title LIKE ?"
                params.append(f"%{event_title}%")
            if keyword:
                sql += " AND k.keyword_name = ?"
                params.append(keyword)
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # imageカラムがあればURL化
                if row_dict.get("image"):
                    row_dict["image"] = get_blob_sas_url("event-images", row_dict["image"])
                # event_idに対応するキーワード名を配列で取得
                cursor.execute(
                    '''
                    SELECT k.keyword_name
                    FROM EVENTS_KEYWORDS ek
                    JOIN KEYWORDS k ON ek.keyword_id = k.keyword_id
                    WHERE ek.event_id = ?
                    ''',
                    (row_dict["event_id"],)
                )
                keywords = [kname for (kname,) in cursor.fetchall()]
                row_dict["keywords"] = keywords
                result.append(row_dict)
            print(result)
            return func.HttpResponse(json.dumps(result, default=str), mimetype="application/json")
    except Exception as e:
        return error_response(str(e), 500)

@app.route(route="get_event_detail", methods=["GET"])
def get_event_detail(req: func.HttpRequest) -> func.HttpResponse:
    try:
        event_id = req.params.get("event_id")
        if not event_id:
            return error_response("event_idは必須です", 400)
        try:
            event_id = int(event_id)
        except ValueError:
            return error_response("event_idは整数で指定してください", 400)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT event_id, event_title, event_category, event_datetime, deadline, location, max_participants, current_participants, creator, CONCAT(u.l_name, u.f_name) AS creator_name, u.handle_name,description, content, image, is_draft
                FROM EVENTS e
                LEFT JOIN users u
                ON e.creator = u.id
                WHERE event_id=?
                ''',
                (event_id,)
            )
            row = cursor.fetchone()
            if row:
                keys = ["event_id", "event_title", "event_category", "event_datetime", "deadline", "location", "max_participants", "current_participants", "creator_id", "creator_name", "handle_name", "description", "content", "image", "is_draft"]
                event = dict(zip(keys, row))
                # imageカラムがあればURL化
                if event.get("image"):
                    event["image"] = get_blob_sas_url("event-images", event["image"])
                # datetime型を文字列に変換
                for k in ["event_datetime", "deadline"]:
                    if isinstance(event[k], (datetime, date)):
                        event[k] = event[k].isoformat()
                # キーワード一覧を取得して追加
                cursor.execute(
                    '''
                    SELECT k.keyword_id, k.keyword_name
                    FROM EVENTS_KEYWORDS ek
                    JOIN KEYWORDS k ON ek.keyword_id = k.keyword_id
                    WHERE ek.event_id = ?
                    ''',
                    (event_id,)
                )
                keywords = [{"keyword_id": kid, "keyword_name": kname} for kid, kname in cursor.fetchall()]
                event["keywords"] = keywords
                return success_response(event)
            else:
                return error_response("イベントが見つかりません", 404)
    except Exception as e:
        return error_response(str(e), 500)


@app.route(route="events/{event_id}", methods=["PUT"])
def update_event(req: func.HttpRequest) -> func.HttpResponse:
    event_id = int(req.route_params.get('event_id'))
    try:
        data, _, image_bytes, image_filename = parse_multipart(req)

        # 作成者チェック
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT creator FROM EVENTS WHERE event_id=?", (event_id,))
            row = cursor.fetchone()
            if not row:
                return error_response("イベントが存在しません", 404)
            event_creator = row.creator if hasattr(row, "creator") else row[0]
            request_creator = str(data.get("creator", ""))
            if not request_creator or request_creator != str(event_creator):
                return error_response("イベント作成者のみ編集可能です", 403)

            # 画像アップロード
            if image_bytes and image_filename:
                blob_name = upload_blob("event-images", image_bytes, image_filename, "eventimg_" + str(event_id))
                data["image"] = blob_name

            # イベント更新
            cursor.execute(
                '''
                UPDATE EVENTS SET event_title=?, event_category=?, event_datetime=?, deadline=?, location=?, max_participants=?, description=?, content=?, image=?, is_draft=? WHERE event_id=?
                ''',
                data.get("title"),
                int(data.get("category")) if data.get("category") else None,
                to_db_date(data.get("date")),
                to_db_date(data.get("deadline")),
                data.get("location"),
                int(data.get("max_participants")) if data.get("max_participants") else None,
                data.get("summary"),
                data.get("detail"),
                data.get("image"),
                int(data.get("is_draft", 0)),
                event_id
            )
            # キーワード更新
            cursor.execute("DELETE FROM EVENTS_KEYWORDS WHERE event_id=?", (event_id,))
            if data.get("keywords"):
                for kw in data["keywords"]:
                    cursor.execute("INSERT INTO EVENTS_KEYWORDS (event_id, keyword_id) VALUES (?, ?)", (event_id, int(kw)))
            conn.commit()
        return success_response({"message": "イベント更新完了", "event_id": event_id})
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(tb)
        return error_response(str(e), 500, tb)


# @app.route(route="get_participants")
# def get_participants(req: func.HttpRequest) -> func.HttpResponse:
#     logging.info('参加者一覧APIが呼び出されました')
#     event_id = req.params.get('event_id')
#     if not event_id:
#         return func.HttpResponse("event_id is required", status_code=400)

#     try:
#         with get_db_connection() as conn:
#             cursor = conn.cursor()
#             sql = """
#                 SELECT u.id, u.l_name, u.f_name, u.email
#                 FROM EVENTS_PARTICIPANTS ep
#                 JOIN USERS u ON ep.id = u.id
#                 WHERE ep.event_id = ? AND ep.cancelled_at IS NULL
#             """
#             cursor.execute(sql, (event_id,))
#             columns = [column[0] for column in cursor.description]
#             participants = [dict(zip(columns, row)) for row in cursor.fetchall()]
#     except Exception as e:
#         logging.error(str(e))
#         return error_response(f"DB error: {str(e)}", 500)

#     return func.HttpResponse(
#         json.dumps({"participants": participants}, ensure_ascii=False),
#         mimetype="application/json",
#         status_code=200
#     )

# get_event = get_event_detail  # ファイル末尾などに追加
