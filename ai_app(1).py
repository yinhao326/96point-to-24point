import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
from openai import OpenAI

# ================= 1. 配置区域 =================
# 务必确保 .streamlit/secrets.toml 中配置了 DEEPSEEK_API_KEY
if "DEEPSEEK_API_KEY" in st.secrets:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    st.error("❌ 未检测到 API Key。请在 Secrets 中配置 DEEPSEEK_API_KEY")
    st.stop()

BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

st.set_page_config(page_title="AI 能源数据分析台 (V28 全能版)", layout="wide")

# ================= 2. 核心清洗引擎 (不依赖 AI 的硬逻辑) =================

def clean_energy_time(series):
    """
    【万能时间清洗器】
    1. 能识别 '2026-01-01 24:00:00' -> 转为次日 00:00
    2. 能识别纯时间 '24:00' -> 暂时保留或标记
    3. 极其强健，不会因为一个错导致全盘崩溃
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
                if len(s_val) > 8: 
                    return dt + pd.Timedelta(days=1)
                # 如果只是纯时间 (如 24:00)，先返回 00:00 (后续逻辑需配合日期处理)
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

# ================= 6. 核心处理引擎 (V28 增强版) =================

def get_dataframe_info(df):
    buf = io.StringIO()
    df.info(buf=buf)
    return f"""Shape: {df.shape}\nColumns: {list(df.columns)}\nTypes:\n{df.dtypes}"""

if user_prompt := st.chat_input("请输入指令 (例如: 转成96点，注意表头是日期)..."):
    # 记录用户输入
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.history.append(st.session_state.current_df.copy())
    with st.chat_message("user"): st.markdown(user_prompt)
    
    with st.chat_message("assistant"):
        status = st.status(f"🧠 AI ({selected_model}) 正在思考...", expanded=True)
        
        # 注入全局变量，让 AI 可以直接调用 pandas 和我们的清洗函数
        execution_globals = {
            "pd": pd, "np": np, "re": re, "math": math, "datetime": datetime,
            "clean_energy_time": clean_energy_time 
        }
        
        # --- V28 System Prompt: 针对宽表和 24:00 的专项训练 ---
        system_prompt = """
        You are an Expert Python Data Scientist in the Energy Sector.
        
        【Critical: Handling Input Structure (Wide vs Long)】
        The user often uploads "Wide Format" energy data:
        - Dates are in the HEADERS (Columns like '2026-01-01', '2026-01-02').
        - Time is in the first column (Rows like '01:00', ... '24:00').
        
        **IF you detect this structure, you MUST:**
        1. `melt` the DataFrame first to turn it into Long Format (Date, Time, Value).
        2. Combine 'Date' and 'Time' columns into a string: `str_time = df['Date_col'] + ' ' + df['Time_col']`.
        3. THEN apply the helper function: `clean_energy_time(str_time)`.
        
        【Critical: Handling "24:00"】
        - NEVER use `pd.to_datetime()` directly on energy data.
        - ALWAYS use `clean_energy_time(series)` provided in the environment.
        - This function automatically handles "24:00" -> "Next Day 00:00".
        
        【Critical: Output Formatting】
        - If the user asks for "96 points" or "resampling", perform the calculation using the cleaned datetime index.
        - **MANDATORY FINAL STEP**: If the user wants to see "24:00", you must convert the final DatetimeIndex back to String.
        - Logic: Convert to string, identify rows where time is "00:00:00" (which implies next day in energy terms), change string to "24:00:00", and shift date string back one day if needed (or just ensure the display looks like the original date + 24:00).
        
        【Output】
        Write a function `def process_step(df):` that returns the processed DataFrame.
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
            [Data Info]
            {get_dataframe_info(st.session_state.current_df)}
            
            [First 5 Rows - Inspect structure carefully]
            {st.session_state.current_df.head(5).to_markdown()}
            
            [User Request]
            {user_prompt}
            
            [Goal]
            1. Detect if it's Wide Format (Dates in headers). If yes, melt/unpivot first.
            2. Fix "24:00" using clean_energy_time.
            3. Resample/Interpolate to 96 points (00:15 to 24:00).
            4. Ensure final output clearly shows "24:00" if requested, matching industry norms.
            """}
        ]
        
        success = False
        generated_code = ""
        
        # 重试机制
        for i in range(3):
            try:
                if i > 0: status.write(f"🔧 自动修正代码 (第 {i} 次)...")
                
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=0.1
                )
                code = response.choices[0].message.content
                # 提取代码块
                if "```python" in code:
                    code = code.split("```python")[1].split("```")[0].strip()
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0].strip()
                
                generated_code = code
                local_scope = {}
                
                # 执行代码
                exec(code, execution_globals, local_scope)
                
                if 'process_step' not in local_scope: 
                    raise ValueError("生成的代码中未找到 process_step 函数")
                
                # 调用处理函数
                new_df = local_scope['process_step'](st.session_state.current_df.copy())
                
                # 结果校验
                if not isinstance(new_df, pd.DataFrame): 
                    if hasattr(new_df, 'data'): new_df = new_df.data
                    else: raise ValueError("函数返回的不是 DataFrame")

                st.session_state.current_df = new_df
                st.session_state.last_successful_code = code
                
                success = True
                status.update(label="✅ 处理成功", state="complete", expanded=False)
                
                st.markdown(f"**✅ 执行完成**")
                st.markdown(f"> 结果数据: {new_df.shape} 行列")
                st.markdown(f"> *已自动识别表格结构并修正 24:00 时间点*")
                
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 处理完成。结果形状: {new_df.shape}"})
                st.rerun()
                break
                
            except Exception as e:
                status.write(f"❌ 代码执行出错: {e}")
                # 将错误回传给 AI 让其重写
                messages.append({"role": "assistant", "content": generated_code})
                messages.append({"role": "user", "content": f"Execution Error: {e}\nPlease fix the code. Ensure you handle '24:00' correctly and check input format."})
        
        if not success:
            st.error("❌ 抱歉，三次尝试均失败。可能是数据格式过于复杂，请检查 AI 生成的代码。")
            with st.expander("查看最后生成的代码"):
                st.code(generated_code, language='python')
            st.session_state.history.pop()
