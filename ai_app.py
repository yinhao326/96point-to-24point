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
        # --- 16.0 全能通用版 System Prompt (智能+安全) ---
        system_prompt = """
        You are a Python coding machine. 
        Output ONLY valid Python code. 
        NO markdown. NO text explanation.
        
        import pandas as pd
        import numpy as np

        def process_step(df):
            # --- 1. 智能预处理 ---
            df = df.astype(str)
            time_col = df.columns[0] # 自动识别第一列为时间

            # 智能检测是否包含 24:00 风格
            has_24 = df.apply(lambda x: x.str.contains('24:00')).any().any()

            # 统一清理：即使没有24:00，跑一遍replace也没坏处
            df = df.replace({'24:00': '00:00', '24:00:00': '00:00:00'}, regex=True)
            df[time_col] = pd.to_datetime(df[time_col])

            # 【核心保护逻辑】仅在检测到24:00风格时启动
            # 防止 24:00 (原本是终点) 变 00:00 (起点) 导致排序错乱
            if has_24:
                last_val = df.iat[-1, 0]
                # 简单粗暴判断：如果最后一行变成了0点，说明它是原来的24点，给它加一天
                if last_val.hour == 0 and last_val.minute == 0:
                    df.iat[-1, 0] = df.iat[-1, 0] + pd.Timedelta(days=1)

            # --- 2. 构建通用时间轴 ---
            df = df.set_index(time_col).sort_index()

            # 动态获取起止时间
            # 这里的逻辑兼容性极强：
            # 如果是24点数据，end_target 已经是加了一天的次日00:00
            # 如果是普通数据，end_target 就是正常的结束时间
            start_target = df.index[0]
            end_target = df.index[-1]

            # 设定目标频率：默认15T，但如果指令要求其他，AI生成的代码应在此处动态调整
            # 为了通用性，我们设定一个变量，AI根据用户意图修改这个字符串即可
            # 在此固定模版中，我们暂定 '15T' 满足当前需求，
            # *但在真正的通用场景下，这里会根据用户 prompt 变为 '30T' 或 '1H'*
            target_freq = '15T' 

            # 如果用户希望从 00:15 开始 (针对特定业务)，修正 start_target
            # 这种修正可以保留，因为它对普通数据影响不大（只会补全前面的一点点）
            if start_target.hour == 0 and start_target.minute > 0:
                 pass # 保持原样
            elif start_target.hour >= 1:
                 # 如果数据从1点开始，强制把起点拉回当天的00:15 (为了满足补全要求)
                 start_target = start_target.floor('D') + pd.Timedelta(minutes=15)

            # 生成骨架 (Reindex 策略，永不丢失尾部)
            full_grid = pd.date_range(start=start_target, end=end_target, freq=target_freq)
            df = df.reindex(full_grid)

            # --- 3. 通用填充 ---
            df = df.interpolate(method='linear')
            df = df.bfill().ffill()

            # --- 4. 智能还原 ---
            df = df.reset_index()
            df.rename(columns={'index': time_col}, inplace=True)
            df[time_col] = df[time_col].dt.strftime('%H:%M')

            # 只有当原始数据有24点，且最后一行正好是00:00时，才还原
            if has_24:
                # 检查最后一行是否是 "00:00"
                if df.iat[-1, 0] == '00:00':
                    df.iat[-1, 0] = '24:00'

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









