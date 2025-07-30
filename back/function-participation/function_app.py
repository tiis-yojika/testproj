import azure.functions as func
import json
import pyodbc
import os
import logging
from datetime import datetime

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

from utils import get_connection_string, get_db_connection, error_response, success_response, to_jst_isoformat
from utils_blob import get_blob_sas_url

# イベント参加登録API
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
        return success_response({"message": "参加予約しました"}, status=200)
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
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # datetimeをISO8601形式に変換
                row_dict["event_datetime"] = to_jst_isoformat(row_dict["event_datetime"]) if row_dict["event_datetime"] else None
                row_dict["registered_at"] = to_jst_isoformat(row_dict["registered_at"]) if row_dict["registered_at"] else None
                # imageカラムがあればURL化
                if row_dict.get("image"):
                    row_dict["image"] = get_blob_sas_url("event-images", row_dict["image"])
                result.append(row_dict)
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
    user_id = data.get("id")
    
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
                    LEFT JOIN EVENTS e ON ep.event_id = e.event_id
                WHERE
                    ep.id = ?
                    AND e.event_datetime < ?
                ORDER BY
                    e.event_datetime DESC
                ''',
                (user_id, now)
            )
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # datetimeをISO8601形式に変換
                row_dict["event_datetime"] = to_jst_isoformat(row_dict["event_datetime"]) if row_dict["event_datetime"] else None
                row_dict["registered_at"] = to_jst_isoformat(row_dict["registered_at"]) if row_dict["registered_at"] else None
                # imageカラムがあればURL化
                if row_dict.get("image"):
                    row_dict["image"] = get_blob_sas_url("event-images", row_dict["image"])
                result.append(row_dict)
            logging.info(f"取得参加履歴: {result}")
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)

    return success_response(result, status=200)


@app.route(route="get_participants", methods=["GET"])
def get_participants(req: func.HttpRequest) -> func.HttpResponse:
    event_id = req.params.get("event_id")
    
    if not event_id:
        return error_response("event_idは必須です", status=400)
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            sql = """
            SELECT
                ep.id,
                u.profile_img,
                u.handle_name
            FROM
                EVENTS_PARTICIPANTS ep
                LEFT JOIN USERS u ON ep.id = u.id
            WHERE
                ep.event_id = ?
            """
            cursor.execute(sql, (event_id,))
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            if not rows:
                return error_response("参加者が見つかりません", status=404)
            result = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # profile_imgカラムがあればURL化
                if row_dict.get("profile_img"):
                    row_dict["profile_img"] = get_blob_sas_url("profile-images", row_dict["profile_img"])
                result.append(row_dict)
            logging.info(f"取得参加者リスト: {result}")
    except Exception as e:
        logging.error(f"DB error: {e}")
        return error_response("DB error", status=500)

    return success_response(result, status=200)