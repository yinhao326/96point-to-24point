import streamlit as st
import pandas as pd
import io
from openpyxl.utils import get_column_letter

# 设置网页标题
st.set_page_config(page_title="电力数据格式转换工具", page_icon="⚡")

st.title("⚡ 电力数据转换工具 (15min -> 1h)")
st.markdown("上传Excel文件，自动完成：**15分转1小时均值** + **去色** + **格式美化**。")

# --- 核心处理函数 (修改为内存处理，不读写本地路径) ---
def process_excel(uploaded_file):
    # 读取上传的文件
    all_sheets = pd.read_excel(uploaded_file, sheet_name=None, index_col=0)
    
    # 创建一个内存缓冲区来存放结果 Excel
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in all_sheets.items():
            try:
                # 1. 数据清洗 (同之前的逻辑)
                df.index = df.index.astype(str)
                # 过滤掉不含冒号或包含中文'点'的行
                condition = df.index.str.contains(':') & ~df.index.str.contains('点')
                df_clean = df[condition].copy()
                df_clean.sort_index(inplace=True)

                if len(df_clean) != 96:
                    # 如果行数不对，原样写入
                    df.to_excel(writer, sheet_name=sheet_name)
                    continue

                # 2. 计算均值 (96 -> 24)
                group_ids = [i // 4 for i in range(len(df_clean))]
                df_hourly = df_clean.groupby(group_ids).mean()
                
                new_index = [f"{h:02d}:00" for h in range(1, 25)]
                df_hourly.index = new_index
                df_hourly.index.name = "时间"

                # 3. 取整
                df_hourly = df_hourly.fillna(0).round(0).astype(int)
                
                # 4. 写入 Sheet
                df_hourly.to_excel(writer, sheet_name=sheet_name)
                
                # 5. 美化格式
                worksheet = writer.sheets[sheet_name]
                worksheet.freeze_panes = 'B2' # 冻结
                
                # 自适应列宽
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = get_column_letter(column[0].column)
                    for cell in column:
                        try:
                            if cell.value:
                                cell_len = len(str(cell.value))
                                if cell_len > max_length: max_length = cell_len
                        except: pass
                    worksheet.column_dimensions[column_letter].width = (max_length + 2) * 1.1

            except Exception as e:
                st.error(f"Sheet [{sheet_name}] 处理出错: {e}")
                df.to_excel(writer, sheet_name=sheet_name) # 出错保底

    # 指针回到开始位置
    output.seek(0)
    return output

# --- 网页交互逻辑 ---
uploaded_file = st.file_uploader("请将Excel文件拖拽到此处", type=["xlsx", "xls"])

if uploaded_file is not None:
    st.info("正在处理数据，请稍候...")
    
    try:
        # 调用处理函数
        processed_data = process_excel(uploaded_file)
        
        st.success("✅ 处理完成！点击下方按钮下载。")
        
        # 生成新文件名
        original_name = uploaded_file.name.split('.')[0]
        new_name = f"{original_name}_1小时均值版.xlsx"
        
        # 下载按钮
        st.download_button(
            label="📥 下载处理后的Excel",
            data=processed_data,
            file_name=new_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    except Exception as e:
        st.error(f"处理失败: {e}")