import os
# 【重要】ライブラリが動く前に「ここ以外は触るな」と命令します
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import json
import io
import re

# --- 1. UI基本設定 ---
st.set_page_config(page_title="Edulabo Visual Extractor", layout="wide")

with st.sidebar:
    st.header("🧬 Edulabo 設定")
    export_format = st.selectbox("保存形式を選択", ["webp", "png"])
    if st.button("♻️ アプリをリセット"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("解析エンジンの負荷を最小限に抑えた『安定モード』で動作中")

# --- 2. 設定読み込み (Secrets) ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# --- 3. 認証ロジック (URLのゴミを即座に消す仕様) ---
def get_service():
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
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

service = get_service()

# --- 4. 解析・保存処理 (重いライブラリはここで初めて読み込む) ---
uploaded_files = st.file_uploader("PDFをアップロード", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        # 重いライブラリをここで読み込むことで、起動時のパンクを防ぎます
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from googleapiclient.http import MediaIoBaseUpload
        import google.generativeai as genai
        from PIL import Image

        genai.configure(api_key=GEMINI_API_KEY)
        vision_model = genai.GenerativeModel('gemini-2.0-flash')

        # パンク回避の最重要設定：ダウンロードを伴うOCRを完全にOFFにする
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False 
        converter = DocumentConverter(
            format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
        )

        for uploaded_file in uploaded_files:
            # 進捗表示用の枠
            status = st.empty()
            bar = st.progress(0)
            
            status.info(f"📄 {uploaded_file.name} を準備中...")
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                status.info(f"🔍 {uploaded_file.name} の構造を解析しています...")
                bar.progress(30)
                result = converter.convert(temp_path)
                
                figures = result.document.figures
                total = len(figures)
                bar.progress(50)
                
                if total == 0:
                    st.warning(f"⚠️ {uploaded_file.name} から図表が見つかりませんでした。")
                else:
                    status.info(f"🎨 {total}個の図表を抽出。AI命名と保存を開始...")
                    for i, fig in enumerate(figures):
                        # 進捗更新
                        prog = 50 + int((i / total) * 50)
                        bar.progress(prog)
                        
                        img = fig.image.pil_image
                        
                        # AI命名
                        status.info(f"🤖 AIが {i+1}/{total} 個目の名前を検討中...")
                        buf = io.BytesIO()
                        img.save(buf, format='PNG')
                        
                        resp = vision_model.generate_content([
                            "理科教材の図。20文字以内の日本語で具体的なファイル名を作成せよ。名称のみ出力。", 
                            img
                        ])
                        name = re.sub(r'[\\/:*?"<>|]', '', resp.text.strip())
                        
                        # 保存
                        status.info(f"☁️ {name} をドライブに転送中...")
                        out_buf = io.BytesIO()
                        img.save(out_buf, format=export_format.upper())
                        out_buf.seek(0)
                        
                        meta = {'name': f"{name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                        media = MediaIoBaseUpload(out_buf, mimetype=f'image/{export_format}')
                        service.files().create(body=meta, media_body=media).execute()
                        
                        st.write(f"✅ 保存成功: {name}")

                status.success(f"✨ {uploaded_file.name} 完了！")
                bar.empty()
            except Exception as e:
                st.error(f"解析エラー: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
