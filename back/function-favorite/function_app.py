import azure.functions as func
import logging
from utils import get_db_connection, success_response, error_response, rows_to_dict_list

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


@app.route(route="get_favorites", methods=["POST"])
def get_favorites(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # リクエストボディからユーザーIDを取得
    try:
        req_body = req.get_json()
    except ValueError:
        return error_response("リクエストボディが不正です", status=400)
    if not req_body:
        return error_response("リクエストボディが空です", status=400)
    if "id" not in req_body:
        return error_response("ユーザーIDが指定されていません", status=400)
    id = req_body.get("id")
    
    # お気に入りイベント一覧を取得
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT
                    f.event_id,
                    e.event_title,
                    c.category_name,
                    e.event_datetime,
                    e.location,
                    e.max_participants,
                    e.current_participants,
                    e.creator,
                    u.handle_name,
                    e.description,
                    e.image
                FROM
                    FAVORITES f
                JOIN
                    EVENTS e ON f.event_id=e.event_id
                JOIN
                    CATEGORIES c ON e.event_category=c.category_id
                JOIN
                    USERS u ON e.creator=u.id
                WHERE
                    f.id=?
                ''',
                (id,)
            )
            favorites_list = rows_to_dict_list(cursor)
        return success_response(favorites_list, status=200)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)


@app.route(route="add_favorite", methods=["POST"])
def add_favorite(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
    except ValueError:
        return error_response("リクエストボディが不正です", status=400)
    
    event_id = req_body.get("event_id")
    id = req_body.get("id")
    
    if not event_id or not id:
            return error_response("event_idまたはidが指定されていません", status=400)
    try:
        with get_db_connection() as conn:
            conn.autocommit = False  # トランザクションを開始
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO
                    FAVORITES (event_id, id)
                VALUES
                    (?, ?)
                ''',
                (event_id, id)
            )
            conn.commit()
        return success_response(message="お気に入り登録しました", status=200)
    except Exception as e:
        logging.error(f"お気に入り登録DBエラー: {e}")
        return error_response(f"DB接続エラー: {e}", status=500)


@app.route(route="remove_favorite", methods=["DELETE"])
def remove_favorite(req: func.HttpRequest) -> func.HttpResponse:
    try:
        req_body = req.get_json()
    except ValueError:
        return error_response("リクエストボディが不正です", status=400)
    
    event_id = req_body.get("event_id")
    id = req_body.get("id")

    try:
        with get_db_connection() as conn:
            conn.autocommit = False  # トランザクションを開始
            cursor = conn.cursor()
            cursor.execute(
                '''
                DELETE FROM
                    FAVORITES
                WHERE
                    event_id=? AND id=?
                ''',
                (event_id, id)
            )
            conn.commit()
        return success_response(message="お気に入りを解除しました", status=200)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)