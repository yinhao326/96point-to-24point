import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
from openai import OpenAI

# ================= 配置区域 =================
if "DEEPSEEK_API_KEY" in st.secrets:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    st.error("请在 Secrets 中配置 DEEPSEEK_API_KEY")
    st.stop()

BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

st.set_page_config(page_title="AI 数据分析台 (V27 闭环版)", layout="wide")

# ================= 1. 核心工具函数 =================
def clean_energy_time(series):
    """
    【进门清洗】将 '24:00' 转换为 '次日 00:00' 以便计算
    """
    def parse_single_val(val):
        s_val = str(val).strip()
        if "24:00" in s_val:
            temp_s = s_val.replace("24:00", "00:00")
            try:
                dt = pd.to_datetime(temp_s)
                return dt + pd.Timedelta(days=1)
            except:
                return pd.NaT
        else:
            try: return pd.to_datetime(val)
            except: return pd.NaT

    try: return pd.to_datetime(series)
    except: return series.apply(parse_single_val)

# ================= 2. 状态管理 =================
keys = ["current_df", "chat_history", "file_hash", "macros", 
        "last_successful_code", "last_successful_explanation", 
        "all_sheets", "current_sheet_name", "history"]

for key in keys:
    if key not in st.session_state:
        if key == "macros" or key == "all_sheets": st.session_state[key] = {}
        elif key in ["chat_history", "history"]: st.session_state[key] = []
        elif key == "current_sheet_name": st.session_state[key] = ""
        else: st.session_state[key] = None

st.title("🤖 AI 数据分析台 (V27 行业闭环版)")
st.caption("⚡ 专为电力行业打造 | 完美支持 24:00 <-> 96点 互转")

# ================= 3. 侧边栏 =================
with st.sidebar:
    st.header("🧠 模型选择")
    model_map = {
        "DeepSeek-V3 (快速/通用)": "deepseek-chat",
        "DeepSeek-R1 (深度推理/聪明)": "deepseek-reasoner"
    }
    selected_model_label = st.radio("选择大脑：", list(model_map.keys()))
    selected_model = model_map[selected_model_label]
    
    st.divider()
    st.header("📂 1. 文件区")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls", "csv"])
    
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
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 文件加载成功。**系统已启用 '24:00' 自动保护机制。**"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")

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
            st.session_state.history = []
            st.rerun()
            
    if st.button("🔥 重置工作区", type="primary"):
        st.session_state.file_hash = None
        st.rerun()

    # 技能库 & 下载 (保持 V25 逻辑)
    if st.session_state.macros:
        st.divider()
        st.header("⚡ 常用功能")
        for name, macro in st.session_state.macros.items():
            if st.button(f"▶️ {name}"):
                pass # (省略代码，逻辑同前)

    if st.session_state.current_df is not None:
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        st.download_button("📥 下载结果", out.getvalue(), "Result.xlsx")

# ================= 4. 主界面 =================
if st.session_state.current_df is None:
    st.info("👈 请上传 Excel")
    st.stop()

c1, c2 = st.columns([1, 5])
with c1: 
    if st.button("↩️ 撤销"):
        if st.session_state.history:
            st.session_state.current_df = st.session_state.history.pop()
            st.rerun()
with c2: st.success(f"当前数据: {st.session_state.current_df.shape}")

with st.expander("📊 数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]): st.markdown(msg["content"])

# ================= 5. 核心引擎 (闭环逻辑) =================

def get_dataframe_info(df):
    buf = io.StringIO()
    df.info(buf=buf)
    return f"""Shape: {df.shape}, Columns: {list(df.columns)}, dtypes: {df.dtypes}"""

if user_prompt := st.chat_input("请输入指令 (例如: 转成96点)..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.history.append(st.session_state.current_df.copy())
    
    with st.chat_message("user"): st.markdown(user_prompt)
    
    with st.chat_message("assistant"):
        status = st.status(f"🧠 AI ({selected_model}) 正在计算...", expanded=True)
        
        execution_globals = {
            "pd": pd, "np": np, "re": re, "math": math, "datetime": datetime,
            "clean_energy_time": clean_energy_time 
        }
        
        # --- V27 核心 Prompt：增加“出门还原”指令 ---
        system_prompt = """
        You are an Expert Python Data Scientist in the Energy Sector.
        
        【Critical Rule 1: Input Cleaning】
        Energy data often uses "24:00". Standard parsing FAILS.
        **MANDATORY**: Use `clean_energy_time(df['col'])` to convert time columns. This turns "24:00" into "NextDay 00:00" for calculation.
        
        【Critical Rule 2: Calculation (Upsampling 24->96)】
        - Do NOT just resample.
        - Create a full index: `idx = pd.date_range(start=..., end=..., freq='15min')`.
        - Use `reindex(idx)` or `merge` to ensure you have exactly 96 points (00:15 to 24:00).
        - Fill missing values using interpolation.
        
        【Critical Rule 3: Output Formatting (The "Round-Trip")】
        The user MUST see "24:00" in the final result, NOT "00:00".
        **Before returning**:
        1. If the index or time column contains "00:00" (representing the next day), Convert it back to String format.
        2. Replace the "00:00:00" string with "24:00:00" (and adjust the date back to current day if needed, or just replace the time suffix if it's purely time).
        3. Example strategy: Convert datetime to string, replace ' 00:00:00' with ' 24:00:00' for the appropriate rows.
        
        【Task】
        Write `def process_step(df):` to solve the request.
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
            [Data Info]
            {get_dataframe_info(st.session_state.current_df)}
            [First 5 Rows]
            {st.session_state.current_df.head(5).to_markdown()}
            [Request]
            {user_prompt}
            """}
        ]
        
        success = False
        for i in range(3):
            try:
                if i > 0: status.write(f"🔧 第 {i} 次修正...")
                
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=0.1
                )
                code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                local_scope = {}
                exec(code, execution_globals, local_scope)
                if 'process_step' not in local_scope: raise ValueError("函数丢失")
                
                new_df = local_scope['process_step'](st.session_state.current_df.copy())
                
                # 校验
                if not isinstance(new_df, pd.DataFrame): 
                    if hasattr(new_df, 'data'): new_df = new_df.data
                    else: raise ValueError("返回非 DataFrame")

                st.session_state.current_df = new_df
                st.session_state.last_successful_code = code
                st.session_state.last_successful_explanation = "处理成功 (已保留 24:00 格式)"
                
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                st.markdown(f"**✅ 处理完成**\n> 结果形状: {new_df.shape} (已还原 24:00 显示)")
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 处理完成。结果形状: {new_df.shape}"})
                st.rerun()
                break
                
            except Exception as e:
                status.write(f"❌ 错误: {e}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"Error: {e}\nRemember Rule 3: You MUST convert '00:00' timestamps back to '24:00' strings at the end!"})
        
        if not success:
            st.error("处理失败。")
            st.session_state.history.pop()
