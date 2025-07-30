import azure.functions as func
import logging
import hashlib
from datetime import datetime, timezone, timedelta


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

from utils import missing, get_db_connection, get_azure_storage_connection_string, error_response, success_response, to_jst_isoformat


@app.route(route="get_inquiries", methods=["POST"])
def get_inquiries(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except Exception:
        return error_response("リクエストボディが不正です。", status=400)

    is_send = body.get('is_send')
    id = str(body.get('id'))
    if is_send is None or not id:
        return error_response("パラメータ不足", status=400)

    target_field = 'sender' if is_send else 'recipient'

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            query = f'''
                SELECT
                    i.inquiry_id,
                    i.event_id,
                    e.event_title,
                    i.subject,
                    i.hashed_inquiry_id,
                    COUNT(d2.inquiry_id) AS count
                FROM INQUIRY_INFO i
                LEFT JOIN EVENTS e ON i.event_id = e.event_id
                INNER JOIN INQUIRY_DETAILS d ON i.inquiry_id = d.inquiry_id
                                              AND d.{target_field} = ?
                                              AND d.inquiry_no = 1
                LEFT JOIN INQUIRY_DETAILS d2 ON i.inquiry_id = d2.inquiry_id
                GROUP BY
                    i.inquiry_id, i.event_id, e.event_title, i.subject, i.hashed_inquiry_id
            '''
            cursor.execute(query, (id,))
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result = [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return error_response(f"取得エラー: {str(e)}", status=500)
    finally:
        if 'conn' in locals():
            conn.close()

    return success_response(result, status=200)


@app.route(route="get_inquiry_details", methods=["POST"])
def get_inquiry_details(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except Exception:
        return error_response("リクエストボディが不正です。", status=400)

    id = str(body.get('id'))
    hashed_inquiry_id = str(body.get('hashed_inquiry_id'))
    if not id or not hashed_inquiry_id:
        return error_response("ユーザーIDおよび問い合わせidは必須です。", status=400)

    try:
        conn = get_db_connection()
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute(
                '''
                SELECT inquiry_id
                FROM INQUIRY_INFO
                WHERE hashed_inquiry_id=?
                ''',
                (hashed_inquiry_id,)
            )
            row = cursor.fetchone()
            if not row:
                return error_response("指定された問い合わせは存在しません。", status=404)
            inquiry_id = row[0]

            cursor.execute(
                '''
                SELECT 
                    i.inquiry_id,
                    i.event_id,
                    e.event_title,
                    i.subject,
                    d.main_text,
                    d.created_at,
                    d.recipient,
                    ur.handle_name AS recipient_name,
                    d.sender,
                    us.handle_name AS sender_name
                FROM INQUIRY_INFO i
                LEFT JOIN INQUIRY_DETAILS d
                    ON i.inquiry_id = d.inquiry_id
                LEFT JOIN EVENTS e
                    ON i.event_id = e.event_id
                LEFT JOIN USERS ur
                    ON d.recipient = ur.id
                LEFT JOIN USERS us
                    ON d.sender = us.id
                WHERE i.inquiry_id=?
                ''',
                (inquiry_id,)
            )
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # created_atがdatetime型の場合のみ変換
                if isinstance(row_dict.get('created_at'), datetime):
                    row_dict['created_at'] = to_jst_isoformat(row_dict['created_at'])
                result.append(row_dict)

            # 既読処理
            cursor.execute(
                '''
                UPDATE INQUIRY_DETAILS
                SET checked = 1
                WHERE inquiry_id = ? AND recipient = ?
                ''',
                (inquiry_id, id)
            )
            conn.commit()
    except Exception as e:
        return error_response(f"取得エラー: {str(e)}", status=500)
    finally:
        if 'conn' in locals():
            conn.close()

    return success_response(result, status=200)


@app.route(route="create_inquiry", methods=["POST"])
def create_inquiry(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    try:
        body = req.get_json()
    except Exception:
        return error_response("リクエストボディが不正です。", status=400)

    inquiry_id = int(body.get('inquiry_id')) if body.get('inquiry_id') is not None else None
    event_id = int(body.get('event_id')) if body.get('event_id') is not None else None
    subject = body.get('subject')
    main_text = body.get('main_text')
    recipient = body.get('recipient')
    sender = body.get('sender')

    if not inquiry_id:
        if missing(event_id, subject, main_text, recipient, sender):
            return error_response("全てのフィールドは必須です。", status=400)
    else:
        if missing(main_text, recipient, sender):
            return error_response("全てのフィールドは必須です。", status=400)

    try:
        conn = get_db_connection()
        conn.autocommit = False  # トランザクション開始
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
            if not inquiry_id:
                cursor.execute(
                    '''
                    INSERT INTO INQUIRY_INFO (event_id, subject, hashed_inquiry_id)
                    OUTPUT INSERTED.inquiry_id
                    VALUES (?, ?, '');
                    ''',
                    (event_id, subject)
                )
                row = cursor.fetchone()
                inquiry_id = int(row[0])

                hashed_inquiry_id = hashlib.sha256(str(inquiry_id).encode()).hexdigest()
                cursor.execute(
                    '''
                    UPDATE INQUIRY_INFO
                    SET hashed_inquiry_id = ?
                    WHERE inquiry_id = ?
                    ''',
                    (hashed_inquiry_id, inquiry_id)
                )

            cursor.execute("""
                SELECT ISNULL(MAX(inquiry_no), 0) FROM INQUIRY_DETAILS WITH (UPDLOCK, HOLDLOCK)
                WHERE inquiry_id = ?
                """, (inquiry_id,))
            max_no = cursor.fetchone()[0]
            next_no = max_no + 1

            cursor.execute(
                '''
                INSERT INTO INQUIRY_DETAILS (inquiry_id, inquiry_no, main_text, recipient, sender)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (inquiry_id, next_no, main_text, recipient, sender)
            )

            conn.commit()
    except Exception as e:
        return error_response(f"データベースエラー: {str(e)}", status=500)
    finally:
        if 'conn' in locals():
            conn.close()
    return success_response({"message": "問い合わせを送信しました"}, status=201)


@app.route(route="receive_inquiries", methods=["POST"])
def receive_inquiries(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except Exception:
        return error_response({"error": "リクエストボディが不正です。"}, status=400)

    recipient = body.get('recipient')
    if not recipient:
        return error_response({"error": "受信者idは必須です。"}, status=400)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT 
                    d.inquiry_id, i.subject, MAX(d.created_at) AS created_at, i.hashed_inquiry_id
                FROM
                    INQUIRY_DETAILS d
                LEFT JOIN
                    INQUIRY_INFO i ON d.inquiry_id = i.inquiry_id
                WHERE
                    d.recipient=? AND d.checked=0
                GROUP BY
                    d.inquiry_id, i.subject, i.hashed_inquiry_id
                ORDER BY
                    created_at DESC;
                ''',
                (recipient,)
            )
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                # created_atがdatetime型の場合のみ変換
                if isinstance(row_dict.get('created_at'), datetime):
                    row_dict['created_at'] = to_jst_isoformat(row_dict['created_at'])
                result.append(row_dict)
    except Exception as e:
        return error_response({"error": f"データベースエラー: {str(e)}"}, status=500)

    return success_response(result, status=200)


