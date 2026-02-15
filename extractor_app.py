import os
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter
from PIL import Image
import io
import json
import re
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# --- ページ基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")
st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("教材資産化計画：ログインに成功すると解析画面に切り替わります")

# --- 設定の読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- 認証チェック関数 (無限ループ防止強化版) ---
def get_authenticated_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    # 1. すでに認証済みの場合は即座にサービスを返す（URLのチェックはしない）
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid:
            return build('drive', 'v3', credentials=creds)
        # 期限切れなら更新を試みる
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state["google_auth_token"] = creds
                return build('drive', 'v3', credentials=creds)
            except:
                st.session_state.pop("google_auth_token")

    # 2. URLを確認し、Googleからの戻り（code）があるかチェック
    auth_code = st.query_params.get("code")
    
    if auth_code:
        # 3. コードがある場合：一度だけ交換を試みる
        try:
            flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
            flow.fetch_token(code=auth_code)
            st.session_state["google_auth_token"] = flow.credentials
            # 【重要】成功したら即座にURLのコードを消してリロード
            st.query_params.clear()
            st.rerun() 
        except Exception:
            # 失敗した（二重使用など）場合はURLを掃除してやり直し
            st.query_params.clear()
            st.rerun()

    # 4. 未ログイン状態：ログインボタンを表示して処理を止める
    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    
    st.warning("🔒 続行するには Google ドライブへのログインが必要です。")
    st.link_button("🔑 Google アカウントでログインする", auth_url)
    st.stop()

# --- AIによる賢い命名 ---
def generate_smart_name(image_bytes, original_name, index):
    img = Image.open(io.BytesIO(image_bytes))
    prompt = "この画像は理科の教材から抽出された図表です。内容を20文字以内で要約し、ファイル名として適切な日本語を生成してください。出力は要約した名称のみとしてください。"
    try:
        response = vision_model.generate_content([prompt, img])
        summary = re.sub(r'[\\/:*?"<>|]', '', response.text.strip())
        return f"{os.path.splitext(original_name)[0]}_{index:02}_{summary}"
    except:
        return f"{os.path.splitext(original_name)[0]}_{index:02}_extracted"

# --- メイン処理 ---
# 認証をチェック（未ログインならここで停止する）
service = get_authenticated_service()

# ログイン成功後のみ表示されるUI
st.sidebar.header("🔧 出力設定")
export_format = st.sidebar.selectbox("保存形式を選択", ["webp", "png"])
if st.sidebar.button("♻️ ログアウト"):
    st.session_state.clear()
    st.query_params.clear()
    st.rerun()

uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        converter = DocumentConverter()
        for uploaded_file in uploaded_files:
            st.info(f"📄 {uploaded_file.name} を解析中...")
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                result = converter.convert(temp_path)
                images_found = 0
                for i, element in enumerate(result.document.figures):
                    images_found += 1
                    image_obj = element.image.pil_image
                    
                    # 命名と保存の実行（実務部分）
                    img_byte_arr = io.BytesIO()
                    image_obj.save(img_byte_arr, format='PNG')
                    smart_name = generate_smart_name(img_byte_arr.getvalue(), uploaded_file.name, i)
                    
                    final_img_byte_arr = io.BytesIO()
                    image_obj.save(final_img_byte_arr, format=export_format.upper())
                    final_img_byte_arr.seek(0)
                    
                    file_metadata = {'name': f"{smart_name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                    media = MediaIoBaseUpload(final_img_byte_arr, mimetype=f'image/{export_format}', resumable=True)
                    service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                    
                    st.write(f"  📸 抽出成功: {smart_name}.{export_format}")

                st.success(f"✅ {uploaded_file.name} の図表を保存しました！")
            except Exception as e:
                st.error(f"解析エラー: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
