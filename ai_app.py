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

st.set_page_config(page_title="AI 可解释数据专家", layout="wide")

# ================= 状态管理 =================
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] 

st.title("🤖 AI 可解释数据专家")
st.caption("我不光会算，还会用人话告诉你我是怎么算的，方便你核对逻辑。")

# ================= 侧边栏 =================
with st.sidebar:
    st.header("📂 文件中心")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        file_hash = hash(uploaded_file.getvalue())
        if "file_hash" not in st.session_state or st.session_state.file_hash != file_hash:
            try:
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = file_hash
                st.session_state.chat_history = [] 
                st.session_state.chat_history.append({"role": "assistant", "content": "文件已就绪！请告诉我如何处理。"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")

    if st.button("🔥 深度重置"):
        if uploaded_file:
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.chat_history.append({"role": "assistant", "content": "已重置。"})
            st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True) # 默认保留索引
        st.download_button("📥 下载结果", data=output.getvalue(), file_name="result.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ================= 主界面 =================
if st.session_state.current_df is None:
    st.info("👈 请上传 Excel 文件开始")
    st.stop()

with st.expander("📊 数据概览", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ================= 核心：带解释的执行引擎 =================
if user_prompt := st.chat_input("请输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在拆解逻辑...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 3
        success = False
        
        # --- 1. 全能环境 ---
        execution_globals = {
            "pd": pd, "np": np, "re": re, "math": math, "datetime": datetime
        }
        
        # --- 2. 核心 Prompt 修改：要求返回逻辑解释 ---
        system_prompt = """
        你是一个 Python 数据处理专家。
        
        【任务】
        1. 分析用户需求。
        2. 编写 `process_step(df)` 函数返回修改后的 df。
        3. **编写一段中文的 `explanation` 字符串**，用“非技术人员也能听懂的话”解释你的计算逻辑，特别是时间聚合的边界（例如："我是把 00:15-01:00 归并为 01:00"）。
        
        【输出格式】
        你的返回内容必须完全符合以下 Python 代码块格式（不要 markdown）：
        
        explanation = "这里写你的中文逻辑解释..."
        
        def process_step(df):
            # 这里写处理代码
            return df
        
        【严格约束】
        1. 必须优先遵循用户给出的具体示例（如"前4个点算作新的01:00"）。
        2. Pandas > 2.0，禁用 append，用 concat。
        3. 遇到时间计算，必须详细解释你是如何划分区间的。
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"数据预览:\n{current_df.head(2).to_markdown()}\n用户需求: {user_prompt}"}
        ]

        for i in range(MAX_RETRIES):
            try:
                if i > 0: status.write(f"🔧 第 {i} 次自动修复中...")
                
                response = client.chat.completions.create(
                    model="deepseek-chat", messages=messages, temperature=0.1
                )
                code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                # 执行代码
                local_scope = {}
                exec(code, execution_globals, local_scope)
                
                if 'process_step' not in local_scope: raise ValueError("函数 process_step 未定义")
                if 'explanation' not in local_scope: local_scope['explanation'] = "（AI 未提供解释，请检查结果）"
                
                # 运行处理
                new_df = local_scope['process_step'](current_df.copy())
                
                st.session_state.current_df = new_df
                success = True
                
                # --- 成功后的展示 ---
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                # 重点：显示 AI 的逻辑解释
                explanation_box = f"""
                **🧐 逻辑核对 (请务必确认):**
                > {local_scope['explanation']}
                
                ---
                ✅ 操作完成！
                """
                st.markdown(explanation_box)
                st.session_state.chat_history.append({"role": "assistant", "content": explanation_box})
                
                st.rerun()
                break

            except Exception as e:
                error_info = f"{type(e).__name__}: {str(e)}"
                status.write(f"❌ 捕获错误: {error_info}")
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"报错: {error_info}\n请修正代码。如果是因为没有定义 explanation 变量，请务必定义它。"})
        
        if not success:
            status.update(label="❌ 任务失败", state="error")
            st.error("AI 尝试多次失败。请尝试更详细地描述步骤。")
