import os
import logging
from utils import get_db_connection, get_azure_storage_connection_string, error_response, success_response
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta


def get_azure_storage_connection_string():
    if os.environ.get("IS_MAIN_PRODUCT") == "true":
        return os.environ.get("AZURE_STORAGE_CONNECTION_STRING_PRODUCT")
    else:
        return os.environ.get("AZURE_STORAGE_CONNECTION_STRING_TEST")


def sanitize_filename(filename):
    # ファイル名から拡張子のみ取得し、ユーザーID+拡張子に限定
    ext = os.path.splitext(filename)[1]
    # 禁止文字が拡張子に含まれていないかチェック
    if (
        not ext
        or len(ext) > 10
        or any(c in ext for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|'])
        or any(c in os.path.splitext(filename)[0] for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|'])
    ):
        raise Exception("不正なファイル拡張子です")
    return ext


def upload_blob(container_name, img_data, img_name, save_name):
    """
    画像データをAzure Blob Storageにアップロードし、DBの画像情報を更新します。

    Parameters:
        container_name (str): アップロード先のAzure Blob Storageコンテナ名
        img_data (bytes): アップロードする画像データ（バイナリ）
        img_name (str): 元の画像ファイル名（拡張子取得に利用）
        save_name (str): 保存時のファイル名（例: ユーザーIDやイベントIDを含む文字列。例: "eventimg_111"）

    Returns:
        str: 保存したBLOBのファイル名（拡張子付き）

    Raises:
        Exception: アップロードやDB更新に失敗した場合
    """
    try:
        conn_str = get_azure_storage_connection_string()
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service_client.get_container_client(container_name)

        ext = sanitize_filename(img_name)
        blob_name = f"{save_name}{ext}"

        try:
            container_client.upload_blob(name=blob_name, data=img_data, overwrite=True)
        except Exception as e:
            raise Exception(f"BLOBアップロードに失敗しました: {str(e)}")

        return blob_name

    except Exception as e:
        logging.error(str(e))
        raise Exception(f"BLOBアップロードに失敗しました: {str(e)}")


def delete_blob(container_name, blob_name):
    """
    指定したAzure Blob StorageコンテナからBLOBファイルを削除します。

    Parameters:
        container_name (str): 削除対象のAzure Blob Storageコンテナ名
        blob_name (str): 削除するBLOBファイル名

    Returns:
        bool: 削除に成功した場合はTrue、失敗した場合はFalse

    Raises:
        例外は発生せず、失敗時はログに警告を出してFalseを返します。
    """
    try:
        conn_str = get_azure_storage_connection_string()
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)

        blob_client.delete_blob()
        return True
    except Exception as e:
        logging.warning(f"Blob削除失敗: {str(e)}")
        return False


def get_blob_sas_url(container_name, blob_name, expiry_hours=1):
    """
    指定したBLOBファイルのSAS付きURLを生成して返します。

    Parameters:
        container_name (str, optional): コンテナ名
        blob_name (str): SAS URLを発行するBLOBファイル名
        expiry_hours (int, optional): SASトークンの有効期限（時間単位）。デフォルトは1時間

    Returns:
        str: SASトークン付きのBLOBアクセスURL

    Raises:
        Exception: SASトークン生成やURL生成に失敗した場合

    注意:
        この関数はBLOBへの一時的なアクセスURLを発行します。SASトークンの有効期限や権限設定に注意してください。
    """
    try:
        conn_str = get_azure_storage_connection_string()
        blob_service_client = BlobServiceClient.from_connection_string(conn_str)

        # コンテナ名が未指定の場合は定数や環境変数から取得
        if container_name is None:
            raise Exception("コンテナ名が指定されていません")

        # アカウントキーの取得
        credential = getattr(blob_service_client, "credential", None)
        if hasattr(credential, 'account_key'):
            account_key = credential.account_key
        elif isinstance(credential, str):
            account_key = credential
        elif hasattr(blob_service_client, "account_key"):
            account_key = blob_service_client.account_key
        else:
            raise Exception("アカウントキー取得失敗")

        # SASトークン生成
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=expiry_hours)
        )

        url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_token}"
        return url

    except Exception as e:
        logging.error(f"SAS URL生成失敗: {str(e)}")
        raise Exception(f"SAS URL生成失敗: {str(e)}")