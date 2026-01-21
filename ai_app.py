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

st.set_page_config(page_title="AI 智能数据工作台", layout="wide")

# ================= 1. 核心状态初始化 =================
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] 
if "file_hash" not in st.session_state:
    st.session_state.file_hash = None
# 新增：技能库 (Macros)
if "macros" not in st.session_state:
    st.session_state.macros = {} 
# 新增：当前待保存的代码缓存
if "last_successful_code" not in st.session_state:
    st.session_state.last_successful_code = None
if "last_successful_explanation" not in st.session_state:
    st.session_state.last_successful_explanation = None

st.title("🤖 AI 智能数据工作台 (技能库版)")
st.caption("上传 -> 对话 -> 保存技能 -> 下次一键复用")

# ================= 2. 侧边栏：文件与技能 =================
with st.sidebar:
    st.header("📂 1. 文件操作")
    
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if st.session_state.file_hash != current_hash:
            try:
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = current_hash
                st.session_state.chat_history = [] 
                st.session_state.last_successful_code = None # 换文件后清空缓存
                st.session_state.chat_history.append({"role": "assistant", "content": "新文件已加载！你可以输入指令，或点击下方【技能库】中的按钮直接处理。"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")
    else:
        if st.session_state.current_df is not None:
            st.session_state.current_df = None
            st.session_state.file_hash = None
            st.session_state.chat_history = []
            st.rerun()

    if st.button("🔥 深度重置 / 重新开始", type="primary"):
        if uploaded_file:
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.last_successful_code = None
            st.rerun()

    # --- 新增功能：技能库面板 ---
    if st.session_state.macros:
        st.divider()
        st.header("⚡ 2. 技能库 (点击即运行)")
        st.caption("针对相同格式的文件，直接复用已有逻辑。")
        
        # 遍历显示所有保存的技能
        for name, macro_data in st.session_state.macros.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                if st.button(f"▶️ {name}", key=f"btn_{name}", use_container_width=True):
                    # === 核心：直接执行保存的代码 ===
                    try:
                        status = st.status(f"正在执行技能：{name}...", expanded=True)
                        current_df = st.session_state.current_df
                        
                        # 准备环境
                        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
                        local_scope = {}
                        
                        # 执行代码
                        exec(macro_data['code'], execution_globals, local_scope)
                        new_df = local_scope['process_step'](current_df.copy())
                        
                        # 更新状态
                        st.session_state.current_df = new_df
                        st.session_state.chat_history.append({"role": "assistant", "content": f"✅ 已通过技能 **【{name}】** 完成处理。\n\n> 逻辑说明: {macro_data['explanation']}"})
                        status.update(label="✅ 技能执行成功", state="complete", expanded=False)
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"技能执行失败: {e}")
                        st.caption("原因可能是当前文件结构与保存技能时文件结构不一致。")
            with col2:
                # 删除技能按钮
                if st.button("❌", key=f"del_{name}"):
                    del st.session_state.macros[name]
                    st.rerun()

    # 下载区域
    if st.session_state.current_df is not None:
        st.divider()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        
        st.download_button(
            label="📥 下载当前进度",
            data=output.getvalue(),
            file_name=f"Result_{datetime.datetime.now().strftime('%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ================= 3. 主界面 =================

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传 Excel 文件")
    st.stop()

st.success(f"当前数据: {st.session_state.current_df.shape[0]} 行, {st.session_state.current_df.shape[1]} 列")

with st.expander("📊 数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 新增功能：技能保存区 (仅在有成功执行的代码时显示) ---
if st.session_state.last_successful_code:
    with st.container():
        st.info("💡 觉得刚才的操作很完美？把它保存下来！")
        c1, c2 = st.columns([3, 1])
        with c1:
            macro_name = st.text_input("给这个技能起个名字", placeholder="例如：转1小时均值并求和", label_visibility="collapsed")
        with c2:
            if st.button("💾 保存为技能"):
                if macro_name:
                    st.session_state.macros[macro_name] = {
                        "code": st.session_state.last_successful_code,
                        "explanation": st.session_state.last_successful_explanation
                    }
                    st.success(f"技能【{macro_name}】已保存到左侧侧边栏！")
                    # 延时刷新让用户看到成功提示
                    import time
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("请输入名称")

# ================= 4. AI 处理引擎 =================
if user_prompt := st.chat_input("输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    # 清空之前的缓存，避免保存了旧代码
    st.session_state.last_successful_code = None
    
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在分析...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 3
        success = False
        
        execution_globals = {"pd": pd, "np": np, "re": re, "math": math, "datetime": datetime}
        
        system_prompt = """
        你是一个 Python 数据处理专家。
        任务：编写 `process_step(df)` 和 `explanation` 字符串。
        规则：Pandas > 2.0，禁用 append，必须处理空值，解释逻辑。
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
                
                new_df = local_scope['process_step'](current_df.copy())
                
                # 成功！更新状态
                st.session_state.current_df = new_df
                
                # --- 关键：保存成功的代码到缓存，供用户保存为技能 ---
                st.session_state.last_successful_code = code
                st.session_state.last_successful_explanation = local_scope['explanation']
                
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                final_response = f"""
                **🧐 逻辑核对:**
                > {local_scope['explanation']}
                """
                st.markdown(final_response)
                st.session_state.chat_history.append({"role": "assistant", "content": final_response})
                st.rerun()
                break

            except Exception as e:
                error_info = f"{type(e).__name__}: {str(e)}"
                status.write(f"❌ 错误: {error_info}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"报错: {error_info}\n请修正代码。"})
        
        if not success:
            status.update(label="❌ 失败", state="error")
            st.error("无法完成任务。")
