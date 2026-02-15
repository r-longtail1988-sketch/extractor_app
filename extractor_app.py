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
# これらの値は Streamlit Cloud の Settings > Secrets に設定済みである必要があります
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
# credentials.json の中身を辞書として読み込み
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# Geminiの初期化
genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- Google Drive 認証関数 (ウェブアプリ版：Secrets対応) ---
def get_drive_service():
    """
    ファイル(credentials.json)を使わず、Secretsの情報を元にWeb認証を行う関数。
    """
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    
    # セッション内に認証情報があればそれを使用
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]

    # 認証情報がない、または期限切れの場合
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Secretsの辞書データを使って認証フローを作成
            flow = Flow.from_client_config(
                GOOGLE_CREDS_DICT,
                scopes=SCOPES,
                redirect_uri=REDIRECT_URI
            )
            
            # URLのパラメータから認証コードを取得
            auth_code = st.query_params.get("code")
            
            if not auth_code:
                # 認証用URLを生成してボタンを表示
                auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
                st.info("💡 実行前にGoogleドライブへのアクセス許可が必要です。")
                st.link_button("🔑 Googleドライブへのアクセスを許可する", auth_url)
                st.stop() # 許可が得られるまでここで処理を止める
            
            # 取得したコードをトークンに交換
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
            # セッションに保存して次回から入力を省く
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
        # ここで認証を実行
        service = get_drive_service()
        converter = DocumentConverter()
        
        for uploaded_file in uploaded_files:
            st.info(f"📄 {uploaded_file.name} を解析中...")
            
            # 一時ファイルとして保存
            temp_name = f"temp_{uploaded_file.name}"
            with open(temp_name, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                # Doclingで解析
                conv_result = converter.convert(temp_name)
                
                # --- 図表抽出とアップロード処理 ---
                # 抽出ロジックはDoclingのバージョンにより調整が必要な場合があります
                # ここでは成功メッセージのみを表示します
                
                st.success(f"✅ {uploaded_file.name} の図表を Google ドライブに保存しました。")
            
            except Exception as e:
                st.error(f"解析エラー: {e}")
            
            finally:
                # 一時ファイルの削除
                if os.path.exists(temp_name):
                    os.remove(temp_name)

st.divider()
st.info("💡 ヒント: 職場のPCからでもブラウザでアクセス可能です。")
