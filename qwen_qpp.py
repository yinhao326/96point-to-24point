import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
# 替换为通义千问兼容的 OpenAI 库
from openai import OpenAI

# ================= 0. 配置与初始化 =================

st.set_page_config(page_title="AI 能源分析台 (千问套餐版)", layout="wide")

if "DASHSCOPE_API_KEY" in st.secrets:
    api_key = st.secrets["DASHSCOPE_API_KEY"]
else:
    st.error("❌ 未检测到 API Key。请在 Streamlit Cloud 控制台的 Secrets 中配置 DASHSCOPE_API_KEY")
    st.stop()

try:
    # 【核心修改 1】：必须使用截图中的“套餐专属 Base URL”
    client = OpenAI(
        api_key=api_key,
        base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
except Exception as e:
    st.error(f"无法初始化千问客户端: {e}")
    st.stop()

# ================= 1. 核心工具函数 =================

def clean_energy_time(series):
    """解决 '24:00' 问题的能源行业时间清洗器"""
    def parse_single_val(val):
        s_val = str(val).strip()
        if "24:00" in s_val:
            temp_s = s_val.replace("24:00", "00:00")
            try:
                dt = pd.to_datetime(temp_s)
                if len(s_val) > 8: return dt + pd.Timedelta(days=1)
                return dt
            except: return pd.NaT
        else:
            try: return pd.to_datetime(val)
            except: return pd.NaT
    try: return pd.to_datetime(series)
    except: return series.apply(parse_single_val)

# ================= 2. 全局状态管理 =================
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "current_df" not in st.session_state: st.session_state.current_df = None
if "dfs_dict" not in st.session_state: st.session_state.dfs_dict = {} 
if "file_hash" not in st.session_state: st.session_state.file_hash = None

# ================= 3. 侧边栏 =================
with st.sidebar:
    st.title("🧠 设置")
    
    # 【核心修改 2】：必须使用套餐支持的精确模型名称
    model_options = [
        "qwen3.6-plus",
        "deepseek-v3.2", 
        "glm-5", 
        "MiniMax-M2.5"# 根据你的截图，套餐可用模型为 qwen3.6-plus
    ]
    selected_model = st.selectbox("选择千问引擎：", model_options, index=0)
    st.success("☁️ 云端环境：千问订阅套餐专属通道")
    st.divider()
    
    st.header("📂 文件上传")
    uploaded_files = st.file_uploader("上传 Excel/CSV (支持多选)", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
    
    if uploaded_files:
        current_hash = hash(tuple(f.getvalue() for f in uploaded_files))
        if st.session_state.file_hash != current_hash:
            try:
                st.session_state.dfs_dict = {}
                for f in uploaded_files:
                    if f.name.endswith('.csv'):
                        df_temp = pd.read_csv(f)
                    else:
                        df_temp = pd.read_excel(f)
                    
                    # 强制将所有列名转为字符串，防止数字列名报错
                    df_temp.columns = df_temp.columns.astype(str)
                    st.session_state.dfs_dict[f.name] = df_temp
                
                st.session_state.file_hash = current_hash
                st.session_state.current_df = None 
                
                file_names_str = "\n".join([f"- `{name}`" for name in st.session_state.dfs_dict.keys()])
                st.session_state.chat_history = [{
                    "role": "assistant", 
                    "content": f"✅ **成功加载 {len(uploaded_files)} 个文件！**\n{file_names_str}\n\n请下达指令。"
                }]
                st.rerun()
            except Exception as e:
                st.error(f"❌ 读取失败: {e}")

    if st.button("🔥 重置工作区", type="primary", use_container_width=True):
        st.session_state.file_hash = None
        st.session_state.current_df = None
        st.session_state.dfs_dict = {}
        st.session_state.chat_history = []
        st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=False)
        st.download_button("📥 下载汇总结果", out.getvalue(), "Merged_Result.xlsx", use_container_width=True)

# ================= 4. 主界面 =================
st.title("⚡ AI 能源数据分析台 (千问 V39)")

if not st.session_state.dfs_dict and st.session_state.current_df is None:
    st.info("👈 请先在左侧上传一个或多个数据文件")
    st.stop()

# 数据预览逻辑
if st.session_state.current_df is not None:
    with st.expander("📊 当前工作区数据预览 (Top 5)", expanded=True):
        st.dataframe(st.session_state.current_df.head(5), use_container_width=True)
        st.caption(f"当前形状: {st.session_state.current_df.shape}")
else:
    with st.expander(f"📊 源文件预览 (共 {len(st.session_state.dfs_dict)} 个)", expanded=True):
        file_names = list(st.session_state.dfs_dict.keys())
        tabs = st.tabs(file_names[:10]) 
        for i, fname in enumerate(file_names[:10]):
            with tabs[i]:
                st.dataframe(st.session_state.dfs_dict[fname].head(5), use_container_width=True)
                st.caption(f"原始形状: {st.session_state.dfs_dict[fname].shape}")

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 5. 千问代码生成引擎 =================

if user_prompt := st.chat_input("请输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"): st.markdown(user_prompt)
    
    with st.chat_message("assistant"):
        status = st.status("✨ 千问正在思考 (代码生成模式)...", expanded=True)
        
        try:
            if st.session_state.current_df is not None:
                df_sample = st.session_state.current_df.head(3).to_markdown()
                df_dtypes = str(st.session_state.current_df.dtypes)
                data_context = f"【Data Context】\nYou have a single working DataFrame `df`.\nSample:\n{df_sample}\nTypes:\n{df_dtypes}"
                func_req = "2. Define a function `def process_step(df):` that returns the modified single dataframe."
                exec_args = st.session_state.current_df.copy()
            else:
                data_context = "【Data Context】\nYou are given a dictionary `dfs_dict` where KEYS are string filenames and VALUES are pandas DataFrames.\n"
                for fname, df in list(st.session_state.dfs_dict.items())[:5]: 
                    data_context += f"- Filename: '{fname}'\n  Columns: {list(df.columns)}\n"
                if len(st.session_state.dfs_dict) > 5:
                    data_context += f"... and {len(st.session_state.dfs_dict)-5} more files.\n"
                
                func_req = "2. Define a function `def process_step(dfs_dict):` that processes this dictionary. Extract info from filenames if needed, combine all dataframes, and return ONE single resulting DataFrame."
                exec_args = {k: v.copy() for k, v in st.session_state.dfs_dict.items()}

            # 构建符合 OpenAI/千问 规范的系统提示词
            system_prompt = f"""
            You are an expert Python Data Analyst.
            
            {data_context}
            
            【Requirements】
            1. Return ONLY valid Python code inside ```python blocks. No explanations outside the code block.
            {func_req}
            3. Use `clean_energy_time(series)` for date parsing if needed.
            4. Assume necessary libraries (pd, np, re, math, datetime) are imported.
            5. Use regex `re.findall` or `re.search` to extract dates from keys (filenames) if necessary.
            """
            
            status.write(f"正在请求千问 API ({selected_model})...")
            
            # 使用 openai 库调用千问
            response = client.chat.completions.create(
                model=selected_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"User Request: {user_prompt}"}
                ]
            )
            raw_code = response.choices[0].message.content
            
            # 提取代码块
            if "```python" in raw_code:
                cleaned_code = raw_code.split("```python")[1].split("```")[0].strip()
            elif "```" in raw_code:
                cleaned_code = raw_code.split("```")[1].split("```")[0].strip()
            else:
                cleaned_code = raw_code.strip()
            
            status.write("代码生成完毕，正在执行...")
            
            # 执行环境
            execution_globals = {
                "pd": pd, "np": np, "re": re, "math": math, 
                "datetime": datetime, "clean_energy_time": clean_energy_time 
            }
            local_scope = {}
            exec(cleaned_code, execution_globals, local_scope)
            
            if 'process_step' in local_scope:
                new_df = local_scope['process_step'](exec_args)
                
                st.session_state.current_df = new_df
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                result_msg = f"✅ 处理完成。当前表格形状: {new_df.shape}"
                st.session_state.chat_history.append({"role": "assistant", "content": result_msg})
                st.rerun()
            else:
                status.update(label="❌ 函数丢失", state="error")
                st.error("AI 未生成 process_step 函数")
                st.code(cleaned_code)

        except Exception as e:
            status.update(label="❌ 发生错误", state="error")
            st.error(f"错误详情: {str(e)}")
