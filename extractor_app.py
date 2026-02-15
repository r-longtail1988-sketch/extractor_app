import os
# 【正規の設定】書き込み制限を回避し、メモリ負荷を下げるための環境設定
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
    st.divider()
    if st.button("♻️ ログアウト/初期化"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

st.title("🧪 Edulabo PDF Visual Extractor")
st.caption("ログインループ防止機能を強化した『教材資産化』エンジン")

# --- 2. 設定読み込み ---
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]
GOOGLE_CREDS_DICT = json.loads(st.secrets["GOOGLE_CREDENTIALS_JSON"])

# --- 3. 認証ロジック (ループ防止・強化版) ---
def get_service():
    from googleapiclient.discovery import build
    from google_auth_oauthlib.flow import Flow
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    # すでにメモリにログイン情報がある場合は、URLのことは忘れて進む
    if "google_auth_token" in st.session_state:
        creds = st.session_state["google_auth_token"]
        if creds and creds.valid:
            return build('drive', 'v3', credentials=creds)

    # URLからコードを取得
    auth_code = st.query_params.get("code")
    
    if auth_code:
        # コードがあったら、即座に「URLの掃除」を予約しつつ処理
        try:
            flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
            flow.fetch_token(code=auth_code)
            st.session_state["google_auth_token"] = flow.credentials
        except Exception as e:
            # コードが使用済みなどのエラー時は、静かにスルーしてボタン表示へ
            st.warning("以前のログイン情報が古くなっています。再度ログインしてください。")
        
        # 【重要】成功・失敗に関わらずURLを真っさらにして再起動
        st.query_params.clear()
        st.rerun()

    # ログインボタンの表示
    flow = Flow.from_client_config(GOOGLE_CREDS_DICT, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    
    st.info("🔒 教材の資産化を開始するには、Googleドライブへのログインが必要です。")
    st.link_button("🔑 Google アカウントでログインする", auth_url)
    st.stop()

service = get_service()

# --- 4. メイン処理 (進捗バー付き) ---
uploaded_files = st.file_uploader("PDFをアップロードしてください", type=["pdf"], accept_multiple_files=True)

if st.button("🚀 教材の解体と保存を開始"):
    if not uploaded_files:
        st.error("ファイルをアップロードしてください。")
    else:
        # パンク防止のため、ここで重いライブラリを読み込む
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from googleapiclient.http import MediaIoBaseUpload
        import google.generativeai as genai
        from PIL import Image

        genai.configure(api_key=GEMINI_API_KEY)
        vision_model = genai.GenerativeModel('gemini-2.0-flash')

        # メモリパンク（Oh no.）防止のためOCRはOFF
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False 
        converter = DocumentConverter(
            format_options={"pdf": PdfFormatOption(pipeline_options=pipeline_options)}
        )

        for uploaded_file in uploaded_files:
            status_text = st.empty()
            progress_bar = st.progress(0)
            
            status_text.info(f"📄 {uploaded_file.name} を準備中...")
            temp_path = f"/tmp/{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                status_text.info(f"🔍 {uploaded_file.name} を解析しています...")
                progress_bar.progress(30)
                result = converter.convert(temp_path)
                
                figures = result.document.figures
                total_figs = len(figures)
                progress_bar.progress(50)
                
                if total_figs == 0:
                    st.warning(f"⚠️ {uploaded_file.name} から図表は見つかりませんでした。")
                else:
                    status_text.info(f"🎨 {total_figs}個の図表を抽出完了。AI命名と保存を開始します...")
                    
                    for i, element in enumerate(figures):
                        # 進捗更新
                        current_progress = 50 + int((i / total_figs) * 50)
                        progress_bar.progress(current_progress)
                        
                        image_obj = element.image.pil_image
                        
                        # AI(Gemini 2.0 Flash)による命名
                        status_text.info(f"🤖 AIが {i+1}/{total_figs} 個目の画像を確認中...")
                        prompt = "理科教材の図です。内容を20文字以内の日本語で要約し、ファイル名を作成してください。名称のみ出力してください。"
                        response = vision_model.generate_content([prompt, image_obj])
                        smart_name = re.sub(r'[\\/:*?"<>|]', '', response.text.strip())
                        
                        # ドライブ保存
                        status_text.info(f"☁️ 『{smart_name}』をドライブに保存中...")
                        final_img_buf = io.BytesIO()
                        image_obj.save(final_img_buf, format=export_format.upper())
                        final_img_buf.seek(0)
                        
                        file_metadata = {'name': f"{smart_name}.{export_format}", 'parents': [DRIVE_FOLDER_ID]}
                        media = MediaIoBaseUpload(final_img_buf, mimetype=f'image/{export_format}')
                        service.files().create(body=file_metadata, media_body=media).execute()
                        
                        st.write(f"✅ 保存成功: {smart_name}.{export_format}")

                status_text.success(f"✨ {uploaded_file.name} のすべての処理が完了しました！")
                progress_bar.empty()
                
            except Exception as e:
                st.error(f"解析中にエラーが発生しました: {e}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
