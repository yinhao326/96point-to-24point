import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
# 引入新版 SDK
from google import genai

# ================= 0. 配置与初始化 =================

st.set_page_config(page_title="AI 能源分析台 (Cloud版)", layout="wide")

# ❌ 删除所有 os.environ 设置代理的代码
# Streamlit Cloud 在海外，直连 Google，不需要代理！

# 检查 API Key
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("❌ 未检测到 API Key。请在 Streamlit Cloud 控制台的 Secrets 中配置 GEMINI_API_KEY")
    st.stop()

# 初始化客户端
try:
    # 纯净初始化，不带任何 proxy 参数
    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": 60000} # 只保留超时设置
    )
except Exception as e:
    st.error(f"无法初始化客户端: {e}")
    st.stop()

# ================= 1. 核心工具函数 =================

def clean_energy_time(series):
    """
    【能源行业时间清洗器】解决 '24:00' 问题
    """
    def parse_single_val(val):
        s_val = str(val).strip()
        if "24:00" in s_val:
            temp_s = s_val.replace("24:00", "00:00")
            try:
                dt = pd.to_datetime(temp_s)
                if len(s_val) > 8: 
                    return dt + pd.Timedelta(days=1)
                return dt
            except:
                return pd.NaT
        else:
            try:
                return pd.to_datetime(val)
            except:
                return pd.NaT

    try:
        return pd.to_datetime(series)
    except:
        return series.apply(parse_single_val)

# ================= 2. 全局状态管理 =================
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "file_hash" not in st.session_state:
    st.session_state.file_hash = None

# ================= 3. 侧边栏 =================
with st.sidebar:
    st.title("🧠 设置")
    
    # 硬编码模型列表
    model_options = [
        "gemini-2.5-flash",       # 截图中的新模型（推荐首选，速度快）
        "gemini-2.5-pro",         # 截图中的强力模型
        "gemini-1.5-flash",   # 1.5 的稳定版（如果 2.5 报错，就切回这个）
        "gemini-1.5-pro",     # 1.5 的强力稳定版
    ]
    selected_model = st.selectbox("选择模型引擎：", model_options, index=0)
    
    st.success("☁️ 云端环境：已自动直连 Google")

    st.divider()
    st.header("📂 文件上传")
    uploaded_file = st.file_uploader("上传 Excel/CSV", type=["xlsx", "xls", "csv"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                if uploaded_file.name.endswith('.csv'):
                    st.session_state.current_df = pd.read_csv(uploaded_file)
                else:
                    st.session_state.current_df = pd.read_excel(uploaded_file)
                
                st.session_state.file_hash = current_hash
                st.session_state.chat_history = [{
                    "role": "assistant", 
                    "content": f"✅ **{uploaded_file.name}** 加载成功！(引擎: {selected_model})\n请告诉我怎么处理数据。"
                }]
                st.rerun()
            except Exception as e:
                st.error(f"❌ 读取失败: {e}")

    if st.button("🔥 重置工作区", type="primary", use_container_width=True):
        st.session_state.file_hash = None
        st.session_state.current_df = None
        st.session_state.chat_history = []
        st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=False) # 这里的 index=False 视情况而定
        st.download_button("📥 下载结果", out.getvalue(), "Result.xlsx", use_container_width=True)

# ================= 4. 主界面 =================
st.title("⚡ AI 能源数据分析台 (Cloud V34)")

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传文件")
    st.stop()

# 数据预览
with st.expander("📊 数据预览 (Top 5)", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

# 聊天记录
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 5. Gemini 核心引擎 =================

if user_prompt := st.chat_input("请输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"): st.markdown(user_prompt)
    
    with st.chat_message("assistant"):
        status = st.status("✨ AI 正在思考...", expanded=True)
        
        try:
            # 准备 Prompt
            df_sample = st.session_state.current_df.head(5).to_markdown()
            df_dtypes = str(st.session_state.current_df.dtypes)
            
            prompt = f"""
            You are an expert Python Data Analyst.
            
            【Data Context】
            {df_sample}
            Types: {df_dtypes}
            
            【User Request】
            {user_prompt}
            
            【Requirements】
            1. Return ONLY valid Python code inside ```python blocks.
            2. Define a function `def process_step(df):` that returns the modified dataframe.
            3. Use `clean_energy_time(series)` for date parsing if needed.
            4. Assume necessary libraries (pd, np, re) are imported.
            """
            
            status.write("正在请求 Google API (Cloud Direct)...")
            
            # 调用生成 API
            response = client.models.generate_content(
                model=selected_model,
                contents=prompt
            )
            
            # 提取代码
            raw_code = response.text
            # 简单的代码提取逻辑
            if "```python" in raw_code:
                cleaned_code = raw_code.split("```python")[1].split("```")[0].strip()
            elif "```" in raw_code:
                cleaned_code = raw_code.split("```")[1].split("```")[0].strip()
            else:
                cleaned_code = raw_code.strip()
            
            status.write("正在执行生成的代码...")
            
            # 执行环境
            execution_globals = {
                "pd": pd, "np": np, "re": re, "math": math, 
                "datetime": datetime, "clean_energy_time": clean_energy_time 
            }
            local_scope = {}
            
            exec(cleaned_code, execution_globals, local_scope)
            
            if 'process_step' in local_scope:
                new_df = local_scope['process_step'](st.session_state.current_df.copy())
                
                st.session_state.current_df = new_df
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                result_msg = f"✅ 处理完成。结果形状: {new_df.shape}"
                st.session_state.chat_history.append({"role": "assistant", "content": result_msg})
                st.rerun()
            else:
                status.update(label="❌ 函数丢失", state="error")
                st.error("AI 未生成 process_step 函数")
                st.code(cleaned_code)

        except Exception as e:
            status.update(label="❌ 发生错误", state="error")
            st.error(f"错误详情: {str(e)}")



