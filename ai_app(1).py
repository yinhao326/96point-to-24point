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

st.set_page_config(page_title="AI 数据分析台 (通用智能版)", layout="wide")

# ================= 1. 状态管理 =================
# 初始化核心状态
keys = ["current_df", "chat_history", "file_hash", "macros", 
        "last_successful_code", "last_successful_explanation", 
        "all_sheets", "current_sheet_name", "history"]

for key in keys:
    if key not in st.session_state:
        if key == "macros" or key == "all_sheets": st.session_state[key] = {}
        elif key in ["chat_history", "history"]: st.session_state[key] = []
        elif key == "current_sheet_name": st.session_state[key] = ""
        else: st.session_state[key] = None

st.title("🤖 AI 数据分析台 (通用智能版)")
st.caption("基于数据特征推理 | 无预设行业规则 | 真正的 AI 数据科学家")

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.header("📂 1. 文件区")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                # 读取所有 Sheet
                all_sheets = pd.read_excel(uploaded_file, sheet_name=None)
                st.session_state.all_sheets = all_sheets
                st.session_state.file_hash = current_hash
                
                # 初始化第一个 Sheet
                first_sheet = list(all_sheets.keys())[0]
                st.session_state.current_sheet_name = first_sheet
                st.session_state.current_df = all_sheets[first_sheet].copy()
                
                # 重置
                st.session_state.chat_history = [] 
                st.session_state.history = [] 
                st.session_state.last_successful_code = None
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 文件已加载，共 {len(all_sheets)} 个工作表。我已准备好分析任意类型的数据。"})
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
            # 自动保存旧表
            old_name = st.session_state.current_sheet_name
            if st.session_state.current_df is not None:
                st.session_state.all_sheets[old_name] = st.session_state.current_df.copy()
            
            # 加载新表
            st.session_state.current_sheet_name = selected_sheet
            st.session_state.current_df = st.session_state.all_sheets[selected_sheet].copy()
            st.session_state.history = [] # 换表清空撤销
            st.rerun()

    if st.button("🔥 重置工作区", type="primary"):
        if uploaded_file:
            st.session_state.file_hash = None # 触发重新加载
            st.rerun()

    # 技能库 (保持不变)
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
                        st.session_state.history.append(current_df.copy()) # 备份
                        
                        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
                        local_scope = {}
                        exec(macro_data['code'], execution_globals, local_scope)
                        result_obj = local_scope['process_step'](current_df.copy())
                        
                        # 处理返回值
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

# 撤销工具栏
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
    st.success(f"当前表: **{st.session_state.current_sheet_name}** | 形状: {st.session_state.current_df.shape}")

# 数据预览
with st.expander("📊 数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

# 聊天记录
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 保存技能
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

# ================= 4. 核心智能引擎 (V24: General Intelligence) =================
def get_dataframe_info(df):
    """
    提取数据特征，辅助 AI 进行推理，而不是盲猜。
    """
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()
    
    # 提取时间特征
    time_info = "Time Index: No"
    if pd.api.types.is_datetime64_any_dtype(df.index):
        time_info = f"Time Index: Yes (Start: {df.index.min()}, End: {df.index.max()}, Freq: {df.index.freq})"
    
    return f"""
    [Data Structure Analysis]
    Shape: {df.shape}
    Columns: {list(df.columns)}
    Index Type: {type(df.index)}
    {time_info}
    
    [df.info() output]
    {info_str}
    """

if user_prompt := st.chat_input("请输入指令 (支持复杂逻辑)..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.last_successful_code = None
    st.session_state.history.append(st.session_state.current_df.copy()) # 备份
    
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在分析数据特征...", expanded=True)
        
        current_df = st.session_state.current_df
        df_meta_info = get_dataframe_info(current_df) # 获取元数据
        
        MAX_RETRIES = 3
        success = False
        
        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
        
        # --- V24 通用智能 Prompt ---
        # 核心改变：
        # 1. 不再教它具体的“行业规则”，而是教它“数据分析方法论”。
        # 2. 强制要求 Think Step，让它先检查数据的一致性。
        system_prompt = """
        You are an advanced Python Data Scientist Expert.
        
        【Goal】
        Write a Python function `def process_step(df):` to manipulate the dataframe `df` according to the user's request.
        
        【Critical Strategy - THOUGHT PROCESS】
        Before writing code, you MUST analyze the provided [Data Structure Analysis].
        1. **Check Index**: Is it a datetime index? Is it continuous? 
        2. **Check Shape**: If user wants to expand data (e.g. 24 -> 96), simple resampling might fail if start/end times are missing. **You need to explicitly generate a full DateRange index and reindex.**
        3. **Check Types**: Are columns numeric? Do they need conversion before calculation?
        
        【Output Rules】
        1. Output valid Python code ONLY. 
        2. NO Markdown blocks in the code output (just the code).
        3. **Robustness**: 
           - Handle potential missing values.
           - If using `resample`, consider `closed` and `label` carefully based on the context (e.g., if data represents "end of period", strictly use right/right).
           - If creating new time points, PREFER `pd.date_range()` + `reindex()` over `resample()` to guarantee exact row counts.
        
        【Template】
        def process_step(df):
            # Your logic here
            # ...
            return df
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
            [Context]
            Current Sheet: {st.session_state.current_sheet_name}
            
            {df_meta_info}
            
            [Data Preview (First 5 rows)]
            {current_df.head(5).to_markdown()}
            
            [User Request]
            {user_prompt}
            """}
        ]

        for i in range(MAX_RETRIES):
            try:
                if i > 0: status.write(f"🔧 第 {i} 次自动修正逻辑...")
                
                # 思考阶段 (模拟 R1)
                response = client.chat.completions.create(
                    model="deepseek-chat", messages=messages, temperature=0.2 # 稍微提高一点温度，增加灵活性
                )
                code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                # 尝试编译
                local_scope = {}
                exec(code, execution_globals, local_scope)
                
                if 'process_step' not in local_scope: raise ValueError("函数 process_step 丢失")
                
                # 执行
                result_obj = local_scope['process_step'](current_df.copy())
                
                # 结果校验
                if isinstance(result_obj, pd.io.formats.style.Styler):
                    new_df = result_obj.data
                    note = " (样式已过滤)"
                elif isinstance(result_obj, pd.DataFrame):
                    new_df = result_obj
                    note = ""
                else:
                    raise ValueError(f"返回类型错误: {type(result_obj)}")
                
                # 成功处理
                st.session_state.current_df = new_df
                st.session_state.all_sheets[st.session_state.current_sheet_name] = new_df
                st.session_state.last_successful_code = code
                st.session_state.last_successful_explanation = f"处理成功。结果形状: {new_df.shape}"
                
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                # 生成简短解释
                st.markdown(f"**✅ 执行完成**\n> 结果包含 {new_df.shape[0]} 行, {new_df.shape[1]} 列{note}")
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 执行完成。结果形状: {new_df.shape}"})
                st.rerun()
                break

            except Exception as e:
                error_msg = str(e)
                status.write(f"❌ 错误: {error_msg}")
                # 将错误反馈给 AI，让它自我修正
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"Code execution failed:\n{error_msg}\n\nPlease analyze the data structure again and fix the code. If it's a 'shape mismatch' or 'index' issue, try to rebuild the index explicitly."})
        
        if not success:
            status.update(label="❌ 无法处理", state="error")
            st.session_state.history.pop() # 恢复撤销栈
            st.error("AI 无法理解或执行该指令。建议检查数据格式是否规范。")