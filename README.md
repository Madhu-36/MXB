# 🧠 MXB (Machine eXecutive Brain)
> The Ultimate AI-Powered Second Brain for Windows

MXB is an ultra-fast, entirely local, voice-controlled AI assistant running invisibly on your Windows machine. It acts as your executive assistant, constantly listening, learning, and automating your OS.

## 🚀 Ultimate Upgrades (V2.0)
- **Glassmorphism HUD:** Ultra-premium translucent GUI with smooth fade animations.
- **Smart App Launcher:** Fuzzy-matching application discovery via the Windows Start Menu.
- **AI Web Search:** Autonomous DuckDuckGo crawling and LLM summarization.
- **Context Awareness:** Injects Real-time Date, Weather, Location, and Active Window titles directly into the LLM context.
- **Memory Engine:** Advanced Keyword-overlap semantic search for long-term facts.
- **Native Toast Notifications:** Seamless integration with Windows 11 Action Center.
- **Asynchronous TTS:** Non-blocking SAPI5 speech synthesis.

## 🛠 Installation
Ensure you have Python 3.10+ and `ollama` installed on your system.

```bash
# 1. Clone the repository
git clone https://github.com/your-username/mxb.git
cd mxb

# 2. Setup Virtual Environment
python -m venv .venv
.\.venv\Scripts\activate

# 3. Install Requirements
pip install -r requirements.txt

# 4. Start the Brain
run.bat
```

## 🧠 AI Models
MXB utilizes a custom Llama-3.1 based `Modelfile` to route intents (OS commands vs conversation).
On first launch, `main.py` will automatically invoke the `LLMBuilder` to compile the `mxb-brain` model into your local Ollama instance.

---
*Built today with 20 ultimate commits.*
