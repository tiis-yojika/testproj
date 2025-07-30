import azure.functions as func
import pyodbc

from utils import get_db_connection, error_response, success_response

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

def validate_credentials(data):
    id = data.get("id")
    password = data.get("password")
    if not id or not password or not id.strip() or not password.strip():
        return None, None, "IDとパスワードの両方を入力してください"
    return id, password, None

def check_user(id, password):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE id=? AND password=?",
                (id, password)
            )
            result = cursor.fetchone()
            return result is not None and result[0] == 1
    except pyodbc.Error:
        return None

@app.route(route="login", methods=["POST"])
def login(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
        id, password, error = validate_credentials(data)
        if error:
            return error_response(error, status=400)
        user_exists = check_user(id, password)
        if user_exists is None:
            return error_response("データベースエラーが発生しました", status=500)
        if user_exists:
            resp_data = {"id": id}
            return success_response(data=resp_data)
        else:
            return error_response("IDまたはパスワードが異なります", status=401)
    except ValueError:
        return error_response("Invalid JSON format", status=400)
    except Exception:
        return error_response("An unexpected error occurred", status=400)