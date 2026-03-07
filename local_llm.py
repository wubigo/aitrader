from llama_cpp import Llama

llm = Llama(
    model_path=r"C:\Users\bigo\.cache\modelscope\hub\models\unsloth\Qwen3___5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf",  # 模型路径
    n_ctx=4096,        # 上下文长度，按显存/内存调整
    n_gpu_layers=35,   # 使用 GPU 加速的层数；纯 CPU 可设为 0
)

prompt = "你是通义千问(Qwen3)模型，请用一句话介绍一下自己。"

res = llm(
    prompt,
    max_tokens=256,
    temperature=0.7,
    top_p=0.9,
)

print(res["choices"][0]["text"])
