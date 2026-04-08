import os
import pandas as pd
import IPython


def is_colab():
    try:
        import google.colab
        return True
    except ImportError:
        return False


import IPython

def safe_download(filepath, lpath="/"):
    """兼容 Colab 单元格 / 脚本 / 本地环境的文件下载"""
    if not os.path.exists(filepath):
        print(f"⚠️ 文件不存在: {filepath}")
        return

    try:
        # 仅在交互式 Notebook 环境中触发浏览器下载
        if IPython.get_ipython() is not None:
            from google.colab import files
            files.download(filepath, lpath=f"{lpath}/filepath")
            return
    except Exception as e:
        print(f"ℹ️ 无法触发自动下载: {e}")

    # 非交互式环境的 fallback
    abs_path = os.path.abspath(filepath)
    print(f"✅ 文件已保存至: {abs_path}")
    print("💡 请在 Colab 左侧文件浏览器中右键下载，或挂载 Google Drive 同步。")



IN_COLAB = is_colab()


# 示例
data = {'姓名': ['A', 'B', 'C', 'D', 'E', 'F'],
        '分数': [80, 95, 70, 90, 85, 100]}
df = pd.DataFrame(data)

if IN_COLAB:
    from google.colab import files
    safe_download("ic_2021.csv.c", lpath="/")
    from google.colab import drive
    drive.mount('/content/drive')
    df.to_csv('/content/drive/ic_2021.csv', index=False)