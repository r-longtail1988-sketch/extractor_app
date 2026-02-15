import os
import gc
import time
import json
import io
import re

# 【最優先】システム領域への書き込みを避け、すべて /tmp で完結させます
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st

# --- 1. ページ基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")

with st.sidebar:
    st.header("🧬 Edulabo 設定")
    export_format = st.selectbox("保存形式を選択", ["webp", "png"])
    st.divider()
    if st.button("♻️ アプリを再起動"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()
    st.caption("授業刷新・資産化計画 v1.2")

st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("分割PDF対応：メモリを節約しながら1枚ずつ資産化します")

# --- 2. 設定読み込み (Secrets) ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# --- 3. 認証ロジック (ループ防止・強化版) ---
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
    st.info("🔒 資産化を開始するには、Googleドライブへのログインが必要です。")
    st.link_button("🔑 Google アカウントでログインする", auth_url)
    st.stop()

service = get_service()

# --- 4. 解析・保存処理 ---
uploaded_files = st.file_uploader("分割したPDFをアップロード（1ファイルずつがより安定します）", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        # 重いライブラリをボタン押下後に読み込み
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from googleapiclient.http import MediaIoBaseUpload
        import google.generativeai as genai
        from PIL import Image

        genai.configure(api_key=GEMINI_API_KEY)
        vision_model = genai.GenerativeModel('gemini-2.0-flash')

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False # OCRをOFFにしてメモリ負荷を軽減
        pipeline_options.generate_page_images = True # 画像抽出の確実性を向上
        
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
                
                # 図表候補の抽出 (ImportErrorを避ける汎用方式)
                all_images = []
                for item, _ in result.document.iterate_items():
                    if item.label in ["picture", "figure"]:
                        all_images.append(item)
                
                total = len(all_images)
                bar.progress(50)
                
                if total == 0:
                    st.warning(f"⚠️ {uploaded_file.name} から図表は見つかりませんでした。")
                else:
                    status.info(f"🎨 {total}個の図表を確認。AI命名と保存を開始...")
                    for i, item in enumerate(all_images):
                        bar.progress(50 + int((i / total) * 50))
                        
                        # 画像データの確実な取得
                        image_obj = None
                        try:
                            if hasattr(item, 'get_image'): image_obj = item.get_image(result.document)
                            elif hasattr(item, 'image'): image_obj = item.image.pil_image
                        except: pass

                        if image_obj is None: continue
                        
                        # スピード制限(429)回避のため6秒待機
                        if i > 0:
                            status.info(f"🚦 制限回避のため待機中... ({i+1}/{total})")
                            time.sleep(6)

                        # AI(Gemini 2.0 Flash)命名
                        status.info(f"🤖 AIが {i+1}/{total} 個目の画像を確認中...")
                        resp = vision_model.generate_content([
                            "理科教材の図です。内容を20文字以内の日本語で要約し、名称のみ出力してください。", 
                            image_obj
                        ])
                        name = re.sub(r'[\\/:*?"<>|]', '', resp.text.strip())
                        
                        # ドライブ転送
                        status.info(f"☁️ 『{name}』をドライブに保存中...")
                        buf = io.BytesIO()
                        image_obj.save(buf, format=export_format.upper())
                        buf.seek(0)
                        
                        meta = {'name': f"{name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                        media = MediaIoBaseUpload(buf, mimetype=f'image/{export_format}')
                        service.files().create(body=meta, media_body=media).execute()
                        st.write(f"✅ 保存成功: {name}.{export_format}")

                status.success(f"✨ {uploaded_file.name} 完了！")
                bar.empty()
                
            except Exception as e:
                st.error(f"解析中に停止しました: {e}")
            finally:
                # メモリと一時ファイルを徹底的に掃除
                if os.path.exists(temp_path): os.remove(temp_path)
                try: del result
                except: pass
                gc.collect()
