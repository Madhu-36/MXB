import requests
from duckduckgo_search import DDGS
from utils.credentials import CredentialsManager
from utils.logger import log

class AIWebSearch:
    @staticmethod
    def search_and_summarize(query: str) -> str:
        log.info(f"WebSearch: Searching DuckDuckGo for '{query}'...")
        try:
            results = DDGS().text(query, max_results=3)
            if not results:
                return "No search results found."

            context = f"Web Search Results for '{query}':\n"
            for i, r in enumerate(results):
                context += f"{i+1}. {r.get('title')}: {r.get('body')}\n"

            prompt = (
                f"You are MXB, an AI executive brain. You just searched the web for '{query}'.\n\n"
                f"Results:\n{context}\n\n"
                f"Summarize the answer clearly and concisely for the user in 1 or 2 spoken sentences. "
                f"DO NOT use markdown formatting, just plain spoken text."
            )

            # 1. Cloud NVIDIA LLM (fastest)
            nv_key = CredentialsManager.get_nvidia_api_key()
            if nv_key:
                try:
                    url = "https://integrate.api.nvidia.com/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {nv_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "meta/llama-3.1-8b-instruct",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 120
                    }
                    resp = requests.post(url, headers=headers, json=payload, timeout=8)
                    if resp.status_code == 200:
                        ans = resp.json()["choices"][0]["message"]["content"].strip()
                        log.info(f"WebSearch: Summarized via NVIDIA Build: '{ans}'")
                        return ans
                except Exception as nv_err:
                    log.warning(f"WebSearch: NVIDIA summarization fallback: {nv_err}")

            # 2. Local Ollama Fallback
            payload = {
                "model": "llama3.1",
                "prompt": prompt,
                "stream": False
            }
            resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=30)
            if resp.status_code == 200:
                summary = resp.json().get("response", "").strip()
                log.info(f"WebSearch: Summarized via Ollama: '{summary}'")
                return summary

            return "Failed to analyze search results."
        except Exception as e:
            log.error(f"WebSearch: Search failed: {e}")
            return f"Web search failed: {e}"
