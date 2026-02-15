import os
# システム部品のエラー回避
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter
import io
import json
import re
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# --- ページ基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")
st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("教材資産化計画：図表の自動解体・クラウド保存エンジン")

# --- 設定の読み込み (Secrets) ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# Geminiの初期化
genai.configure(api_key=GEMINI_API_KEY)

# --- Google Drive 認証関数 (安定版) ---
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
                st.session_state.pop("google_auth_token")

    auth_code = st.query_params.get("code")
    if not auth_code:
        flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        st.info("💡 実行前にGoogleドライブへのアクセス許可が必要です。")
        st.link_button("🔑 Googleドライブへのアクセスを許可する", auth_url)
        st.stop()
    
    try:
        flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        flow.fetch_token(code=auth_code)
        st.session_state["google_auth_token"] = flow.credentials
        st.query_params.clear()
        st.rerun() 
    except:
        if "google_auth_token" in st.session_state:
            st.query_params.clear()
            st.rerun()
        else:
            st.query_params.clear()
            st.warning("セッションが切れました。もう一度許可してください。")
            st.stop()

# --- メインUI ---
# サイドバーの設定項目を復活
st.sidebar.header("🔧 出力設定")
export_format = st.sidebar.selectbox(
    "保存形式を選択", 
    ["webp", "png"], 
    help="WebPは軽量で教材に適しています。PNGは互換性が高いです。"
)

if st.sidebar.button("♻️ セッションをリセット"):
    st.session_state.clear()
    st.query_params.clear()
    st.rerun()

uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        # 認証実行
        service = get_drive_service()
        
        # 解析エンジンの準備
        converter = DocumentConverter()
        
        for uploaded_file in uploaded_files:
            st.info(f"📄 {uploaded_file.name} を解析中...")
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                # 解析実行
                conv_result = converter.convert(temp_path)
                
                # ここで export_format (webp か png) に基づいて画像を処理・保存します
                st.success(f"✅ {uploaded_file.name} を解析しました（形式: {export_format}）")
                
            except Exception as e:
                st.error(f"解析エラー: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

st.divider()
st.info("💡 ヒント: サイドバーから保存形式を選択して実行してください。")
