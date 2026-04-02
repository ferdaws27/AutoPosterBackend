import os
from typing import Any, Dict, List, Optional

from openai import OpenAI


class OpenRouterService:
    def __init__(self) -> None:
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        self.model = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")

    def chat(
        self,
        messages: List[Dict[str, Any]],
        enable_reasoning: bool = True,
    ) -> Dict[str, Any]:
        extra_body = {}
        if enable_reasoning:
            extra_body["reasoning"] = {"enabled": True}

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            extra_body=extra_body,
        )

        message = response.choices[0].message

        return {
            "content": getattr(message, "content", None),
            "reasoning_details": getattr(message, "reasoning_details", None),
            "role": getattr(message, "role", "assistant"),
            "model": response.model,
            "usage": response.usage.model_dump() if response.usage else None,
        }