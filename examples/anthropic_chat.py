"""Anthropic 格式请求示例 —— synth-loop"""

import requests

BASE_URL = "http://localhost:13155"

response = requests.post(
    f"{BASE_URL}/v1/messages",
    json={
        "model": "deepseek-v4-flash",
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": "解释一下什么是分形决策"}
        ]
    },
    headers={
        "Content-Type": "application/json",
        "x-api-key": "your-api-key",
        "anthropic-version": "2023-06-01"
    }
)

print(response.json()["content"][0]["text"])
