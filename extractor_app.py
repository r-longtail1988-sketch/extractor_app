import os
os.environ["HOME"] = "/tmp"
os.environ["HF_HOME"] = "/tmp/huggingface_cache"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"

import streamlit as st
import json
import io
import re

st.set_page_config(page_title="Edulabo Debug Mode", layout="wide")

with st.sidebar:
    st.header("🧬 Edulabo 設定")
    export_format = st.selectbox("保存形式を選択", ["webp", "png"])
    st.info(f"現在の保存先ID: {st.secrets['DRIVE_FOLDER_ID']}") # IDの確認用
    if st.button("♻️ アプリをリセット"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

st.title("🧪 Edulabo 実況・解析モード")
st.caption("各ステップの成功・失敗をすべて記録します")

# --- 設定読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# --- 認証 (安定版) ---
def get_service():
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
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
        except: pass
        st.query_params.clear()
        st.rerun()
    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.warning("🔒 続行するにはログインが必要です。")
    st.link_button("🔑 Google ログイン", auth_url)
    st.stop()

service = get_service()

# --- 解析処理 ---
uploaded_files = st.file_uploader("PDFを選択", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from googleapiclient.http import MediaIoBaseUpload
        import google.generativeai as genai
        
        genai.configure(api_key=GEMINI_API_KEY)
        vision_model = genai.GenerativeModel('gemini-2.0-flash')

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False 
        converter = DocumentConverter(format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)})

        for uploaded_file in uploaded_files:
            st.subheader(f"📊 {uploaded_file.name} の実況ログ")
            log_area = st.container() # ログをまとめる枠
            
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                st.write("1. PDFの構造を読み解いています...")
                result = converter.convert(temp_path)
                
                # 図表の検索
                all_items = list(result.document.iterate_items())
                st.write(f"2. 全要素数: {len(all_items)} 件を確認")
                
                all_images = [item for item, _ in all_items if item.label in ["picture", "figure"]]
                st.write(f"3. そのうち『図・写真』として認識されたもの: **{len(all_images)} 件**")
                
                if not all_images:
                    st.warning("⚠️ このPDFからは画像として認識できる要素が見つかりませんでした。")
                else:
                    for i, item in enumerate(all_images):
                        st.write(f"--- 🖼️ {i+1}枚目の処理 ---")
                        try:
                            # 画像取得
                            image_obj = item.image.pil_image if hasattr(item, 'image') else item.get_image(result.document)
                            
                            # AI命名
                            st.write("  🤖 AIが名前を考えています...")
                            resp = vision_model.generate_content(["理科教材の図。20文字以内の名称を1つ出力。", image_obj])
                            name = re.sub(r'[\\/:*?"<>|]', '', resp.text.strip())
                            st.write(f"  📝 決定した名前: {name}")
                            
                            # アップロード
                            st.write(f"  ☁️ ドライブ（フォルダID: {DRIVE_FOLDER_ID}）へ転送中...")
                            buf = io.BytesIO()
                            image_obj.save(buf, format=export_format.upper())
                            buf.seek(0)
                            
                            meta = {'name': f"{name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                            media = MediaIoBaseUpload(buf, mimetype=f'image/{export_format}')
                            # ここで実際にGoogleへ送信
                            upload_res = service.files().create(body=meta, media_body=media, fields='id').execute()
                            st.success(f"  ✅ 保存完了！ (Google上のID: {upload_res.get('id')})")
                            
                        except Exception as inner_e:
                            st.error(f"  ❌ この枚数でエラー: {inner_e}")

                st.balloons() # 完了のお祝い
                st.success("✨ すべてのファイルの処理が終わりました！ドライブをリロードしてください。")
            except Exception as e:
                st.error(f"解析エラー: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
