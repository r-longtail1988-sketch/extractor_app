import os
# システムの書き込み制限とキャッシュ場所の強制固定
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import google.generativeai as genai
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from PIL import Image
import io
import json
import re
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

# --- 1. UI基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")

with st.sidebar:
    st.header("🧬 Edulabo 設定")
    export_format = st.selectbox("保存形式を選択", ["webp", "png"])
    st.divider()
    if st.button("♻️ ログアウト/リセット"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("進捗状況をリアルタイムで表示します")

# --- 2. 設定読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- 3. 認証ロジック ---
def get_authenticated_service():
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid:
            return build('drive', 'v3', credentials=creds)

    auth_code = st.query_params.get("code")
    if auth_code:
        try:
            flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
            flow.fetch_token(code=auth_code)
            st.session_state["google_auth_token"] = flow.credentials
            st.query_params.clear()
            st.rerun() 
        except:
            st.query_params.clear()
            st.rerun()

    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.warning("🔒 続行するには Google ドライブへのログインが必要です。")
    st.link_button("🔑 Google アカウントでログインする", auth_url)
    st.stop()

service = get_authenticated_service()

# --- 4. メイン処理 ---
uploaded_files = st.file_uploader("PDFをアップロードしてください", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        try:
            # 安定化のための設定：OCRを完全にスキップ
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False 
            converter = DocumentConverter(
                format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
            )
            
            for uploaded_file in uploaded_files:
                # 進捗表示用の枠を作成
                status_text = st.empty()
                progress_bar = st.progress(0)
                
                status_text.info(f"📄 {uploaded_file.name} を読み込み中...")
                temp_path = f"/tmp/{uploaded_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # PDF解析
                status_text.info(f"🔍 {uploaded_file.name} を構造解析中（これに時間がかかります）...")
                progress_bar.progress(20)
                result = converter.convert(temp_path)
                
                figures = result.document.figures
                total_figs = len(figures)
                progress_bar.progress(50)
                
                if total_figs == 0:
                    st.warning(f"⚠️ {uploaded_file.name} から図表が見つかりませんでした。")
                else:
                    status_text.info(f"🎨 {total_figs}個の図表を抽出しました。AI命名と保存を開始します...")
                    
                    for i, element in enumerate(figures):
                        # 進捗率の計算
                        current_progress = 50 + int((i / total_figs) * 50)
                        progress_bar.progress(current_progress)
                        
                        image_obj = element.image.pil_image
                        
                        # AI命名
                        status_text.info(f"🤖 AIが {i+1}/{total_figs} 個目の名前を考えています...")
                        img_byte_arr = io.BytesIO()
                        image_obj.save(img_byte_arr, format='PNG')
                        
                        prompt = "理科教材の図表です。20文字以内の日本語で、ファイル名に適した具体的な名称を1つだけ出力してください。"
                        response = vision_model.generate_content([prompt, image_obj])
                        smart_name = re.sub(r'[\\/:*?"<>|]', '', response.text.strip())
                        
                        # ドライブ保存
                        status_text.info(f"☁️ {smart_name} を保存中...")
                        final_img_byte_arr = io.BytesIO()
                        image_obj.save(final_img_byte_arr, format=export_format.upper())
                        final_img_byte_arr.seek(0)
                        
                        file_metadata = {'name': f"{smart_name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                        media = MediaIoBaseUpload(final_img_byte_arr, mimetype=f'image/{export_format}')
                        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                        
                        st.write(f"✅ 保存成功: {smart_name}.{export_format}")

                status_text.success(f"✨ {uploaded_file.name} のすべての処理が完了しました！")
                progress_bar.empty() # バーを消す
                
        except Exception as e:
            st.error(f"解析エラー: {e}")
            st.info("💡 PDFが大きすぎるか、構造が複雑すぎる可能性があります。")
