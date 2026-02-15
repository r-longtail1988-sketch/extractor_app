import os
# システムの制約（書き込み禁止エリア）を避けるための設定（正規の回避策です）
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
import io
import json
import re
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# --- ページ設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")
st.title("🧪 Edulabo PDF Visual Extractor")

# --- 設定読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- 【修正】認証ループを確実に防ぐ関数 ---
def get_authenticated_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    # 1. 既に「メモリ(Session State)」に有効な鍵があるなら、それを使って即座に終了
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid:
            return build('drive', 'v3', credentials=creds)

    # 2. URLを確認し、Googleからの「戻りコード」があるかチェック
    auth_code = st.query_params.get("code")
    
    # 3. コードがある場合（Googleから戻ってきた瞬間）
    if auth_code:
        try:
            flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
            flow.fetch_token(code=auth_code)
            # 成功したらメモリに保存
            st.session_state["google_auth_token"] = flow.credentials
            # 【重要】URLからコードを完全に消去し、真っさらな状態で再起動
            st.query_params.clear()
            st.rerun() 
        except Exception:
            # コードが既に使われていた等のエラー時は、URLを掃除してやり直し
            st.query_params.clear()
            st.rerun()

    # 4. メモリにもURLにも鍵がない場合のみ、ログインボタンを表示
    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    
    st.warning("🔒 続行するには Google ドライブへのログインが必要です。")
    st.link_button("🔑 Google アカウントでログインする", auth_url)
    st.stop()

# --- メイン処理 ---
service = get_authenticated_service()

# ログイン後のUI
st.sidebar.header("🔧 出力設定")
export_format = st.sidebar.selectbox("保存形式を選択", ["webp", "png"])

uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        try:
            # 解析オプション（権限エラーを避けるためOCRは一旦最小限に）
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False 
            
            converter = DocumentConverter(
                format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
            )
            
            for uploaded_file in uploaded_files:
                st.info(f"📄 {uploaded_file.name} を解析中...")
                temp_path = f"/tmp/{uploaded_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                result = converter.convert(temp_path)
                
                images_found = 0
                for i, element in enumerate(result.document.figures):
                    images_found += 1
                    image_obj = element.image.pil_image
                    
                    # Gemini命名 & アップロード
                    final_img_byte_arr = io.BytesIO()
                    image_obj.save(final_img_byte_arr, format=export_format.upper())
                    final_img_byte_arr.seek(0)
                    
                    # 命名（プレースホルダー的な簡易版）
                    file_name = f"{os.path.splitext(uploaded_file.name)[0]}_{i:02}.{export_format}"
                    
                    file_metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
                    media = MediaIoBaseUpload(final_img_byte_arr, mimetype=f'image/{export_format}', resumable=True)
                    service.files().create(body=file_metadata, media_body=media).execute()
                    
                    st.write(f"  📸 保存成功: {file_name}")

                st.success(f"✅ {uploaded_file.name} の解体が完了しました！")
                
        except Exception as e:
            st.error(f"解析エラー: {e}")
