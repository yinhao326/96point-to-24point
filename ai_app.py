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

st.set_page_config(page_title="AI 全能数据专家", layout="wide")

# ================= 状态管理 =================
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] 

st.title("🤖 AI 全能数据专家 (God Mode)")
st.caption("内置全能运行环境 + 自动纠错闭环。任意需求，使命必达。")

# ================= 侧边栏 =================
with st.sidebar:
    st.header("📂 文件中心")
    uploaded_file = st.file_uploader("上传 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        file_hash = hash(uploaded_file.getvalue())
        if "file_hash" not in st.session_state or st.session_state.file_hash != file_hash:
            try:
                # 读取时不做特殊处理，原汁原味交给 AI
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = file_hash
                st.session_state.chat_history = [] 
                st.session_state.chat_history.append({"role": "assistant", "content": "数据已就绪！无论是清洗、计算还是统计，请尽管吩咐。"})
                st.rerun()
            except Exception as e:
                st.error(f"读取失败: {e}")

    if st.button("🔥 深度重置"):
        if uploaded_file:
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.chat_history.append({"role": "assistant", "content": "记忆已清除，数据已恢复初始状态。"})
            st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=False)
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

# ================= 核心：全能执行引擎 =================
if user_prompt := st.chat_input("请输入指令..."):
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        status = st.status("🧠 AI 正在解析需求...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 4 # 增加重试次数
        success = False
        
        # --- 1. 构建全能上下文环境 ---
        # 这里把所有可能用到的库都预先塞进去，AI 就算忘了 import 也能用
        execution_globals = {
            "pd": pd,
            "np": np,
            "re": re,
            "math": math,
            "datetime": datetime,
            "io": io
        }
        
        # --- 2. 更加智能的 System Prompt ---
        system_prompt = """
        你是一个拥有 Python 执行权限的高级数据分析师。
        任务：编写 `process_step(df)` 函数，返回修改后的 df。
        
        【环境说明】
        1. 系统已预置 pandas(pd), numpy(np), re, math, datetime。你依然可以 import，但忘记也没关系。
        2. 数据中可能包含 '24:00' (需替换为 '00:00' 并+1天) 或 NaT/NaN。
        3. Pandas 版本 > 2.0，严禁使用 append，请用 pd.concat。
        
        【代码要求】
        1. 必须具有极强的鲁棒性。在进行数值计算前，先转换类型；在处理时间前，先处理异常值。
        2. 只返回纯 Python 代码，不带 markdown 标记。
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"数据预览:\n{current_df.head(2).to_markdown()}\n数据类型:\n{current_df.dtypes}\n\n需求: {user_prompt}"}
        ]

        for i in range(MAX_RETRIES):
            try:
                if i > 0: status.write(f"🔧 第 {i} 次自动修复中... (错误已捕获)")
                
                # 调用 AI
                response = client.chat.completions.create(
                    model="deepseek-chat", messages=messages, temperature=0.1
                )
                code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                # 执行代码 (注入了全能环境)
                local_scope = {}
                exec(code, execution_globals, local_scope)
                
                if 'process_step' not in local_scope: raise ValueError("函数 process_step 未定义")
                
                # 运行函数
                new_df = local_scope['process_step'](current_df.copy()) # 传入副本防止污染
                
                # 成功！
                st.session_state.current_df = new_df
                success = True
                status.update(label="✅ 执行成功", state="complete", expanded=False)
                
                msg = f"✅ 操作完成！(自动修正 {i} 次)" if i > 0 else "✅ 操作完成！"
                st.markdown(msg)
                st.session_state.chat_history.append({"role": "assistant", "content": msg})
                st.rerun()
                break

            except Exception as e:
                # 捕获所有 Python 运行时的报错
                error_info = f"{type(e).__name__}: {str(e)}"
                status.write(f"❌ 捕获错误: {error_info}")
                
                # 将错误喂回给 AI，让它下一次修复
                messages.append({"role": "assistant", "content": code})
                messages.append({"role": "user", "content": f"代码执行报错: {error_info}\n请针对此错误修改代码。确保处理了空值或类型不匹配问题。"})
        
        if not success:
            status.update(label="❌ 任务失败", state="error")
            st.error("AI 尝试了 4 次依然失败。建议：\n1. 检查数据是否极其混乱\n2. 尝试将复杂的指令拆分成两步说")
