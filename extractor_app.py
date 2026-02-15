import os
# 【最優先】すべてのAIモデルと一時データの置き場所を /tmp に完全に隔離します
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"
# 今回のエラーの主犯であるOCRエンジンの保存先も強制指定
os.environ["RAPIDOCR_MODEL_PATH"] = "/tmp/rapidocr_models"

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

# --- ページ設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")
st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("教材資産化計画：解析エンジンの「置き場所」を完全に修正しました")

# --- Secrets読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

genai.configure(api_key=GEMINI_API_KEY)
vision_model = genai.GenerativeModel('gemini-2.0-flash')

# --- 認証チェック (安定版) ---
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

    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.warning("🔒 続行するには Google ドライブへのログインが必要です。")
    st.link_button("🔑 Google アカウントでログインする", auth_url)
    st.stop()

# --- メイン処理 ---
service = get_authenticated_service()

st.sidebar.header("🔧 出力設定")
export_format = st.sidebar.selectbox("保存形式を選択", ["webp", "png"])

uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        try:
            # 【重要】解析エンジンが「システムフォルダ」を触らないよう設定を注入
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False  # 権限エラー回避のため一旦OCRをOFF。図表抽出はこれでも可能です。
            
            converter = DocumentConverter(
                format_options={
                    "pdf": PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
            
            for uploaded_file in uploaded_files:
                st.info(f"📄 {uploaded_file.name} を解析中...")
                temp_path = f"/tmp/{uploaded_file.name}"
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # PDF解析の実行
                result = converter.convert(temp_path)
                
                images_found = 0
                for i, element in enumerate(result.document.figures):
                    images_found += 1
                    image_obj = element.image.pil_image
                    
                    # AI命名 & ドライブ保存（ここは前回と同じ）
                    img_byte_arr = io.BytesIO()
                    image_obj.save(img_byte_arr, format='PNG')
                    
                    # Gemini命名
                    prompt = "この画像の内容を20文字以内で要約し、ファイル名として適切な日本語を生成してください。"
                    response = vision_model.generate_content([prompt, image_obj])
                    smart_name = re.sub(r'[\\/:*?"<>|]', '', response.text.strip())
                    
                    # アップロード
                    final_img_byte_arr = io.BytesIO()
                    image_obj.save(final_img_byte_arr, format=export_format.upper())
                    final_img_byte_arr.seek(0)
                    
                    file_metadata = {'name': f"{smart_name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                    media = MediaIoBaseUpload(final_img_byte_arr, mimetype=f'image/{export_format}', resumable=True)
                    service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                    
                    st.write(f"  📸 保存成功: {smart_name}")

                st.success(f"✅ {uploaded_file.name} から {images_found} 個の図表を抽出・保存しました！")
                
        except Exception as e:
            st.error(f"解析エラー: {e}")
