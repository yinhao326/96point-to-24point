import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
import google.generativeai as genai

# ================= 1. 配置与初始化 =================

st.set_page_config(page_title="AI 能源分析台 (Gemini Pro)", layout="wide")

# 检查 API Key
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("❌ 未检测到 API Key。请在 .streamlit/secrets.toml 中配置 GEMINI_API_KEY")
    st.stop()

# ================= 2. 核心工具函数 (行业专用) =================

def clean_energy_time(series):
    """
    【能源行业时间清洗器】
    用于解决 Python 无法识别 '24:00' 的问题。
    将 '24:00' 转换为 '次日 00:00' 以便进行数学计算。
    """
    def parse_single_val(val):
        s_val = str(val).strip()
        # 针对电力行业特殊的 24:00 处理
        if "24:00" in s_val:
            # 将 24:00 替换为 00:00
            temp_s = s_val.replace("24:00", "00:00")
            try:
                dt = pd.to_datetime(temp_s)
                # 如果是包含日期的完整时间 (如 2026-01-01 24:00)，则加一天
                # 如果只是纯时间 (如 24:00)，也先按当天 00:00 处理，计算逻辑交给 AI 修正
                if len(s_val) > 8: 
                    return dt + pd.Timedelta(days=1)
                return dt
            except:
                return pd.NaT
        else:
            # 正常时间
            try:
                return pd.to_datetime(val)
            except:
                return pd.NaT

    # 优先尝试高速批量转换
    try:
        return pd.to_datetime(series)
    except:
        # 失败则进入逐行清洗模式
        return series.apply(parse_single_val)

# ================= 3. 全局状态管理 =================
# 初始化所有 Session State，确保页面刷新数据不丢失
keys = ["current_df", "chat_history", "file_hash", 
        "last_successful_code", "all_sheets", "current_sheet_name", "history"]

for key in keys:
    if key not in st.session_state:
        if key == "all_sheets": st.session_state[key] = {}
        elif key in ["chat_history", "history"]: st.session_state[key] = []
        elif key == "current_sheet_name": st.session_state[key] = ""
        else: st.session_state[key] = None

# ================= 4. 侧边栏 (设置与文件) =================
with st.sidebar:
    st.title("🧠 设置")
    
    # 模型选择 (Gemini 1.5 Pro 是目前逻辑最强的版本)
    model_name = st.radio(
        "选择模型引擎：",
        ["gemini-1.5-pro (推荐)", "gemini-2.0-flash-exp (极速)"],
        index=0
    )
    # 提取实际模型名
    selected_model = "gemini-1.5-pro" if "pro" in model_name else "gemini-2.0-flash-exp"

    st.divider()
    st.header("📂 文件上传")
    uploaded_file = st.file_uploader("上传 Excel/CSV", type=["xlsx", "xls", "csv"])
    
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
                
                # 默认选中第一个 Sheet
                first_sheet = list(all_sheets.keys())[0]
                st.session_state.current_sheet_name = first_sheet
                st.session_state.current_df = all_sheets[first_sheet].copy()
                
                # 重置历史
                st.session_state.chat_history = [] 
                st.session_state.history = [] 
                
                st.session_state.chat_history.append({
                    "role": "assistant", 
                    "content": f"✅ **{uploaded_file.name}** 加载成功！\n\nGemini 1.5 Pro 已就绪。您可以直接用自然语言描述需求，例如：\n*“将数据转为96点”*\n*“如果是宽表，请帮我转成24点并保留原来的格式”*"
                })
                st.rerun()
            except Exception as e:
                st.error(f"❌ 读取失败: {e}")

    # Sheet 切换逻辑
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
            
    if st.button("🔥 重置工作区", type="primary", use_container_width=True):
        st.session_state.file_hash = None
        st.rerun()

    # 下载功能
    if st.session_state.current_df is not None:
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True) # 默认保留索引，避免丢失时间轴
        st.download_button("📥 下载结果 Excel", out.getvalue(), "Result.xlsx", use_container_width=True)

# ================= 5. 主界面 =================
st.title("⚡ AI 能源数据分析台 (V29)")

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传文件")
    st.stop()

# 顶部工具栏 (撤销 + 状态)
c1, c2 = st.columns([1, 6])
with c1: 
    if st.button("↩️ 撤销"):
        if st.session_state.history:
            st.session_state.current_df = st.session_state.history.pop()
            st.rerun()
