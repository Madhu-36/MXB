import json
import os
from pathlib import Path

class MemoryBank:
    """
    MXB's Long-Term Memory Storage.
    Stores and retrieves facts about the user in a persistent JSON database.
    """
    def __init__(self):
        self.filepath = Path(__file__).parent.parent / 'memory_bank.json'
        self._ensure_db()

    def _ensure_db(self):
        try:
            if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                with open(self.filepath, 'w') as f:
                    json.dump([], f)
            else:
                with open(self.filepath, 'r') as f:
                    json.load(f)
        except json.JSONDecodeError:
            print("[Memory] Database corrupted or invalid JSON. Recreating...")
            with open(self.filepath, 'w') as f:
                json.dump([], f)

    def remember(self, fact: str):
        print(f"[Memory] Saving new fact: {fact}")
        with open(self.filepath, 'r') as f:
            memories = json.load(f)
            
        memories.append(fact)
        
        # Keep the last 50 memories to avoid blowing up the LLM context window
        if len(memories) > 50:
            memories = memories[-50:]
            
        with open(self.filepath, 'w') as f:
            json.dump(memories, f, indent=2)

    def get_memories(self, query=None, limit=10):
        self._ensure_db()
        with open(self.filepath, 'r') as f:
            memories = json.load(f)
            
        if not memories:
            return []
            
        if not query:
            return memories[-limit:]
            
        # Basic keyword scoring retrieval
        import re
        query_words = set(re.findall(r'\w+', query.lower()))
        scored_memories = []
        for mem in memories:
            mem_words = set(re.findall(r'\w+', mem.lower()))
            score = len(query_words.intersection(mem_words))
            scored_memories.append((score, mem))
            
        # Sort by score descending, return top 'limit'
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in scored_memories[:limit]]
