import os
import datetime
from github import Github
from github import Auth
from github import GithubException


# --- 配置区 ---
ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")   # 必须有 repo 权限
REPO_NAME = "wubigo/feedback"
BRANCH = "main"


def backup_file(local_file_path: str):
    # 1. 检查本地文件是否存在
    if not os.path.exists(local_file_path):
        print(f"❌ 错误：找不到本地文件 {local_file_path}")
        return

    # 2. 读取本地文件内容 (以二进制模式读取)
    with open(local_file_path, "rb") as file:
        content = file.read()

    # 1. 使用新的 Auth.Token 方式进行身份验证
    auth = Auth.Token(ACCESS_TOKEN)

    # 2. 在初始化 Github 对象时传入 auth 参数
    g = Github(auth=auth)



    try:
        repo = g.get_repo(REPO_NAME)
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = f"{now}-{local_file_path}"
        try:
            # 3. 尝试获取仓库中该文件的 SHA (如果已存在)
            contents = repo.get_contents(dest_path, ref=BRANCH)

            # 4. 如果文件存在，对比内容（可选），直接更新
            repo.update_file(
                path=dest_path,
                message=f"Backup: {os.path.basename(local_file_path)}",
                content=content,
                sha=contents.sha,
                branch=BRANCH
            )
            print(f"✅ 成功更新备份: {dest_path}")

        except GithubException as e:
            if e.status == 404:
                # 5. 如果文件不存在，创建新备份
                repo.create_file(
                    path=dest_path,
                    message=f"Initial Backup: {os.path.basename(local_file_path)}",
                    content=content,
                    branch=BRANCH
                )
                print(f"🚀 成功创建新备份: {dest_path}")
            else:
                print(f"❌ GitHub 异常: {e}")

    except Exception as e:
        print(f"❌ 连接失败: {e}")


if __name__ == "__main__":
    backup_file(local_file_path = "LOGGER_README.md")