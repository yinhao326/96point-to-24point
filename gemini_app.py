import streamlit as st
import pandas as pd
import numpy as np
import io
import re
# 1. 引入 Google 的库
import google.generativeai as genai 

# ================= 配置区域 =================
if "GEMINI_API_KEY" in st.secrets:
    # 2. 配置 Gemini
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("请在 Secrets 中配置 GEMINI_API_KEY")
    st.stop()

# 3. 初始化模型 (推荐使用 gemini-1.5-pro，逻辑最强)
model = genai.GenerativeModel('gemini-1.5-pro')

st.set_page_config(page_title="AI 数据分析台 (Gemini 引擎)", layout="wide")

# ... (中间的 session_state 初始化、UI上传文件代码保持不变，直接复用 V28 即可) ...
# ... (clean_energy_time 函数也可以保留，作为备用) ...

# ================= 核心修改：AI 调用部分 =================

# ================= 3. 全局状态管理 =================
# 初始化所有 Session State，防止报错
keys = ["current_df", "chat_history", "file_hash", "macros", 
        "last_successful_code", "last_successful_explanation", 
        "all_sheets", "current_sheet_name", "history"]

for key in keys:
    if key not in st.session_state:
        if key == "macros" or key == "all_sheets": st.session_state[key] = {}
        elif key in ["chat_history", "history"]: st.session_state[key] = []
        elif key == "current_sheet_name": st.session_state[key] = ""
        else: st.session_state[key] = None

# ================= 4. 侧边栏 (文件上传与设置) =================
with st.sidebar:
    st.header("🧠 模型选择")
    model_map = {
        "DeepSeek-V3 (快速/稳定)": "deepseek-chat",
        "DeepSeek-R1 (深度推理)": "deepseek-reasoner"
    }
    selected_model_label = st.radio("选择大脑：", list(model_map.keys()))
    selected_model = model_map[selected_model_label]
    
    st.divider()
    st.header("📂 文件上传区")
    uploaded_file = st.file_uploader("上传 Excel/CSV (支持宽表/窄表)", type=["xlsx", "xls", "csv"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                if uploaded_file.name.endswith('.csv'):
                    all_sheets = {'Sheet1': pd.read_csv(uploaded_file)}
                else:
                    all_sheets = pd.read_excel(uploaded_file, sheet_name=None)
                
                st.session_state.all_sheets = all_sheets
                st.session_state.file_hash = current_hash
                first_sheet = list(all_sheets.keys())[0]
                st.session_state.current_sheet_name = first_sheet
                st.session_state.current_df = all_sheets[first_sheet].copy()
                st.session_state.chat_history = [] 
                st.session_state.history = [] 
                st.session_state.last_successful_code = None
                
                # 初始欢迎语
                st.session_state.chat_history.append({
                    "role": "assistant", 
                    "content": f"✅ **{uploaded_file.name}** 加载成功。\n\n我已准备好处理 **24:00** 格式数据，无论是宽表（日期在表头）还是长表（日期在列），我都能自动识别。"
                })
                st.rerun()
            except Exception as e:
                st.error(f"❌ 读取失败: {e}")

    # 多 Sheet 切换
    if st.session_state.all_sheets:
        st.divider()
        sheet_names = list(st.session_state.all_sheets.keys())
        try: curr_idx = sheet_names.index(st.session_state.current_sheet_name)
        except: curr_idx = 0
        sel_sheet = st.selectbox("当前工作表", sheet_names, index=curr_idx)
        if sel_sheet != st.session_state.current_sheet_name:
            st.session_state.current_sheet_name = sel_sheet
            st.session_state.current_df = st.session_state.all_sheets[sel_sheet].copy()
            st.session_state.history = []
            st.rerun()
            
    if st.button("🔥 重置工作区", type="primary"):
        st.session_state.file_hash = None
        st.rerun()

    # 结果下载
    if st.session_state.current_df is not None:
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        st.download_button("📥 下载当前结果", out.getvalue(), "Result.xlsx")

# ================= 5. 主界面 (数据展示与交互) =================
st.title("⚡ AI 能源数据分析台 (V28)")

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传包含数据的 Excel 文件")
    st.stop()

# 撤销与状态栏
c1, c2 = st.columns([1, 6])
with c1: 
    if st.button("↩️ 撤销"):
        if st.session_state.history:
            st.session_state.current_df = st.session_state.history.pop()
            st.rerun()
with c2: 
    st.success(f"当前数据形状: {st.session_state.current_df.shape} | 列: {list(st.session_state.current_df.columns)[:5]}...")

# 数据预览
with st.expander("📊 数据预览 (前 5 行)", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

# 聊天记录显示
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

if user_prompt := st.chat_input("请输入指令..."):
    # ... (前面的 history 记录代码不变) ...
    
    with st.chat_message("assistant"):
        status = st.status(f"✨ Gemini 1.5 Pro 正在思考...", expanded=True)
        
        # 准备上下文
        df_info = st.session_state.current_df.head(10).to_markdown() # Gemini 处理长文本能力强，可以直接给它看 Markdown
        col_info = str(st.session_state.current_df.dtypes)
        
        # 4. 构建 Gemini 的提示词 (Gemini 喜欢清晰的任务描述)
        full_prompt = f"""
        You are an expert Python Data Analyst.
        
        【Context】
        The user has a dataset (Pandas DataFrame).
        Here is the structure and the first 10 rows:
        {df_info}
        
        Columns and Types:
        {col_info}
        
        【User Request】
        {user_prompt}
        
        【Requirements】
        1. Write a Python function `def process_step(df):` to solve the request.
        2. Handle messy data:
           - If the input is in "Wide Format" (dates in headers), melt it first.
           - If the input is in "Long Format" but user wants a summary table, pivot it back at the end.
           - Handle "24:00" if present by converting it to the next day 00:00 for calculation.
        3. **CRITICAL**: The code must be complete and robust. Return ONLY the python code block.
        """
        
        try:
            # 5. 调用 Gemini (API 及其简单)
            response = model.generate_content(full_prompt)
            
            # 6. 提取代码 (Gemini 返回的是 response.text)
            raw_content = response.text
            # 清洗 markdown 标记
            code = raw_content.replace("```python", "").replace("```", "").strip()
            
            status.write("代码生成完毕，正在执行...")
            
            # 7. 执行代码 (逻辑同前)
            local_scope = {}
            execution_globals = {"pd": pd, "np": np, "re": re, "io": io} # 不需要注入太多自定义函数，看 Gemini 原生能力
            
            exec(code, execution_globals, local_scope)
            
            if 'process_step' in local_scope:
                new_df = local_scope['process_step'](st.session_state.current_df.copy())
                
                st.session_state.current_df = new_df
                st.session_state.last_successful_code = code
                
                status.update(label="✅ Gemini 执行成功", state="complete", expanded=False)
                st.markdown(f"**✅ 处理完成** | 结果形状: {new_df.shape}")
                st.session_state.chat_history.append({"role": "assistant", "content": "✅ 处理完成。"})
                st.rerun()
            else:
                st.error("Gemini 未生成 process_step 函数")
                
        except Exception as e:
            st.error(f"Gemini 调用或执行失败: {e}")
            st.code(code if 'code' in locals() else "No code generated")