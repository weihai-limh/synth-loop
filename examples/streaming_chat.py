"""SSE 流式对话示例 —— synth-loop"""

import requests

BASE_URL = "http://localhost:13155/v1"

response = requests.post(
    f"{BASE_URL}/chat/completions",
    json={
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "user", "content": "用 Python 写一个快速排序函数"}
        ],
        "stream": True
    },
    headers={"Content-Type": "application/json"},
    stream=True
)

for line in response.iter_lines():
    if line:
        line_str = line.decode("utf-8")
        if line_str.startswith("data: "):
            data = line_str[6:]
            if data == "[DONE]":
                break
            print(data)
