"""基础对话示例 —— synth-loop OpenAI 兼容接口"""

import requests

BASE_URL = "http://localhost:13155/v1"

response = requests.post(
    f"{BASE_URL}/chat/completions",
    json={
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "user", "content": "你好，请帮我计算圆的面积，半径为5"}
        ],
        "stream": False
    },
    headers={"Content-Type": "application/json"}
)

print(response.json()["choices"][0]["message"]["content"])
