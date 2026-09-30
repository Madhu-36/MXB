from duckduckgo_search import DDGS
import requests

class AIWebSearch:
    @staticmethod
    def search_and_summarize(query: str) -> str:
        try:
            results = DDGS().text(query, max_results=3)
            if not results:
                return "No search results found."
                
            context = f"Web Search Results for '{query}':\n"
            for i, r in enumerate(results):
                context += f"{i+1}. {r.get('title')}: {r.get('body')}\n"
                
            # Have Llama summarize it directly
            payload = {
                "model": "llama3.1",
                "prompt": f"You are MXB, an AI assistant. You just searched the web for '{query}'.\n\nHere are the top results:\n{context}\n\nSummarize the answer clearly and concisely for the user in 1-2 short sentences so it can be spoken out loud. DO NOT use markdown formatting, just plain text.",
                "stream": False
            }
            
            resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=30)
            if resp.status_code == 200:
                summary = resp.json().get("response", "").strip()
                return summary
            return "Failed to analyze search results."
        except Exception as e:
            return f"Web search failed: {e}"
