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

st.title("🤖 AI 数据分析台 (企业稳定版)")
st.caption("专注数据清洗与计算。由于在线预览限制，暂不支持颜色/字体等样式修改。")

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.header("📂 1. 文件区")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = current_hash
                st.session_state.chat_history = [] 
                st.session_state.last_successful_code = None
                st.session_state.chat_history.append({"role": "assistant", "content": "✅ 文件已加载。请下达数据处理指令（如：求和、转置、去重）。"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")

    if st.button("🔥 重置工作区", type="primary"):
        if uploaded_file:
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.last_successful_code = None
            st.rerun()

    # 技能库
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
                        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
                        local_scope = {}
                        exec(macro_data['code'], execution_globals, local_scope)
                        
                        # --- 安全执行封装 ---
                        result_obj = local_scope['process_step'](current_df.copy())
                        
                        # 样式防御
                        if isinstance(result_obj, pd.io.formats.style.Styler):
                            new_df = result_obj.data
                            msg = f"✅ 技能【{name}】执行成功！(已自动过滤不支持的颜色样式)"
                        else:
                            new_df = result_obj
                            msg = f"✅ 技能【{name}】执行成功！"

                        st.session_state.current_df = new_df
                        st.session_state.chat_history.append({"role": "assistant", "content": f"{msg}\n> 说明: {macro_data['explanation']}"})
                        status.update(label="完成", state="complete", expanded=False)
                        st.rerun()
                    except Exception as e:
                        st.error(f"执行失败: {e}")
            with col2:
                if st.button("❌", key=f"del_{name}"):
                    del st.session_state.macros[name]
                    st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        st.download_button("📥 下载当前结果", data=output.getvalue(), file_name=f"Result_{datetime.datetime.now().strftime('%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ================= 3. 主界面 =================
if st.session_state.current_df is None:
    st.info("👈 请上传 Excel 开始")
    st.stop()

st.success(f"当前数据: {st.session_state.current_df.shape[0]} 行, {st.session_state.current_df.shape[1]} 列")

with st.expander("📊 数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 技能保存按钮
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
if user_prompt := st.chat_input("输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    st.session_state.last_successful_code = None
    
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在处理...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 3
        success = False
        
        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
        
        # --- 关键修改：通过 Prompt 管理预期 ---
        system_prompt = """
        你是一个 Python 数据处理专家。你的目标是编写**逻辑严密、通用性强**的 Pandas 代码。
        
        【严重警告：输出格式】
        1. 必须定义 `def process_step(df):`。
        2. 必须包含 explanation 变量。
        3. 仅返回 Python 代码。
        
        【通用数据处理法则（无论用户数据如何变化，必须遵守以下逻辑）】
        
        1. **时间格式的“借与还”逻辑**：
           - **入场检查**：检查列中是否包含 "24:00" 或 "24:00:00"。
             - 若有：设标记 `is_24_end_style = True`，并将其临时替换为 "00:00" 以便计算。
             - 若无（标准00:00-23:xx数据）：设标记 `is_24_end_style = False`，**绝对不要**修改原始数据。
           - **标准化**：转 datetime -> 排序 (`sort_values`) -> 设索引。
        
        2. **全范围数据填充策略**：
           - 当用户要求“插值”或“补全”时，不能只做 `.interpolate()`。
           - **逻辑闭环**：
             1. `df = df.interpolate()` (填补中间空缺)。
             2. **边界检查**：检查首尾是否存在 NaN。
             3. 若头部有 NaN (如00:15但数据始于01:00)：执行 `.bfill()` (向后回填)。
             4. 若尾部有 NaN：执行 `.ffill()` (向前填充)。
             *这样无论用户缺失哪一部分数据，代码都能通用处理。*
        
        3. **输出时的“精准还原” (仅针对 24:00)**：
           - 计算结束后，重置索引。
           - **条件触发**：仅当 `is_24_end_style == True` 时执行还原。
           - **精准定位（防止误伤）**：
             - 先将时间列转为字符串。
             - **只检查最后一行**的数据（或时间为 00:00 的最后一条记录）。
             - 如果最后一行是 "00:00"，则将其替换为 "24:00"。
             - **严禁**对第一行或中间的 "00:00" 进行替换，防止破坏正常的时间起点。
        
        【标准代码结构示例】
        def process_step(df):
            # 1. 预处理 (识别 24:00, 转 datetime, 排序)
            # ...
            
            # 2. 核心计算 (Resample, Interpolate)
            # ...
            
            # 3. 完整性填充 (处理 interpolate 遗漏的首尾 NaN)
            df = df.bfill().ffill() # 简单且通用的双向填充
            
            # 4. 精准还原 (仅在检测到原始偏好为24点且位于末尾时修改)
            # if is_24_end_style and df.iloc[-1]['时间'] == '00:00':
            #     df.at[df.index[-1], '时间'] = '24:00'
            
            return df
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"数据预览:\n{current_df.head(2).to_markdown()}\n需求: {user_prompt}"}
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
                if isinstance(result_obj, pd.io.formats.style.Styler):
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




