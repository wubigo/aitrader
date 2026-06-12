from openai import OpenAI
import os

client = OpenAI(
    api_key=os.getenv("GEMINI_API"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

response = client.chat.completions.create(
    # model="gemini-2.5-pro-exp-03-25",      # 常用模型推荐
    model="gemini-3-flash-preview",            # 速度快、免费额度高
    # model="gemini-1.5-pro",              # 老模型
    messages=[
        {"role": "system", "content": "你是一个有帮助的AI助手。"},
        {"role": "user", "content": "介绍一下你自己"}
    ],
    temperature=0.7,
    max_tokens=2048
)

print(response.choices[0].message.content)