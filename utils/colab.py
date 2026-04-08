import os
import pandas as pd
import IPython


def is_colab():
    try:
        import google.colab
        return True
    except ImportError:
        return False


import os
import shutil
import IPython


def safe_download(filepath, save_dir="/content"):
    """
    兼容 Colab 的文件保存与下载
    :param filepath: 待下载的源文件路径
    :param save_dir: Colab 虚拟机内的目标保存目录（非本地电脑路径）
    """
    if not os.path.exists(filepath):
        print(f"⚠️ 源文件不存在: {filepath}")
        return

    os.makedirs(save_dir, exist_ok=True)
    dest_path = os.path.join(save_dir, os.path.basename(filepath))

    # 1. 复制到 Colab 指定目录
    shutil.copy2(filepath, dest_path)
    print(f"✅ 已保存至 Colab 虚拟机: {dest_path}")

    # 2. 尝试触发浏览器下载（仅限交互式 Notebook）
    try:
        if IPython.get_ipython() is not None:
            from google.colab import files
            files.download(filepath)  # ✅ 仅接受文件名，触发浏览器对话框
            print("📥 已触发浏览器下载，请在本地选择保存位置。")
            return
    except Exception as e:
        print(f"ℹ️ 无法触发浏览器下载: {e}")

    print("💡 提示：如需自动同步到本地，请挂载 Google Drive 或手动在左侧文件面板下载。")




def safe_download(filepath, lpath="/"):
    """兼容 Colab 单元格 / 脚本 / 本地环境的文件下载"""
    if not os.path.exists(filepath):
        print(f"⚠️ 文件不存在: {filepath}")
        return

    try:
        # 仅在交互式 Notebook 环境中触发浏览器下载
        if IPython.get_ipython() is not None:
            from google.colab import files
            lpath = f"{lpath}/{filepath}.bak"
            print(lpath)
            files.download(filepath, lpath=f"{lpath}/{filepath}.bak")
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
    # safe_download("ic_2021.csv", lpath="/")
    safe_download("ic_2021.csv", save_dir="/content/output")
    # from google.colab import drive
    # drive.mount('/content/drive')
    # df.to_csv('/content/drive/ic_2021.csv', index=False)