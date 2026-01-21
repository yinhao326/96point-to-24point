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

st.set_page_config(page_title="AI 智能数据助手", layout="wide")

# ================= 1. 核心状态初始化 (记忆库) =================
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] 
if "file_hash" not in st.session_state:
    st.session_state.file_hash = None # 用于判断文件是否更换

st.title("🤖 AI 智能数据助手 (安全存档版)")
st.caption("支持中途下载存档。处理到一半点击下载，数据不会丢失，可继续对话。")

# ================= 2. 侧边栏：文件与控制 =================
with st.sidebar:
    st.header("📂 文件中心")
    
    # [A] 文件上传区
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    # [B] 文件加载逻辑 (带防重置锁)
    if uploaded_file:
        # 计算新文件的特征值
        current_hash = hash(uploaded_file.getvalue())
        
        # 只有当上传的文件和记忆里的不一样时，才执行重置
        if st.session_state.file_hash != current_hash:
            try:
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = current_hash # 更新锁
                st.session_state.chat_history = [] # 清空历史
                st.session_state.chat_history.append({"role": "assistant", "content": "新文件已加载！请下达指令。"})
                st.rerun() # 强制刷新以显示新状态
            except Exception as e:
                st.error(f"读取失败: {e}")
    else:
        # 如果用户点了“X”取消上传，也清空状态
        if st.session_state.current_df is not None:
            st.session_state.current_df = None
            st.session_state.file_hash = None
            st.session_state.chat_history = []
            st.rerun()

    # [C] 深度重置按钮 (只有点这个才会强制清空)
    if st.button("🔥 深度重置 / 重新开始", type="primary"):
        if uploaded_file:
            # 重新读取原始文件
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.chat_history.append({"role": "assistant", "content": "一切已归零，数据恢复到初始上传状态。"})
            st.rerun()

    # [D] 下载区域 (绝对安全的下载)
    if st.session_state.current_df is not None:
        st.divider()
        st.subheader("💾 阶段性存档")
        
        # 将当前内存里的 df 转为 Excel 字节流
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        
        # 这个按钮点击后，虽然页面会刷新，但因为 uploaded_file 没变，hash 没变，
        # 所以上面的 [B] 逻辑会被跳过，数据会完美保留。
        st.download_button(
            label="📥 下载当前进度的 Excel",
            data=output.getvalue(),
            file_name=f"处理结果_{datetime.datetime.now().strftime('%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ================= 3. 主界面展示 =================

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传 Excel 文件")
    st.stop()

# 实时显示当前数据的形状，让你确认数据还在
st.success(f"当前数据状态: {st.session_state.current_df.shape[0]} 行, {st.session_state.current_df.shape[1]} 列 (数据安全)")

with st.expander("📊 点击查看当前数据预览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

# 显示历史对话
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ================= 4. 核心：AI 处理引擎 (带解释) =================
if user_prompt := st.chat_input("输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在分析与计算...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 3
        success = False
        
        execution_globals = {
            "pd": pd, "np": np, "re": re, "math": math, "datetime": datetime
        }
        
        system_prompt = """
        你是一个 Python 数据处理专家。
        
        【任务】
        1. 分析用户需求。
        2. 编写 `process_step(df)` 函数返回修改后的 df。
        3. 编写 `explanation` 字符串，用中文解释你的逻辑（特别是时间聚合、空值处理等逻辑）。
        
        【规则】
        1. Pandas > 2.0，禁用 append，用 concat。
        2. 代码必须健壮，处理 NaT/NaN 错误。
        3. 优先使用用户指定的逻辑（如"前4点聚合为新的1点"）。
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"数据预览:\n{current_df.head(2).to_markdown()}\n用户需求: {user_prompt}"}
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
                
                if 'process_step' not in local_scope: raise ValueError("函数 process_step 未定义")
                if 'explanation' not in local_scope: local_scope['explanation'] = "（AI 未提供解释）"
                
                new_df = local_scope['process_step'](current_df.copy())
                
                # 更新状态
                st.session_state.current_df = new_df
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                # 构建回复
                final_response = f"""
                **🧐 逻辑核对:**
                > {local_scope['explanation']}
                
                ✅ 已完成修改。你可以：
                1. 继续输入指令进行下一步处理
                2. 点击左侧下载按钮保存当前进度
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
            status.update(label="❌ 任务失败", state="error")
            st.error("AI 尝试多次失败。请检查指令或数据。")
