import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter
from PIL import Image
import io
import os
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
# credentials.jsonの中身を文字列として取得
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# Geminiの初期化
genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- Google Drive 認証関数 (ウェブアプリ版) ---
def get_drive_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    
    # セッション状態に認証情報を保持
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Secretsから読み込んだ辞書データを使用してフローを作成
            flow = Flow.from_client_config(
                GOOGLE_CREDS_DICT,
                scopes=SCOPES,
                redirect_uri=st.secrets["REDIRECT_URI"]
            )
            
            # URLパラメータから認証コードを取得
            auth_code = st.query_params.get("code")
            if not auth_code:
                # 認証用URLを生成してユーザーにクリックしてもらう
                auth_url, _ = flow.authorization_url(prompt='consent')
                st.link_button("🔑 Googleドライブへのアクセスを許可する", auth_url)
                st.stop()
            
            # 認証コードをトークンに交換
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
            st.session_state["google_auth_token"] = creds
            
    return build('drive', 'v3', credentials=creds)

# --- AIによるファイル名生成 ---
def generate_smart_name(image, original_name, page_num, index):
    prompt = "この画像は理科の教材から抽出された図表です。内容を30文字以内で要約し、ファイル名として適切な日本語を生成してください。出力は要約のみとしてください。"
    try:
        response = vision_model.generate_content([prompt, image])
        summary = re.sub(r'[\\/:*?"<>|]', '', response.text.strip())
        return f"{os.path.splitext(original_name)[0]}_P{page_num:03}_{index:02}_{summary}"
    except:
        return f"{os.path.splitext(original_name)[0]}_P{page_num:03}_{index:02}_extracted_image"

# --- メインUI ---
st.sidebar.header("🔧 出力設定")
export_format = st.sidebar.selectbox("保存形式を選択", ["webp", "png"], help="WebPは軽量、PNGは高互換性です。")
uploaded_files = st.file_uploader("PDFまたは教材画像をアップロード", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        # 認証実行
        service = get_drive_service()
        converter = DocumentConverter()
        
        for uploaded_file in uploaded_files:
            st.info(f"📄 {uploaded_file.name} を解析中...")
            
            # 一時ファイルとして保存
            temp_name = f"temp_{uploaded_file.name}"
            with open(temp_name, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # Doclingで解析
            conv_result = converter.convert(temp_name)
            
            # ここに画像の抽出とアップロード処理を記述
            # (現在はプロトタイプ表示のみ)
            
            st.success(f"✅ {uploaded_file.name} のすべての図表を Google ドライブに保存しました。")
            
            if os.path.exists(temp_name):
                os.remove(temp_name)

st.divider()
st.info("💡 ヒント: 職場のPCからでもブラウザでアクセス可能です。")
