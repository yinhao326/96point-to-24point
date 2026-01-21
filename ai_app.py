import streamlit as st
import pandas as pd
import io
from openai import OpenAI
import traceback

# ================= 配置区域 =================
# 自动读取 Secrets 中的 Key
if "DEEPSEEK_API_KEY" in st.secrets:
    API_KEY = st.secrets["DEEPSEEK_API_KEY"]
else:
    st.error("未检测到 API Key，请在 Streamlit Secrets 中配置。")
    st.stop()

BASE_URL = "https://api.deepseek.com"
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

st.set_page_config(page_title="AI 连续数据对话", layout="wide")

# ================= 核心逻辑：状态管理 =================

# 1. 初始化记忆：如果没有存过数据，先创建一个空的
if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = [] # 记录对话历史

st.title("🤖 AI 数据分析师 (对话模式)")
st.caption("上传文件后，像聊天一样不断下指令，我会一步步修改数据。")

# ================= 侧边栏：文件管理 =================
with st.sidebar:
    st.header("📂 文件操作")
    uploaded_file = st.file_uploader("上传/更换 Excel", type=["xlsx", "xls"])
    
    # 如果用户上传了新文件，重置所有状态
    if uploaded_file:
        # 只有当上传的文件和当前内存里的不一样时，才重置
        file_hash = hash(uploaded_file.getvalue())
        if "file_hash" not in st.session_state or st.session_state.file_hash != file_hash:
            try:
                df = pd.read_excel(uploaded_file)
                st.session_state.current_df = df
                st.session_state.file_hash = file_hash
                st.session_state.chat_history = [] # 清空聊天记录
                st.session_state.chat_history.append({"role": "assistant", "content": "文件已加载！请告诉我你想怎么处理？"})
                st.rerun() # 重新刷新页面
            except Exception as e:
                st.error(f"文件读取失败: {e}")

    # 提供“重置”按钮，万一改错了可以重来
    if st.button("🔄 重置数据到初始状态"):
        if uploaded_file:
            st.session_state.current_df = pd.read_excel(uploaded_file)
            st.session_state.chat_history = []
            st.session_state.chat_history.append({"role": "assistant", "content": "数据已重置，请重新下指令。"})
            st.rerun()

    # --- 实时下载按钮 (放在侧边栏最方便) ---
    if st.session_state.current_df is not None:
        st.divider()
        st.write("📥 **下载当前结果**")
        
        # 转换数据
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.current_df.to_excel(writer, index=True) # 默认保留索引
        
        st.download_button(
            label="点击下载 Excel",
            data=output.getvalue(),
            file_name="AI处理结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ================= 主界面：聊天窗口 =================

if st.session_state.current_df is None:
    st.info("👈 请先在左侧上传 Excel 文件")
    st.stop()

# 1. 显示当前数据预览 (折叠起来，省空间)
with st.expander("👀 点击查看当前数据预览 (最新状态)", expanded=True):
    st.dataframe(st.session_state.current_df.head(5), use_container_width=True)
    st.text(f"当前形状: {st.session_state.current_df.shape} | 列名: {list(st.session_state.current_df.columns)}")

st.divider()

# 2. 渲染历史聊天记录
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 3. 处理用户输入
# 🔴 这里就是刚才报错的地方，已经修改为 := 
if user_prompt := st.chat_input("输入修改指令 (例如：把所有空值填为0) ..."):
    
    # A. 显示用户的话
    st.session_state.chat_history.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # B. AI 思考处理
    with st.chat_message("assistant"):
        with st.spinner("AI 正在修改数据..."):
            try:
                # 获取最新的数据情况
                current_df = st.session_state.current_df
                data_info = f"""
                当前列名: {list(current_df.columns)}
                当前前3行数据: {current_df.head(3).to_markdown()}
                数据类型: {current_df.dtypes.to_dict()}
                """
                
                # 构造 Prompt
                system_prompt = """
                你是一个 Python 数据处理引擎。
                1. 你的任务是编写一个函数 `process_step(df)` 对数据进行修改。
                2. 代码将直接在现有 DataFrame 上运行，无需读取文件。
                3. 只返回 Python 代码，不要解释，不要 markdown 标记。
                4. 必须导入必要的库 (import pandas as pd)。
                5. 最终返回修改后的 df。
                6. ⚠️重要：当前 Pandas 版本 > 2.0，禁止使用 df.append() 或 series.append()，添加行必须使用 pd.concat()。
                """
                
                full_prompt = f"""
                数据状态:
                {data_info}
                
                用户需求:
                {user_prompt}
                
                请编写 Python 代码。
                """

                # 调用 API
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": full_prompt},
                    ],
                    temperature=0.1
                )
                
                generated_code = response.choices[0].message.content
                # 清洗代码
                generated_code = generated_code.replace("```python", "").replace("```", "").strip()
                
                # 动态执行
                local_scope = {}
                exec(generated_code, globals(), local_scope)
                
                if 'process_step' in local_scope:
                    # 运行 AI 的代码，更新 session_state 里的 df
                    new_df = local_scope['process_step'](current_df)
                    st.session_state.current_df = new_df
                    
                    success_msg = f"✅ 已完成修改！数据形状变为 {new_df.shape}。"
                    st.markdown(success_msg)
                    
                    # 存入历史
                    st.session_state.chat_history.append({"role": "assistant", "content": success_msg})
                    
                    # 强制刷新页面以更新顶部的数据预览
                    st.rerun()
                    
                else:
                    err_msg = "❌ AI 生成的代码格式有误，找不到 process_step 函数。"
                    st.error(err_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": err_msg})

            except Exception as e:
                err_msg = f"❌ 执行出错: {e}"
                st.error(err_msg)
                st.code(traceback.format_exc())
                st.session_state.chat_history.append({"role": "assistant", "content": err_msg})





