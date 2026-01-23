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
                current_name = st.session_state['current_sheet_name']
                st.session_state['all_sheets'][current_name] = last_df
                
                st.success("已撤销！")
                st.rerun()
            else:
                st.warning("无法再撤销了")
    
    with col2:
        st.info(f"正在编辑: **{st.session_state['current_sheet_name']}** | 行数: {st.session_state['df'].shape[0]}")

    st.dataframe(st.session_state['df'].head(8), use_container_width=True)

# ==========================================
# 4. AI 逻辑 (V18 Industry Logic)
# ==========================================
def process_data_with_ai(user_prompt):
    if not api_key:
        st.error("❌ 未找到 API Key，请检查 Secrets 配置或手动输入")
        return

    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = """
    You are an expert Python Data Scientist for the Energy/Power industry.
    
    【Output Rules - STRICT】
    1. Output ONLY valid Python code. NO markdown. NO explanation.
    2. The code MUST contain `def process_step(df):`.
    
    【Industry Logic】
    1. **Time**: 01:00 represents the END of the period.
    2. **Resampling**: ALWAYS use `df.resample(..., closed='right', label='right')`.
    3. **24:00**: Treat as end of day.
    
    【Smart Guard】
    - If df is empty or not time-series, return df.
    
    【Task】
    Generate `def process_step(df):` to fulfill the user's request.
    """

    data_preview = st.session_state['df'].head(5).to_markdown()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Current Sheet: {st.session_state['current_sheet_name']}\nData Preview:\n{data_preview}\n\nInstruction: {user_prompt}"}
    ]

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.1
        )
        return response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# ==========================================
# 5. 聊天与执行
# ==========================================
if st.session_state['df'] is not None:
    user_input = st.chat_input(f"对 {st.session_state['current_sheet_name']} 下达指令...")

    if user_input:
        st.session_state['chat_history'].append({"role": "user", "content": user_input})
        st.session_state['history'].append(st.session_state['df'].copy(deep=True))
        
        with st.spinner("AI 正在思考..."):
            code = process_data_with_ai(user_input)
        
        if code:
            try:
                local_vars = {'pd': pd, 'np': pd.numpy}
                exec(code, local_vars)
                process_step = local_vars['process_step']
                new_df = process_step(st.session_state['df'])
                
                st.session_state['df'] = new_df
                st.session_state['all_sheets'][st.session_state['current_sheet_name']] = new_df
                
                st.session_state['chat_history'].append({"role": "assistant", "content": f"✅ {st.session_state['current_sheet_name']} 处理完成"})
                st.rerun()
                
            except Exception as e:
                st.error(f"代码执行错误: {e}")
                st.session_state['df'] = st.session_state['history'].pop() # 回滚

    for msg in st.session_state['chat_history']:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

# ==========================================
# 6. 下载
# ==========================================
if st.session_state['df'] is not None:
    st.markdown("---")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for name, sheet_df in st.session_state['all_sheets'].items():
            if name == st.session_state['current_sheet_name']:
                st.session_state['df'].to_excel(writer, sheet_name=name)
            else:
                sheet_df.to_excel(writer, sheet_name=name, index=False)
                
    st.download_button(
        label="📥 下载最终结果",
        data=output.getvalue(),
        file_name="processed_result.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
