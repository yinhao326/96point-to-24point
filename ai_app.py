import streamlit as st
import pandas as pd
import io
from openai import OpenAI
import traceback

# ================= 配置区域 =================
# 这里以 DeepSeek 为例，便宜又强大。也可以换成 OpenAI
# 你需要去 deepseek 官网申请一个 API Key
BASE_URL = "https://api.deepseek.com"    # DeepSeek 的地址

if "DEEPSEEK_API_KEY" in st.secrets:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    st.error("未检测到 API Key，请在 Secrets 中配置。")
    st.stop()

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
# client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

st.set_page_config(page_title="AI 智能数据助手", layout="wide")

st.title("🤖 智能数据处理助手")
st.markdown("上传 Excel，直接告诉 AI 你想怎么改，它自动帮你写代码并执行！")

# 1. 上传文件
uploaded_file = st.file_uploader("📂 第一步：上传 Excel 文件", type=["xlsx", "xls"])

if uploaded_file:
    # 读取前几行给 AI 看，让它懂数据结构
    try:
        df = pd.read_excel(uploaded_file, index_col=None) # 先不设索引，让AI自己判断
        st.write("### 数据预览 (前 5 行):")
        st.dataframe(df.head())
    except Exception as e:
        st.error(f"读取失败: {e}")
        st.stop()

    # 2. 输入需求
    user_prompt = st.text_area("🗣️ 第二步：告诉 AI 你想做什么？", 
                               height=100,
                               placeholder="例如：\n1. 把第一列的时间从15分钟间隔变成1小时均值\n2. 去掉所有包含'汇总'的行\n3. 保留整数")

    # 3. 开始处理
    if st.button("🚀 开始 AI 处理") and user_prompt:
        with st.spinner("AI 正在思考并编写代码..."):
            try:
                # --- A. 构造提示词 (让 AI 写代码) ---
                # 我们把数据的列名、前几行数据、用户需求都喂给 AI
                data_info = f"""
                数据列名: {list(df.columns)}
                前3行数据: {df.head(3).to_markdown()}
                数据形状: {df.shape}
                """
                
                system_prompt = """
                你是一个 Python 数据处理专家。你的任务是编写一个函数 `process_data(df)`。
                1. 输入是一个 pandas DataFrame。
                2. 根据用户的需求对 df 进行处理。
                3. 返回处理后的 df。
                4. 只返回 Python 代码，不要 markdown 标记，不要解释。
                5. 代码必须包含 `import pandas as pd` 等必要的库。
                """

                user_message = f"""
                数据情况:
                {data_info}

                用户需求:
                {user_prompt}

                请写出完整的 Python 代码。
                """

                # --- B. 调用大模型 ---
                response = client.chat.completions.create(
                    model="deepseek-chat", # 或者 "gpt-4o"
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.1 # 温度低一点，保证代码严谨
                )
                
                generated_code = response.choices[0].message.content
                
                # 清洗代码 (去掉 ```python 等标记)
                generated_code = generated_code.replace("```python", "").replace("```", "").strip()

                # --- C. 展示生成的代码 (可选，方便验证) ---
                with st.expander("👀 查看 AI 生成的代码 (点击展开)"):
                    st.code(generated_code, language='python')

                # --- D. 危险操作：动态执行代码 ---
                # 创建一个局部命名空间来运行代码
                local_scope = {}
                exec(generated_code, globals(), local_scope)
                
                # 获取函数并执行
                if 'process_data' in local_scope:
                    process_func = local_scope['process_data']
                    new_df = process_func(df) # 真正执行处理
                    
                    st.success("✅ 处理成功！")
                    
                    # --- E. 展示结果与下载 ---
                    st.write("### 处理结果预览:")
                    st.dataframe(new_df.head())
                    
                    # 导出
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        new_df.to_excel(writer, index=True) # 假设index重要，如果不需要设为False
                        
                        # (可以在这里加上之前写的自适应列宽代码)
                        
                    st.download_button(
                        label="📥 下载处理后的文件",
                        data=output.getvalue(),
                        file_name="AI处理结果.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.error("AI 生成的代码里没有找到 `process_data` 函数，请重试。")

            except Exception as e:
                st.error(f"❌ 执行出错: {e}")
                st.write("错误详情:", traceback.format_exc())