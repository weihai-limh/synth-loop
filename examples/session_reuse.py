"""多轮对话示例 —— 使用 x-gateway-session-id 保持上下文"""

import requests

BASE_URL = "http://localhost:13155/v1"
SESSION_ID = "demo-session-001"

def chat(content: str):
    return requests.post(
        f"{BASE_URL}/chat/completions",
        json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": content}],
            "stream": False
        },
        headers={
            "Content-Type": "application/json",
            "x-gateway-session-id": SESSION_ID
        }
    ).json()

# 第一轮
r1 = chat("我叫小明，是一名程序员")
print("Round 1:", r1["choices"][0]["message"]["content"][:80])

# 第二轮（带上下文，应记得我叫小明）
r2 = chat("我叫什么名字？我的职业是什么？")
print("Round 2:", r2["choices"][0]["message"]["content"][:80])
