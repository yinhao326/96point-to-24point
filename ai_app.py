import streamlit as st
import pandas as pd
import io
import openai

# ==========================================
# 1. 页面配置与初始化
# ==========================================
st.set_page_config(page_title="Excel AI 智能助手 (Pro)", layout="wide")
st.title("⚡ Excel AI 智能助手 (Pro)")

# 初始化 Session State
if 'df' not in st.session_state:
    st.session_state['df'] = None
if 'history' not in st.session_state:
    st.session_state['history'] = []
if 'chat_history' not in st.session_state:
    st.session_state['chat_history'] = []
if 'all_sheets' not in st.session_state:
    st.session_state['all_sheets'] = {}
if 'current_sheet_name' not in st.session_state:
    st.session_state['current_sheet_name'] = ""

# ==========================================
# 2. 侧边栏：自动加载密钥 & 文件上传
# ==========================================
with st.sidebar:
    st.header("⚙️ 设置")
    
    # --- 🔑 核心修正：优先从 Secrets 读取 API Key ---
    api_key = None
    if "DEEPSEEK_API_KEY" in st.secrets:
        api_key = st.secrets["DEEPSEEK_API_KEY"]
        st.success("🔑 API Key 已从 Secrets 自动加载")
    else:
        # 如果没配置 Secrets，才显示输入框 (兼容本地测试)
        api_key = st.text_input("请输入 DeepSeek API Key", type="password")
        if not api_key:
            st.warning("检测到未配置 Secrets，请手动输入 Key")

    base_url = "https://api.deepseek.com"
    
    st.markdown("---")
    uploaded_file = st.file_uploader("上传 Excel 文件", type=["xlsx", "xls"])

    # --- 文件加载逻辑 ---
    if uploaded_file:
        if 'uploaded_filename' not in st.session_state or st.session_state['uploaded_filename'] != uploaded_file.name:
            try:
                all_sheets = pd.read_excel(uploaded_file, sheet_name=None)
                st.session_state['all_sheets'] = all_sheets
                st.session_state['uploaded_filename'] = uploaded_file.name
                
                # 默认选中第一个
                first_sheet = list(all_sheets.keys())[0]
                st.session_state['current_sheet_name'] = first_sheet
                st.session_state['df'] = all_sheets[first_sheet].copy()
                st.session_state['history'] = [] 
                st.session_state['chat_history'] = []
                
                st.success(f"已加载: {uploaded_file.name}")
            except Exception as e:
                st.error(f"读取失败: {e}")

    # --- 工作表切换器 ---
    if st.session_state['all_sheets']:
        st.markdown("### 📑 选择工作表")
        sheet_names = list(st.session_state['all_sheets'].keys())
        
        selected_sheet = st.selectbox(
            "当前处理：", 
            options=sheet_names, 
            index=sheet_names.index(st.session_state['current_sheet_name']) if st.session_state['current_sheet_name'] in sheet_names else 0
        )

        # 切换逻辑
        if selected_sheet != st.session_state['current_sheet_name']:
            old_name = st.session_state['current_sheet_name']
            if st.session_state['df'] is not None:
                st.session_state['all_sheets'][old_name] = st.session_state['df'].copy()
                st.toast(f"已自动保存 {old_name} 进度", icon="💾")
            
            st.session_state['current_sheet_name'] = selected_sheet
            st.session_state['df'] = st.session_state['all_sheets'][selected_sheet].copy()
            st.session_state['history'] = [] # 换表清空撤销栈
            st.rerun()

# ==========================================
# 3. 核心功能区
# ==========================================
if st.session_state['df'] is not None:
    
    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("↩️ 撤销上一步", use_container_width=True):
            if len(st.session_state['history']) > 0:
                last_df = st.session_state['history'].pop()
                st.session_state['df'] = last_df
                if st.session_state['chat_history']:
                    st.session_state['chat_history'].pop()
                
                # 同步到全家福
                current_name = st.session_state['current
