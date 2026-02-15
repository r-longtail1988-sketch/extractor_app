import os
import gc
import time
import json
import io
import re

# 書き込み制限とキャッシュの隔離
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"

import streamlit as st

# --- 1. UI設定 ---
st.set_page_config(page_title="Edulabo Extractor - Final", layout="wide")

with st.sidebar:
    st.header("🧬 Edulabo 設定")
    export_format = st.selectbox("保存形式を選択", ["webp", "png"])
    if st.button("♻️ アプリを再起動"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("スピード制限(429)への『自動リトライ機能』を搭載しました")

# --- 2. 設定読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# --- 3. 認証ロジック ---
def get_service():
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid: return build('drive', 'v3', credentials=creds)
    auth_code = st.query_params.get("code")
    if auth_code:
        try:
            flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
            flow.fetch_token(code=auth_code)
            st.session_state["google_auth_token"] = flow.credentials
        except: pass
        st.query_params.clear()
        st.rerun()
    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.info("🔒 資産化を開始するにはGoogleログインが必要です。")
    st.link_button("🔑 ログイン", auth_url)
    st.stop()

service = get_service()

# --- 4. 解析・保存処理 ---
uploaded_files = st.file_uploader("分割PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from googleapiclient.http import MediaIoBaseUpload
        import google.generativeai as genai
        from PIL import Image

        genai.configure(api_key=GEMINI_API_KEY)
        vision_model = genai.GenerativeModel('gemini-2.0-flash')

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False 
        pipeline_options.generate_page_images = True 
        converter = DocumentConverter(format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)})

        for uploaded_file in uploaded_files:
            status = st.empty()
            bar = st.progress(0)
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f: f.write(uploaded_file.getbuffer())
            
            try:
                status.info(f"🔍 {uploaded_file.name} を構造解析中...")
                bar.progress(30)
                result = converter.convert(temp_path)
                
                # 図表候補の抽出 (ImportError回避)
                all_items = [(item, prov) for item, prov in result.document.iterate_items() if item.label in ["picture", "figure"]]
                total = len(all_items)
                bar.progress(50)
                
                if total == 0:
                    st.warning(f"⚠️ 図表が見つかりませんでした。")
                else:
                    for i, (item, prov) in enumerate(all_items):
                        bar.progress(50 + int((i / total) * 50))
                        
                        image_obj = None
                        try:
                            if hasattr(item, 'get_image'): image_obj = item.get_image(result.document)
                            elif hasattr(item, 'image'): image_obj = item.image.pil_image
                        except: pass

                        if image_obj is None: continue #

                        # AI命名 (リトライループ搭載)
                        name = f"figure_{i+1}" # デフォルト名
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                status.info(f"🤖 AIが {i+1}/{total} 個目を確認中... (試行 {attempt+1})")
                                resp = vision_model.generate_content(["理科教材の図。20文字以内の名称を1つ出力。", image_obj])
                                name = re.sub(r'[\\/:*?"<>|]', '', resp.text.strip())
                                break # 成功したらループ脱出
                            except Exception as e:
                                if "429" in str(e) or "quota" in str(e).lower():
                                    status.warning(f"🚦 制限に達しました。60秒待機して再開します... ({attempt+1}/{max_retries})")
                                    time.sleep(60) #
                                else:
                                    st.error(f"AIエラー: {e}")
                                    break
                        
                        # ドライブ転送
                        status.info(f"☁️ 『{name}』を保存中...")
                        buf = io.BytesIO()
                        image_obj.save(buf, format=export_format.upper())
                        buf.seek(0)
                        
                        meta = {'name': f"{name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                        media = MediaIoBaseUpload(buf, mimetype=f'image/{export_format}')
                        service.files().create(body=meta, media_body=media).execute()
                        st.write(f"✅ 保存成功: {name}.{export_format}")
                        
                        # 次の処理まで少し休憩
                        time.sleep(5)

                status.success(f"✨ {uploaded_file.name} 完了！")
                bar.empty()
                
            except Exception as e:
                st.error(f"解析中にエラー: {e}")
            finally:
                if os.path.exists(temp_path): os.remove(temp_path)
                try: del result
                except: pass
                gc.collect()
