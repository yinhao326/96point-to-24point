import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
import datetime
from openai import OpenAI
import traceback

# ================= 配置区域 =================
if "DEEPSEEK_API_KEY" in st.secrets:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    st.error("请在 Secrets 中配置 DEEPSEEK_API_KEY")
    st.stop()

BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

st.set_page_config(page_title="AI 数据分析台 (V25 双核版)", layout="wide")

# ================= 1. 状态管理 =================
keys = ["current_df", "chat_history", "file_hash", "macros", 
        "last_successful_code", "last_successful_explanation", 
        "all_sheets", "current_sheet_name", "history"]

for key in keys:
    if key not in st.session_state:
        if key == "macros" or key == "all_sheets": st.session_state[key] = {}
        elif key in ["chat_history", "history"]: st.session_state[key] = []
        elif key == "current_sheet_name": st.session_state[key] = ""
        else: st.session_state[key] = None

st.title("🤖 AI 数据分析台 (V25 双核切换版)")
st.caption("支持 DeepSeek-V3 (快速) 与 DeepSeek-R1 (深度推理) 自由切换")

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.header("🧠 模型选择")
    # --- V25 新增：模型切换器 ---
    model_map = {
        "DeepSeek-V3 (快速/通用)": "deepseek-chat",
        "DeepSeek-R1 (深度推理/聪明)": "deepseek-reasoner"
    }
    selected_model_label = st.radio("选择大脑：", list(model_map.keys()))
    selected_model = model_map[selected_model_label]
    
    if selected_model == "deepseek-reasoner":
        st.info("ℹ️ R1 模式下思考时间较长，但逻辑能力更强，适合处理复杂转换。")
    
    st.divider()
    
    st.header("📂 1. 文件区")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                all_sheets = pd.read_excel(uploaded_file, sheet_name=None)
                st.session_state.all_sheets = all_sheets
                st.session_state.file_hash = current_hash
                
                first_sheet = list(all_sheets.keys())[0]
                st.session_state.current_sheet_name = first_sheet
                st.session_state.current_df = all_sheets[first_sheet].copy()
                
                st.session_state.chat_history = [] 
                st.session_state.history = [] 
                st.session_state.last_successful_code = None
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 文件已加载。当前使用模型：**{selected_model_label}**"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")

    # 工作表切换
    if st.session_state.all_sheets:
        st.divider()
        st.markdown("### 📑 选择工作表")
        sheet_names = list(st.session_state.all_sheets.keys())
        try:
            current_index = sheet_names.index(st.session_state.current_sheet_name)
        except ValueError:
            current_index = 0
        selected_sheet = st.selectbox("当前处理：", options=sheet_names, index=current_index, key="sheet_selector")

        if selected_sheet != st.session_state.current_sheet_name:
            old_name = st.session_state.current_sheet_name
            if st.session_state.current_df is not None:
                st.session_state.all_sheets[old_name] = st.session_state.current_df.copy()
            st.session_state.current_sheet_name = selected_sheet
            st.session_state.current_df = st.session_state.all_sheets[selected_sheet].copy()
            st.session_state.history = []
            st.rerun()

    if st.button("🔥 重置工作区", type="primary"):
        if uploaded_file:
            st.session_state.file_hash = None
            st.rerun()

    # 技能库
    if st.session_state.macros:
        st.divider()
        st.header("⚡ 2. 常用功能库")
        for name, macro_data in st.session_state.macros.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(f"▶️ {name}", key=f"btn_{name}", use_container_width=True):
                    try:
                        status = st.status(f"执行：{name}...", expanded=True)
                        current_df = st.session_state.current_df
                        st.session_state.history.append(current_df.copy())
                        
                        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
                        local_scope = {}
                        exec(macro_data['code'], execution_globals, local_scope)
                        result_obj = local_scope['process_step'](current_df.copy())
                        
                        new_df = result_obj.data if isinstance(result_obj, pd.io.formats.style.Styler) else result_obj
                        
                        st.session_state.current_df = new_df
                        st.session_state.all_sheets[st.session_state.current_sheet_name] = new_df
                        st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 技能【{name}】执行成功！"})
                        status.update(label="完成", state="complete", expanded=False)
                        st.rerun()
                    except Exception as e:
                        st.error(f"执行失败: {e}")
                        if st.session_state.history: st.session_state.current_df = st.session_state.history.pop()
            with col2:
                if st.button("❌", key=f"del_{name}"):
                    del st.session_state.macros[name]
                    st.rerun()

    # 下载
    if st.session_state.current_df is not None:
        st.divider()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, sheet_df in st.session_state.all_sheets.items():
                save_df = st.session_state.current_df if sheet_name == st.session_state.current_sheet_name else sheet_df
                save_df.to_excel(writer, sheet_name=sheet_name, index=True)
        st.download_button("📥 下载完整结果", data=output.getvalue(), file_name="Result.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ================= 3. 主界面 =================
if st.session_state.current_df is None:
    st.info("👈 请上传 Excel 开始")
    st.stop()

col_tool_1, col_tool_2 = st.columns([1, 5])
with col_tool_1:
    if st.button("↩️ 撤销", use_container_width=True):
        if len(st.session_state.history) > 0:
            last_df = st.session_state.history.pop()
            st.session_state.current_df = last_df
            st.session_state.all_sheets[st.session_state.current_sheet_name] = last_df
            st.success("已撤销")
            st.rerun()
        else:
            st.warning("无步骤可撤销")
with col_tool_2:
    st.success(f"当前表: **{st.session_state.current_sheet_name}** | 形状: {st.session_state.current_df.shape} | 🧠 模型: {selected_model_label}")

with st.expander("📊 数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.session_state.last_successful_code:
    with st.container():
        c1, c2 = st.columns([3, 1])
        with c1: macro_name = st.text_input("功能命名", placeholder="给刚才的操作起名", label_visibility="collapsed")
        with c2: 
            if st.button("💾 保存"):
                if macro_name:
                    st.session_state.macros[macro_name] = {"code": st.session_state.last_successful_code, "explanation": st.session_state.last_successful_explanation}
                    st.success("已保存")
                    st.rerun()

# ================= 4. 核心智能引擎 =================
def get_dataframe_info(df):
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()
    time_info = "Time Index: No"
    if pd.api.types.is_datetime64_any_dtype(df.index):
        time_info = f"Time Index: Yes (Start: {df.index.min()}, End: {df.index.max()}, Freq: {df.index.freq})"
    return f"""
    [Data Structure Analysis]
    Shape: {df.shape}
    Columns: {list(df.columns)}
    Index Type: {type(df.index)}
    {time_info}
    [df.info() output] {info_str}
    """

if user_prompt := st.chat_input("请输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.last_successful_code = None
    st.session_state.history.append(st.session_state.current_df.copy())
    
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        # 动态显示正在使用的模型
        status_msg = f"🧠 AI ({selected_model}) 正在分析数据..."
        status = st.status(status_msg, expanded=True)
        
        current_df = st.session_state.current_df
        df_meta_info = get_dataframe_info(current_df)
        
        MAX_RETRIES = 3
        success = False
        
        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
        
        # System Prompt (通用版)
        system_prompt = """
        You are an advanced Python Data Scientist Expert.
        
        【Goal】
        Write a Python function `def process_step(df):` to manipulate the dataframe `df`.
        
        【Strategy】
        1. Analyze [Data Structure Analysis] carefully.
        2. If expanding data (e.g. 24->96 points), construct a FULL Index explicitly using `pd.date_range`. Do not rely on simple resampling.
        3. Check column types before calculation.
        
        【Output】
        Output valid Python code ONLY. No markdown blocks.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
            [Meta Info]
            Sheet: {st.session_state.current_sheet_name}
            {df_meta_info}
            
            [Preview]
            {current_df.head(5).to_markdown()}
            
            [Request]
            {user_prompt}
            """}
        ]

        for i in range(MAX_RETRIES):
            try:
                if i > 0: status.write(f"🔧 第 {i} 次修正...")
                
                # --- 关键：在这里调用选中的模型 ---
                response = client.chat.completions.create(
                    model=selected_model,  # <--- 动态调用 V3 或 R1
                    messages=messages, 
                    temperature=0.2
                )
                code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                # R1 模型可能会在代码前后加一些思维链文字（虽然通常被隐藏），用正则提取纯代码
                # 简单的提取逻辑：找 def process_step 这里的代码块
                if "def process_step(df):" not in code:
                    # 尝试更强力的清洗
                    pass 
                
                local_scope = {}
                exec(code, execution_globals, local_scope)
                if 'process_step' not in local_scope: raise ValueError("函数 process_step 丢失")
                
                result_obj = local_scope['process_step'](current_df.copy())
                
                if isinstance(result_obj, pd.io.formats.style.Styler):
                    new_df = result_obj.data
                elif isinstance(result_obj, pd.DataFrame):
                    new_df = result_obj
                else:
                    raise ValueError(f"返回类型错误: {type(result_obj)}")
                
                st.session_state.current_df = new_df
                st.session_state.all_sheets[st.session_state.current_sheet_name] = new_df
                st.session_state.last_successful_code = code
                st.session_state.last_successful_explanation = f"由 {selected_model} 处理成功"
                
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                st.markdown(f"**✅ 执行完成** ({selected_model})\n> 结果形状: {new_df.shape}")
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 执行完成 ({selected_model})。结果形状: {new_df.shape}"})
                st.rerun()
                break

            except Exception as e:
                error_msg = str(e)
                status.write(f"❌ 错误: {error_msg}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"Error: {error_msg}\nPlease fix code based on data structure."})
        
        if not success:
            status.update(label="❌ 无法处理", state="error")
            st.session_state.history.pop()
            st.error(f"AI ({selected_model}) 无法完成指令。建议尝试切换模型或简化指令。")
