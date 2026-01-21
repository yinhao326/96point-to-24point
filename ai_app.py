import streamlit as st
import pandas as pd
import io
from openai import OpenAI
import traceback

# ================= 配置区域 =================
if "DEEPSEEK_API_KEY" in st.secrets:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    st.error("未检测到 API Key，请在 Streamlit Secrets 中配置。")
    st.stop()

BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

st.set_page_config(page_title="AI 智能数据分析 (自动修复版)", layout="wide")

# ================= 核心逻辑：状态管理 =================
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] 

st.title("🤖 AI 数据分析师 (自动修复版)")
st.caption("我拥有自我纠错能力。如果代码运行失败，我会根据报错信息自动重试，直到成功。")

# ================= 侧边栏：文件管理 =================
with st.sidebar:
    st.header("📂 文件操作")
    uploaded_file = st.file_uploader("上传/更换 Excel", type=["xlsx", "xls"])
    
    if uploaded_file:
        file_hash = hash(uploaded_file.getvalue())
        if "file_hash" not in st.session_state or st.session_state.file_hash != file_hash:
            try:
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = file_hash
                st.session_state.chat_history = [] 
                st.session_state.chat_history.append({"role": "assistant", "content": "文件已加载！请下达指令。"})
                st.rerun()
            except Exception as e:
                st.error(f"文件读取失败: {e}")

    if st.button("🔄 重置数据到初始状态"):
        if uploaded_file:
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.chat_history.append({"role": "assistant", "content": "数据已重置。"})
            st.rerun()

    if st.session_state.current_df is not None:
        st.divider()
        st.write("📥 **下载当前结果**")
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True)
        st.download_button(
            label="点击下载 Excel",
            data=output.getvalue(),
            file_name="AI处理结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ================= 主界面 =================

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传 Excel 文件")
    st.stop()

with st.expander("👀 数据预览 (最新)", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)

st.divider()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ================= 核心：带自动修复的执行循环 =================
if user_prompt := st.chat_input("输入指令..."):
    
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        # 创建一个占位符，用于动态更新状态 (比如: "第1次尝试失败，正在重试...")
        status_container = st.status("AI 正在思考...", expanded=True)
        
        current_df = st.session_state.current_df
        MAX_RETRIES = 3  # 最大重试次数
        success = False
        
        # 初始 Prompt
        base_system_prompt = """
        你是一个 Python 数据处理引擎。
        1. 编写函数 `process_step(df)` 修改数据，返回 new_df。
        2. 只返回 Python 代码，不要解释。
        3. 必须导入必要库 (import pandas as pd, numpy as np)。
        4. Pandas > 2.0，禁止用 append，请用 pd.concat。
        5. 注意处理空值和数据类型转换错误。
        """
        
        data_info = f"列名: {list(current_df.columns)}\n数据类型: {current_df.dtypes.to_dict()}"
        
        # 这里的 messages 列表会随着重试不断增加
        messages = [
            {"role": "system", "content": base_system_prompt},
            {"role": "user", "content": f"数据信息:{data_info}\n用户需求:{user_prompt}"}
        ]

        for attempt in range(MAX_RETRIES):
            try:
                if attempt > 0:
                    status_container.write(f"⚠️ 第 {attempt} 次尝试失败，正在进行自我修复...")
                
                # 1. 调用 API
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    temperature=0.1
                )
                generated_code = response.choices[0].message.content.replace("```python", "").replace("```", "").strip()
                
                # 2. 尝试执行代码
                local_scope = {}
                exec(generated_code, globals(), local_scope)
                
                if 'process_step' not in local_scope:
                    raise ValueError("未找到 process_step 函数")
                
                new_df = local_scope['process_step'](current_df)
                
                # 3. 如果执行到这里没有报错，说明成功了！
                st.session_state.current_df = new_df
                success = True
                status_container.update(label="✅ 处理成功！", state="complete", expanded=False)
                
                success_msg = f"✅ 修改成功！(尝试次数: {attempt+1})"
                st.markdown(success_msg)
                st.session_state.chat_history.append({"role": "assistant", "content": success_msg})
                st.rerun()
                break # 跳出循环

            except Exception as e:
                # 4. 捕获错误
                error_msg = f"{type(e).__name__}: {str(e)}"
                status_container.write(f"❌ 错误: {error_msg}")
                
                # 5. 关键步骤：把错误信息加回对话历史，让 AI 下次修正
                # 告诉 AI：“你刚才写的代码报错了，报错信息是这个，请修正代码。”
                messages.append({"role": "assistant", "content": generated_code})
                messages.append({"role": "user", "content": f"执行报错: {error_msg}\n请修正上述代码，注意处理该错误。只返回修正后的代码。"})
        
        if not success:
            status_container.update(label="❌ 处理失败", state="error", expanded=True)
            fail_msg = "经过 3 次尝试，AI 依然无法解决该问题。请检查数据或简化指令。"
            st.error(fail_msg)
            st.session_state.chat_history.append({"role": "assistant", "content": fail_msg})
