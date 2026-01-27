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

st.set_page_config(page_title="AI 数据分析台", layout="wide")

# ================= 1. 状态管理 =================
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] 
if "file_hash" not in st.session_state:
    st.session_state.file_hash = None
if "macros" not in st.session_state:
    st.session_state.macros = {} 
if "last_successful_code" not in st.session_state:
    st.session_state.last_successful_code = None
if "last_successful_explanation" not in st.session_state:
    st.session_state.last_successful_explanation = None
    
# --- V22 新增状态 ---
if "all_sheets" not in st.session_state:
    st.session_state.all_sheets = {} # 存储所有 Sheet
if "current_sheet_name" not in st.session_state:
    st.session_state.current_sheet_name = ""
if "history" not in st.session_state:
    st.session_state.history = [] # 撤销栈

st.title("🤖 AI 数据分析台 (林洋内部版)")
st.caption("专注数据清洗与计算 | 支持多 Sheet 切换 | 支持撤销回退")

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.header("📂 1. 文件区")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                # --- V22 修改：读取所有 Sheet ---
                all_sheets = pd.read_excel(uploaded_file, sheet_name=None)
                st.session_state.all_sheets = all_sheets
                st.session_state.file_hash = current_hash
                
                # 默认选中第一个 Sheet
                first_sheet = list(all_sheets.keys())[0]
                st.session_state.current_sheet_name = first_sheet
                st.session_state.current_df = all_sheets[first_sheet].copy()
                
                # 重置状态
                st.session_state.chat_history = [] 
                st.session_state.history = [] # 清空撤销
                st.session_state.last_successful_code = None
                st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 文件已加载，共 {len(all_sheets)} 个工作表。请选择工作表并下达指令。"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")

    # --- V22 新增：工作表切换器 ---
    if st.session_state.all_sheets:
        st.divider()
        st.markdown("### 📑 选择工作表")
        sheet_names = list(st.session_state.all_sheets.keys())
        
        # 确保当前选中项有效
        try:
            current_index = sheet_names.index(st.session_state.current_sheet_name)
        except ValueError:
            current_index = 0

        selected_sheet = st.selectbox(
            "当前处理：", 
            options=sheet_names, 
            index=current_index,
            key="sheet_selector"
        )

        # 切换逻辑
        if selected_sheet != st.session_state.current_sheet_name:
            # 1. 保存旧表进度
            old_name = st.session_state.current_sheet_name
            if st.session_state.current_df is not None:
                st.session_state.all_sheets[old_name] = st.session_state.current_df.copy()
            
            # 2. 加载新表
            st.session_state.current_sheet_name = selected_sheet
            st.session_state.current_df = st.session_state.all_sheets[selected_sheet].copy()
            
            # 3. 清空撤销栈 (换表了，之前的撤销记录就不适用了)
            st.session_state.history = []
            st.toast(f"已切换至: {selected_sheet}", icon="🔄")
            st.rerun()

    if st.button("🔥 重置工作区", type="primary"):
        if uploaded_file:
            # 重读文件
            all_sheets = pd.read_excel(uploaded_file, sheet_name=None)
            st.session_state.all_sheets = all_sheets
            first_sheet = list(all_sheets.keys())[0]
            st.session_state.current_sheet_name = first_sheet
            st.session_state.current_df = all_sheets[first_sheet].copy()
            st.session_state.chat_history = []
            st.session_state.history = []
            st.session_state.last_successful_code = None
            st.rerun()

    # 技能库 (V18 原有功能保留)
    if st.session_state.macros:
        st.divider()
        st.header("⚡ 2. 常用功能库")
        for name, macro_data in st.session_state.macros.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(f"▶️ {name}", key=f"btn_{name}", use_container_width=True):
                    # 执行宏
                    try:
                        status = st.status(f"执行：{name}...", expanded=True)
                        current_df = st.session_state.current_df
                        
                        # --- V22 新增：执行宏前先备份 (Undo) ---
                        st.session_state.history.append(current_df.copy())
                        
                        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
                        local_scope = {}
                        exec(macro_data['code'], execution_globals, local_scope)
                        
                        # --- 安全执行封装 ---
                        result_obj = local_scope['process_step'](current_df.copy())
                        
                        # --- 版本兼容的 Styler 检查 ---
                        is_styler = False
                        try:
                            # 尝试新版本导入
                            from pandas.io.formats.style import Styler
                            is_styler = isinstance(result_obj, Styler)
                        except ImportError:
                            try:
                                # 尝试旧版本导入
                                from pandas.formats.style import Styler
                                is_styler = isinstance(result_obj, Styler)
                            except ImportError:
                                # 通用检查
                                is_styler = hasattr(result_obj, 'data') and hasattr(result_obj, 'render')
                        
                        if is_styler:
                            new_df = result_obj.data
                            msg = f"✅ 技能【{name}】执行成功！(已自动过滤不支持的颜色样式)"
                        else:
                            new_df = result_obj
                            msg = f"✅ 技能【{name}】执行成功！"

                        st.session_state.current_df = new_df
                        # --- V22 新增：同步到 all_sheets ---
                        st.session_state.all_sheets[st.session_state.current_sheet_name] = new_df
                        
                        st.session_state.chat_history.append({"role": "assistant", "content": f"{msg}\n> 说明: {macro_data['explanation']}"})
                        status.update(label="完成", state="complete", expanded=False)
                        st.rerun()
                    except Exception as e:
                        st.error(f"执行失败: {e}")
                        # 回滚
                        if st.session_state.history:
                            st.session_state.current_df = st.session_state.history.pop()
            with col2:
                if st.button("❌", key=f"del_{name}"):
                    del st.session_state.macros[name]
                    st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        # --- V22 修改：下载逻辑包含所有工作表 ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, sheet_df in st.session_state.all_sheets.items():
                # 确保当前正在编辑的表也是最新的
                if sheet_name == st.session_state.current_sheet_name:
                    st.session_state.current_df.to_excel(writer, sheet_name=sheet_name, index=True)
                else:
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=True)
                    
        st.download_button("📥 下载完整结果 (含所有表)", data=output.getvalue(), file_name=f"Result_{datetime.datetime.now().strftime('%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ================= 3. 主界面 =================
if st.session_state.current_df is None:
    st.info("👈 请上传 Excel 开始")
    st.stop()

# --- V22 新增：撤销按钮区域 ---
col_tool_1, col_tool_2 = st.columns([1, 5])
with col_tool_1:
    if st.button("↩️ 撤销上一步", use_container_width=True):
        if len(st.session_state.history) > 0:
            last_df = st.session_state.history.pop()
            st.session_state.current_df = last_df
            # 同步回 all_sheets
            st.session_state.all_sheets[st.session_state.current_sheet_name] = last_df
            
            # 移除最后一条 AI 回复（如果需要的话，不仅回退数据，也回退对话界面看起来更合理）
            if len(st.session_state.chat_history) > 0:
                 # 简单逻辑：移除最后一次交互（用户+AI）
                 # 实际操作中，为了保险，这里只回退数据，对话记录保留作为参考
                 pass
            
            st.success("已回到上一步状态")
            st.rerun()
        else:
            st.warning("没有可撤销的步骤了")

with col_tool_2:
    st.success(f"当前表: **{st.session_state.current_sheet_name}** | {st.session_state.current_df.shape[0]} 行, {st.session_state.current_df.shape[1]} 列")

with st.expander("📊 数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 技能保存按钮 (保留 V18 功能)
if st.session_state.last_successful_code:
    with st.container():
        c1, c2 = st.columns([3, 1])
        with c1:
            macro_name = st.text_input("功能命名", placeholder="给刚才的操作起个名", label_visibility="collapsed")
        with c2:
            if st.button("💾 保存为常用功能"):
                if macro_name:
                    st.session_state.macros[macro_name] = {
                        "code": st.session_state.last_successful_code,
                        "explanation": st.session_state.last_successful_explanation
                    }
                    st.success("已保存！")
                    import time
                    time.sleep(1)
                    st.rerun()

# ================= 4. 核心引擎 (含安全气囊) =================
if user_prompt := st.chat_input("对当前工作表下达指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.last_successful_code = None
    
    # --- V22 新增：操作前自动备份 ---
    st.session_state.history.append(st.session_state.current_df.copy())
    
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在处理...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 3
        success = False
        
        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
        
        # --- 16.0 全能通用版 System Prompt (智能+安全) ---
        system_prompt = """
        You are an expert Python Data Scientist for the Energy/Power industry.
        
        【Output Rules - STRICT】
        1. Output ONLY valid Python code. NO markdown (```). NO text.
        2. The code MUST contain `def process_step(df):`.
        3. IGNORE non-data sheets (Smart Guard is active).
        
        【Industry Domain Knowledge (CRITICAL)】
        You must apply the following default logic to ALL user queries unless explicitly told otherwise:
        
        1. **Time Representation**: In this domain, a timestamp (e.g., 01:00) represents the **END** of a period, not the start.
        2. **Resampling/Aggregation**: 
           - When converting frequency (e.g., 15min -> 1H), you MUST use **right-closed intervals**.
           - Code pattern: `df.resample('...', closed='right', label='right').mean()` (or sum).
           - **NEVER** use the default pandas behavior (which is left-closed).
           - Example: 01:00 hourly mean = average of (00:15, 00:30, 00:45, 01:00).
        3. **24:00 Handling**:
           - If '24:00' exists, treat it as the end of the day.
           - Ensure calculations (like mean) include this 24:00 point correctly in the last interval.
        
        【Smart Guard Clause】
        (Include this at the start of your code)
        - Check if df is empty or first column is not time-like/string-like. If so, `return df`.
        
        【Task】
        Generate `def process_step(df):` to fulfill the user's natural language request, applying the Industry Knowledge above automatically.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Current Sheet: {st.session_state.current_sheet_name}\nData Preview:\n{current_df.head(2).to_markdown()}\n需求: {user_prompt}"}
        ]

        for i in range(MAX_RETRIES):
            try:
                if i > 0: status.write(f"🔧 第 {i} 次自动修正中...")
                
                response = client.chat.completions.create(
                    model="deepseek-chat", messages=messages, temperature=0.1
                )
                code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                local_scope = {}
                exec(code, execution_globals, local_scope)
                
                if 'process_step' not in local_scope: raise ValueError("函数丢失")
                if 'explanation' not in local_scope: local_scope['explanation'] = "AI 未提供解释"
                
                # 执行处理
                result_obj = local_scope['process_step'](current_df.copy())
                
                # =========== 🛡️ 安全气囊：防样式崩溃系统 ===========
                warning_note = ""
                # 检测返回值是不是 Styler (Pandas 的样式对象)
                # 版本兼容的 Styler 检查
                is_styler = False
                try:
                    # 尝试新版本导入
                    from pandas.io.formats.style import Styler
                    is_styler = isinstance(result_obj, Styler)
                except ImportError:
                    try:
                        # 尝试旧版本导入
                        from pandas.formats.style import Styler
                        is_styler = isinstance(result_obj, Styler)
                    except ImportError:
                        # 通用检查：有 data 和 render 方法的就是 Styler
                        is_styler = hasattr(result_obj, 'data') and hasattr(result_obj, 'render')

                if is_styler:
                    # 如果是，强制取回纯数据 (.data)
                    new_df = result_obj.data
                    warning_note = "\n\n⚠️ **系统提示**：检测到包含颜色/样式指令。为防止系统崩溃，已自动过滤样式，仅保留处理后的数据结果。"
                elif isinstance(result_obj, pd.DataFrame):
                    new_df = result_obj
                else:
                    raise ValueError(f"AI 返回了不支持的数据类型: {type(result_obj)}")
                # ===============================================
                
                # 成功
                st.session_state.current_df = new_df
                # --- V22 新增：同步到 all_sheets ---
                st.session_state.all_sheets[st.session_state.current_sheet_name] = new_df
                
                st.session_state.last_successful_code = code
                st.session_state.last_successful_explanation = local_scope['explanation'] + warning_note
                
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                final_response = f"""
                **🧐 结果说明:**
                > {st.session_state.last_successful_explanation}
                """
                st.markdown(final_response)
                st.session_state.chat_history.append({"role": "assistant", "content": final_response})
                st.rerun()
                break

            except Exception as e:
                error_info = f"{type(e).__name__}: {str(e)}"
                status.write(f"❌ 内部尝试错误: {error_info}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"代码执行报错: {error_info}\n请修正。如果是因为尝试使用 .style 或样式功能导致，请去掉样式代码，只处理数据！"})
        
        if not success:
            status.update(label="❌ 无法处理", state="error")
            # 回退数据（虽然还没覆盖，但清理一下栈比较好）
            st.session_state.history.pop() 
            
            # --- 最终兜底：给用户一个体面的台阶 ---
            fail_msg = """
            **🤔 抱歉，这个需求有点超出我的能力范围。**
            
            可能的原因：
            1. **涉及复杂的 Excel 样式/颜色**（我目前只能处理数据计算，还不会画画）。
            2. 数据结构极其特殊，逻辑无法对齐。
            
            建议：**简化指令**，例如先只做数据计算，下载后再去 Excel 里调整颜色。
            """
            st.error(fail_msg)
            st.session_state.chat_history.append({"role": "assistant", "content": fail_msg})
