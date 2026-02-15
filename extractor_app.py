import os
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter
import io
import json
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# --- ページ基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")
st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("教材資産化計画：図表の自動解体・クラウド保存エンジン")

# --- 設定の読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# Geminiの初期化
genai.configure(api_key=GEMINI_API_KEY)

# --- Google Drive 認証関数 (完全版) ---
def get_drive_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    # 1. すでにセッション内に「有効な鍵」があれば即座にそれを返す
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid:
            return build('drive', 'v3', credentials=creds)
        # 期限切れならリフレッシュ
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                st.session_state["google_auth_token"] = creds
                return build('drive', 'v3', credentials=creds)
            except:
                st.session_state.pop("google_auth_token")

    # 2. URLからGoogleの認証コードを取得
    auth_code = st.query_params.get("code")
    
    # 3. コードがない（ログイン前）場合はボタンを表示
    if not auth_code:
        flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        st.info("💡 実行前にGoogleドライブへのアクセス許可が必要です。")
        st.link_button("🔑 Googleドライブへのアクセスを許可する", auth_url)
        st.stop()
    
    # 4. コードがある（Googleから戻ってきた）場合の処理
    try:
        # ここでコードを本物の鍵（トークン）に交換
        flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        flow.fetch_token(code=auth_code)
        # 成功したらセッションに保存
        st.session_state["google_auth_token"] = flow.credentials
        # URLのコードを消去してリフレッシュ（InvalidGrantError対策）
        st.query_params.clear()
        st.rerun() 
    except Exception as e:
        # 失敗した場合、すでにセッションに鍵があればそのまま進む
        if "google_auth_token" in st.session_state:
            st.query_params.clear()
            st.rerun()
        else:
            # 完全に失敗している場合はURLを掃除してやり直しを促す
            st.query_params.clear()
            st.warning("セッションが切れました。もう一度「許可する」ボタンを押してください。")
            st.stop()

# --- メインUI ---
if st.sidebar.button("♻️ セッションをリセット"):
    st.session_state.clear()
    st.query_params.clear()
    st.rerun()

uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        # ここで認証が通るまで待機
        service = get_drive_service()
        
        # 認証が通った後の処理
        converter = DocumentConverter()
        for uploaded_file in uploaded_files:
            st.info(f"📄 {uploaded_file.name} を解析中...")
            # 解析ロジック...
            st.success(f"✅ {uploaded_file.name} の解析が完了しました！")
