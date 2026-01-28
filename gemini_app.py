import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
import os
# 1. 引入新版 SDK
from google import genai

# ================= 0. 核心网络配置 (最关键一步) =================
# 根据你的截图，你的代理端口是 7897
# 这两行代码必须放在所有网络请求之前
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"

# ================= 1. 配置与初始化 =================

st.set_page_config(page_title="AI 能源分析台 (Gemini V30)", layout="wide")

# 检查 API Key
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("❌ 未检测到 API Key。请在 .streamlit/secrets.toml 中配置 GEMINI_API_KEY")
    st.stop()

# 初始化新版客户端
try:
    # 【强制指定代理】直接告诉 SDK 走这个通道，不再依赖环境变量
    client = genai.Client(
        api_key=api_key,
        http_options={
            "proxy": "http://127.0.0.1:7897",  # <--- 显式指定，解决 Connection Refused
            "timeout": 60000, # 顺便设置个长一点的超时(毫秒)
        }
    )
except Exception as e:
    st.error(f"无法初始化客户端，请检查代理设置: {e}")
    st.stop()

# ================= 2. 核心工具函数 =================

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

# ================= 3. 全局状态管理 =================
keys = ["current_df", "chat_history", "file_hash", 
        "last_successful_code", "all_sheets", "current_sheet_name", "history"]

for key in keys:
    if key not in st.session_state:
        if key == "all_sheets": st.session_state[key] = {}
        elif key in ["chat_history", "history"]: st.session_state[key] = []
        elif key == "current_sheet_name": st.session_state[key] = ""
        else: st.session_state[key] = None

# ================= 4. 侧边栏 =================
with st.sidebar:
    st.title("🧠 设置")
    
    # 新版 SDK 的模型名称通常不需要 'models/' 前缀，但为了保险我们使用完整名称
    model_options = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
    selected_model = st.selectbox("选择模型引擎：", model_options, index=0)
    
    st.info(f"🌐 代理状态: 已强制指向 127.0.0.1:7897")

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
                first_sheet = list(all_sheets.keys())[0]
                st.session_state.current_sheet_name = first_sheet
                st.session_state.current_df = all_sheets[first_sheet].copy()
                st.session_state.chat_history = [] 
                st.session_state.history = [] 
                
                st.session_state.chat_history.append({
                    "role": "assistant", 
                    "content": f"✅ **{uploaded_file.name}** 加载成功！(引擎: {selected_model})\n代理已连接，请告诉我怎么处理数据。"
                })
                st.rerun()
            except Exception as e:
                st.error(f"❌ 读取失败: {e}")

    # Sheet 切换
    if st.session_state.all_sheets:
        st.divider()
        sheet_names = list(st.session_state.all_sheets.keys())
        try: curr_idx = sheet_names.index(st.session_state.current_sheet_name)
        except: curr_idx = 0
        sel_sheet = st.selectbox("当前工作表", sheet_names, index=curr_idx)
        if sel_sheet != st.session_state.current_sheet_name:
            st.session_state.current_sheet_name = sel_sheet
            st.session_state.current_df = st.session_state.all_sheets[sel_sheet].copy()
            st.rerun()
            
    if st.button("🔥 重置工作区", type="primary", use_container_width=True):
        st.session_state.file_hash = None
        st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        st.download_button("📥 下载结果", out.getvalue(), "Result.xlsx", use_container_width=True)

# ================= 5. 主界面 =================
st.title("⚡ AI 能源数据分析台 (V30)")

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传文件")
    st.stop()

c1, c2 = st.columns([1, 6])
with c1: 
    if st.button("↩️ 撤销"):
        if st.session_state.history:
            st.session_state.current_df = st.session_state.history.pop()
            st.rerun()
with c2: 
    row_count, col_count = st.session_state.current_df.shape
    st.success(f"数据维度: {row_count} 行 × {col_count} 列")

with st.expander("📊 数据预览 (Top 5)", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 6. Gemini 新版核心引擎 =================

if user_prompt := st.chat_input("请输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.history.append(st.session_state.current_df.copy())
    with st.chat_message("user"): st.markdown(user_prompt)
    
    with st.chat_message("assistant"):
        status = st.status("✨ Gemini 正在连接...", expanded=True)
        
        try:
            # 准备 Prompt
            df_sample = st.session_state.current_df.head(10).to_markdown()
            df_dtypes = str(st.session_state.current_df.dtypes)
            
            prompt = f"""
            You are an expert Python Data Analyst in the Energy sector.
            
            【Data Context】
            {df_sample}
            Types: {df_dtypes}
            
            【User Request】
            {user_prompt}
            
            【Requirements】
            1. Return ONLY a valid Python code block.
            2. The code must define a function `def process_step(df):`.
            3. Use `clean_energy_time(series)` if you need to parse times like "24:00".
            4. Handle wide format (dates in columns) if detected.
            """
            
            # 【核心修改】新版 SDK 调用方式
            status.write("正在发送请求到 Google (via Proxy 7897)...")
            
            response = client.models.generate_content(
                model=selected_model,
                contents=prompt
            )
            
            # 提取代码
            raw_code = response.text
            cleaned_code = raw_code.replace("```python", "").replace("```", "").strip()
            
            status.write("代码生成完毕，正在执行...")
            
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
                st.markdown(result_msg)
                st.session_state.chat_history.append({"role": "assistant", "content": result_msg})
                st.rerun()
            else:
                status.update(label="❌ 函数丢失", state="error")
                st.error("AI 未生成 process_step 函数")
                st.code(cleaned_code)

        except Exception as e:
            status.update(label="❌ 发生错误", state="error")
            st.error(f"错误详情: {str(e)}")
            st.info("提示：如果提示连接超时，请检查你的 VPN 是否开启，且端口是否确实为 7897")

