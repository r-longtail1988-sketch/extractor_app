import os
# 【重要】ライブラリがデータを書き込める場所を指定します（エラー回避用）
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter
from PIL import Image
import io
import re
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# --- ページ基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")
st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("教材資産化計画：図表の自動解体・クラウド保存エンジン")

# --- 設定の読み込み (Secretsから) ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# Geminiの初期化
genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- Google Drive 認証関数 ---
def get_drive_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid:
            return build('drive', 'v3', credentials=creds)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state["google_auth_token"] = creds
                return build('drive', 'v3', credentials=creds)
            except:
                pass

    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_code = st.query_params.get("code")
    
    if not auth_code:
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        st.info("💡 実行前にGoogleドライブへのアクセス許可が必要です。")
        st.link_button("🔑 Googleドライブへのアクセスを許可する", auth_url)
        st.stop()
    
    try:
        flow.fetch_token(code=auth_code)
        st.session_state["google_auth_token"] = flow.credentials
        st.query_params.clear()
        st.rerun()
    except:
        st.query_params.clear()
        st.error("認証に失敗しました。もう一度やり直してください。")
        st.stop()

# --- AIによるファイル名生成 ---
def generate_smart_name(image, original_name, page_num, index):
    prompt = "この画像は理科の教材から抽出された図表です。内容を30文字以内で要約し、ファイル名として適切な日本語を生成してください。出力は要約のみとしてください。"
    try:
        response = vision_model.generate_content([prompt, image])
        summary = re.sub(r'[\\/:*?"<>|]', '', response.text.strip())
        return f"{os.path.splitext(original_name)[0]}_P{page_num:03}_{index:02}_{summary}"
    except:
        return f"{os.path.splitext(original_name)[0]}_P{page_num:03}_{index:02}_extracted"

# --- メインUI ---
st.sidebar.header("🔧 出力設定")
export_format = st.sidebar.selectbox("保存形式を選択", ["webp", "png"])
uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        service = get_drive_service()
        # ここで解析エンジンの読み込み（環境変数の設定により /tmp を使います）
        converter = DocumentConverter()
        
        for uploaded_file in uploaded_files:
            st.info(f"📄 {uploaded_file.name} を解析中...")
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                # PDFの解析実行
                conv_result = converter.convert(temp_path)
                
                # ここにGoogleドライブへの保存処理（MediaIoBaseUpload等）が入ります
                # まずは解析がエラーなく通るかを確認しましょう
                
                st.success(f"✅ {uploaded_file.name} の解析が完了しました！")
            except Exception as e:
                st.error(f"解析エラー: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

st.divider()
st.info("💡 ヒント: 初回の解析はモデルの準備に少し時間がかかる場合があります。")
