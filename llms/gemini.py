from google import genai
from google.genai import types
import os

def verify_gemini_key(api_key):
    try:
        client = genai.Client(api_key=api_key)
        # 尝试列出模型，这不会消耗额度/Token
        models = client.models.list()
        print("✅ API Key 有效！")
        print("你可以访问的部分模型：")
        for i, m in enumerate(models):
            print(f"- {m.name}")
            if i >= 2: break # 只打印前几个
        return True
    except Exception as e:
        print(f"❌ API Key 无效或发生错误: {e}")
        return False

# 测试你的 Key
my_key = os.getenv("GEMINI_API_KEY")
verify_gemini_key(my_key)