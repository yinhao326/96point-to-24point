# ================= 0. 环境准备 =================
import os
import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import math
from datetime import datetime
# 注意：通义千问使用 openai 库进行兼容调用
from openai import OpenAI

# ================= 1. 初始化与配置 =================
st.set_page_config(page_title="AI 能源数据分析台 (Qwen V37)", layout="wide")

# 检查 API Key
# 请在 Streamlit Secrets 中将 GEMINI_API_KEY 改名为 DASHSCOPE_API_KEY
if "DASHSCOPE_API_KEY" in st.secrets:
    api_key = st.secrets["DASHSCOPE_API_KEY"]
else:
    st.error("❌ 未检测到 API Key。请在 .streamlit/secrets.toml 中配置 DASHSCOPE_API_KEY")
    st.stop()

# 初始化千问客户端 (兼容 OpenAI 协议)
client = OpenAI(
    api_key=api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.title("🧠 模型设置")
    
    # 更改为千问系列型号
    model_options = [
        "qwen-max", 
        "qwen-plus", 
        "qwen-turbo",
        "qwen-long"  # 适合超长文档
    ]
    selected_model = st.selectbox("选择模型引擎：", model_options, index=0)
    
    st.divider()
    st.title("📁 文件上传")
    uploaded_file = st.file_uploader("上传 Excel/CSV", type=['xlsx', 'xls', 'csv'])

# ================= 3. 数据处理逻辑 =================
if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        
        st.success(f"✅ {uploaded_file.name} 加载成功！(引擎: {selected_model})")
        
        with st.expander("📊 数据预览 (Top 5)"):
            st.dataframe(df.head())
            st.info(f"数据维度: {df.shape[0]} 行 × {df.shape[1]} 列")
            
    except Exception as e:
        st.error(f"文件读取失败: {e}")
        df = None
else:
    df = None

# ================= 4. 对话界面 =================
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("请输入指令..."):
    # 用户输入显示
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 调用千问模型
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        # 准备上下文 (如果上传了文件，把列名传给 AI)
        context_prompt = prompt
        if df is not None:
            cols_info = ", ".join(df.columns.tolist())
            context_prompt = f"当前用户上传了数据表，列名包含: [{cols_info}]。\n用户指令: {prompt}"

        try:
            # 这里的调用方式完全改变了 (OpenAI 风格)
            response = client.chat.completions.create(
                model=selected_model,
                messages=[
                    {"role": "system", "content": "你是一个专业的数据分析专家，擅长处理电力和能源数据。"},
                    {"role": "user", "content": context_prompt}
                ],
                stream=True, # 开启流式输出
            )
            
            # 流式渲染到界面
            for chunk in response:
                content = chunk.choices[0].delta.content
                if content:
                    full_response += content
                    message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"❌ 发生错误\n错误详情: {str(e)}")
