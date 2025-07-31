import azure.functions as func
import logging
from datetime import datetime

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

from utils import get_db_connection, error_response, success_response, rows_to_dict_list


@app.route(route="participate", methods=["POST"])
def participate(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except Exception:
        return error_response("リクエストボディが不正です", status=400)
    event_id = data.get("event_id")
    id = data.get("id")

    if not event_id or not id:
        return error_response("event_idとidは必須です", status=400)
    try:
        event_id = int(event_id)
    except ValueError:
        return error_response("event_idは整数で指定してください", status=400)

    try:
        with get_db_connection() as conn:
            conn.autocommit = False  # トランザクション開始
            cursor = conn.cursor()
            # すでに参加済みかチェック
            cursor.execute(
                '''
                SELECT
                    COUNT(*)
                FROM
                    EVENTS_PARTICIPANTS
                WHERE
                    event_id=? AND id=?
                ''',
                (event_id, id)
            )
            if cursor.fetchone()[0] > 0:
                return error_response("すでに参加登録済みです", status=409)
            # 定員チェック
            cursor.execute(
                '''
                SELECT
                    max_participants, current_participants
                FROM
                    EVENTS
                WHERE
                    event_id=?
                ''',
                (event_id,)
            )
            row = cursor.fetchone()
            if not row:
                return error_response("指定されたイベントは存在しません", status=404)
            max_participants, current_participants = row
            if current_participants >= max_participants:
                return error_response("定員に達しているため参加できません", status=403)
            # 参加登録
            cursor.execute(
                '''
                INSERT INTO
                    EVENTS_PARTICIPANTS (event_id, id)
                VALUES (?, ?)
                ''',
                (event_id, id)
            )
            # current_participantsをインクリメント
            cursor.execute(
                '''
                UPDATE
                    EVENTS
                SET
                    current_participants = current_participants + 1
                WHERE
                    event_id=?
                ''',
                (event_id,)
            )
            conn.commit()
        return success_response(message="参加予約しました", status=200)
    except Exception as e:
        return error_response(f"DB error: {str(e)}", status=500)


@app.route(route="reservation_history", methods=["POST"])
def reservation_history(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
    except Exception:
        return error_response("リクエストボディが不正です", status=400)
    id = data.get("id")

    if not id:
        return error_response("idは必須です", status=400)
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT
                    ep.event_id,
                    e.event_title,
                    e.event_datetime,
                    ep.registered_at,
                    e.location,
                    e.image
                FROM
                    EVENTS_PARTICIPANTS ep
                    LEFT JOIN EVENTS e ON ep.event_id = e.event_id
                WHERE
                    ep.id = ? AND e.deadline > GETDATE()
                ORDER BY
                    e.event_datetime DESC
                ''',
                (id,)
            )
            result = rows_to_dict_list(cursor)
            logging.info(f"取得予約履歴: {result}")
        return success_response(result, status=200)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)


@app.route(route="cancel_participation", methods=["DELETE"])
def cancel_participation(req: func.HttpRequest) -> func.HttpResponse:
    try:
        try:
            data = req.get_json()
        except Exception:
            return error_response("リクエストボディが不正です", status=400)
        event_id = data.get("event_id")
        id = data.get("id")
        if not event_id or not id:
            return error_response("event_idとidは必須です", status=400)
        try:
            event_id = int(event_id)
        except ValueError:
            return error_response("event_idは整数で指定してください", status=400)

        with get_db_connection() as conn:
            conn.autocommit = False  # トランザクション開始
            cursor = conn.cursor()
            # レコード削除
            cursor.execute(
                '''
                DELETE FROM
                    EVENTS_PARTICIPANTS
                WHERE
                    event_id=? AND id=?
                ''',
                (event_id, id)
            )
            if cursor.rowcount == 0:
                return error_response("参加登録が見つかりません", status=404)
            # current_participantsをデクリメント
            cursor.execute(
                '''
                UPDATE
                    EVENTS
                SET
                    current_participants = 
                        CASE WHEN current_participants > 0
                        THEN current_participants - 1
                        ELSE 0 
                        END
                WHERE
                    event_id=?
                ''',
                (event_id,)
            )
            conn.commit()
        return success_response(message="参加予約をキャンセルしました", status=200)
    except Exception as e:
        logging.error(f"Cancel participation error: {e}")
        return error_response("DB error", status=500)
    

@app.route(route="participation-history", methods=["POST"])
def participation_history(req: func.HttpRequest) -> func.HttpResponse:
    data = req.get_json()
    id = data.get("id")
    
    try:
        now = datetime.now()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT
                    ep.event_id,
                    e.event_title,
                    e.event_datetime,
                    ep.registered_at,
                    e.location,
                    e.image
                FROM
                    EVENTS_PARTICIPANTS ep
                LEFT JOIN
                    EVENTS e ON ep.event_id=e.event_id
                WHERE
                    ep.id=? AND e.event_datetime<?
                ORDER BY
                    e.event_datetime DESC
                ''',
                (id, now)
            )
            result = rows_to_dict_list(cursor)
            logging.info(f"取得参加履歴: {result}")
        return success_response(result, status=200)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)


@app.route(route="get_participants", methods=["GET"])
def get_participants(req: func.HttpRequest) -> func.HttpResponse:
    event_id = req.params.get("event_id")
    
    if not event_id:
        return error_response("event_idは必須です", status=400)
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT
                    ep.id,
                    u.profile_img,
                    u.handle_name
                FROM
                    EVENTS_PARTICIPANTS ep
                LEFT JOIN
                    USERS u ON ep.id=u.id
                WHERE
                    ep.event_id=?
                ''',
                (event_id,)
            )
            result = rows_to_dict_list(cursor)
            logging.info(f"取得参加者リスト: {result}")
        return success_response(result, status=200)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)