with c2: 
    row_count, col_count = st.session_state.current_df.shape
    st.success(f"当前数据: {row_count} 行 × {col_count} 列")

# 数据预览
with st.expander("📊 数据预览 (Top 5)", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

# 聊天记录渲染
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 6. Gemini 核心引擎 (无硬编码规则版) =================

if user_prompt := st.chat_input("请输入指令..."):
    # 1. 记录用户输入
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.history.append(st.session_state.current_df.copy()) # 存入历史栈用于撤销
    with st.chat_message("user"): st.markdown(user_prompt)
    
    with st.chat_message("assistant"):
        status = st.status("✨ Gemini 正在阅读数据...", expanded=True)
        
        try:
            # 2. 准备上下文 (Gemini 擅长长文本，直接给它看前10行和Markdown格式)
            df_sample = st.session_state.current_df.head(10).to_markdown()
            df_dtypes = str(st.session_state.current_df.dtypes)
            
            # 3. 构建 Prompt
            # 注意：这里不再写死 "Must Melt" 等规则，而是描述业务场景，让 AI 自己决定
            prompt = f"""
            You are an expert Senior Python Data Analyst in the Energy/Power sector.
            
            【Current Dataset Context】
            The user has uploaded a dataframe. Here are the first 10 rows and columns:
            {df_sample}
            
            Column Data Types:
            {df_dtypes}
            
            【User Request】
            {user_prompt}
            
            【Your Task】
            1. Analyze the structure of the data. 
               - If it's a "Wide Format" (Dates in headers, Time in rows), handle it appropriately (likely need to melt -> process -> pivot back).
               - If it's "Long Format", process directly.
            2. **Handle "24:00" ambiguity**:
               - Energy data often uses "24:00" to mean the end of the day. 
               - A helper function `clean_energy_time(series)` is available in the environment. USE IT if you need to parse time columns.
               - If the user requests a final output format that requires "24:00" (instead of "00:00" next day), please convert the index/column back to string and fix the display at the very end.
            3. Write a Python function `def process_step(df):` that takes the current dataframe and returns the processed dataframe.
            4. **CRITICAL**: Return ONLY the valid Python code block. No explanation text outside the code block.
            """
            
            # 4. 调用 Gemini API
            model = genai.GenerativeModel(selected_model)
            response = model.generate_content(prompt)
            
            # 5. 代码清洗 (Gemini 有时会带 ```python 标记)
            raw_code = response.text
            cleaned_code = raw_code.replace("```python", "").replace("```", "").strip()
            
            status.write("代码生成完毕，正在执行...")
            
            # 6. 执行环境准备
            # 将 clean_energy_time 注入给 AI 使用
            execution_globals = {
                "pd": pd, 
                "np": np, 
                "re": re, 
                "math": math, 
                "datetime": datetime,
                "clean_energy_time": clean_energy_time 
            }
            local_scope = {}
            
            # 7. 动态执行
            exec(cleaned_code, execution_globals, local_scope)
            
            if 'process_step' in local_scope:
                # 运行 AI 写的函数
                new_df = local_scope['process_step'](st.session_state.current_df.copy())
                
                # 校验结果
                if not isinstance(new_df, pd.DataFrame):
                    raise ValueError("函数未返回 DataFrame，请检查逻辑。")
                
                # 更新状态
                st.session_state.current_df = new_df
                st.session_state.last_successful_code = cleaned_code
                
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                # 结果反馈
                result_msg = f"✅ 处理完成。结果形状: {new_df.shape}"
                st.markdown(result_msg)
                st.session_state.chat_history.append({"role": "assistant", "content": result_msg})
                
                # 强制刷新页面以显示新数据
                st.rerun()
            else:
                status.update(label="❌ 函数丢失", state="error")
                st.error("Gemini 未生成名为 `process_step` 的函数。")
                with st.expander("查看生成代码"):
                    st.code(cleaned_code, language='python')

        except Exception as e:
            status.update(label="❌ 发生错误", state="error")
            st.error(f"执行失败: {str(e)}")
            st.session_state.chat_history.append({"role": "assistant", "content": f"❌ 错误: {str(e)}"})
            # 如果出错，弹出代码供调试
            if 'cleaned_code' in locals():
                with st.expander("查看 AI 生成的错误代码"):
                    st.code(cleaned_code, language='python')
