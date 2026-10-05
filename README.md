# 🧠 MXB (Machine eXecutive Brain)
> The Ultimate AI-Powered Second Brain & Executive Assistant for Windows

![MXB Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows_10%20%7C%2011-lightgrey.svg)
![AI](https://img.shields.io/badge/AI-Llama_3.1-orange.svg)

**MXB** is an ultra-fast, entirely local, voice-controlled AI assistant running invisibly on your Windows machine. It acts as your autonomous executive assistant, constantly listening, learning, and automating your OS without ever sending your private data to the cloud.

---

## 🌟 Comprehensive Description & Vision

MXB was built with a singular vision: to create an AI assistant that actually *understands* your physical computing environment. Unlike traditional chatbots that live inside a web browser window, MXB is deeply integrated directly into your Windows Operating System.

### 🔒 100% Local & Private
Privacy is the core foundation of MXB. Every single component—from the Voice Activity Detection (VAD), to the Whisper Speech-to-Text transcription, to the Llama-3.1 LLM Brain—runs entirely on your local hardware. There are no API keys required, no cloud subscriptions, and absolutely zero telemetry. Your data, your microphone audio, and your personal clipboard contents never leave your physical computer.

### 🧠 True Context Awareness
MXB doesn't just listen to your voice; it reads your environment. Before MXB formulates a response, it silently injects the exact time of day, your geographic location, the live local weather, and the title of the exact application window you are currently looking at into its context matrix. When you say *"Summarize what I am looking at"*, it truly knows what you are looking at.

### ⚙️ Autonomous OS Control
MXB acts as a bridge between natural language and the Windows API. It can minimize, maximize, and close your active windows. It can scan your Start Menu using fuzzy-matching algorithms to launch applications even if you mispronounce their names. It polls your hardware to warn you about RAM limits and battery life. 

---

## 🚀 Ultimate Upgrades (V2.0 Features)

- **Premium Glassmorphism HUD:** An ultra-premium translucent GUI with smooth fade animations and custom drop-shadows that gracefully appears only when speaking.
- **Smart App Launcher:** Fuzzy-matching application discovery via the Windows Start Menu `.lnk` files.
- **AI Web Search:** Autonomous duckduckgo-search crawling. MXB fetches search results, parses the HTML, and summarizes the internet for you on the fly.
- **Context Injection:** Injects Real-time Date, Weather, IP-based Location, and Active Window titles directly into the LLM context buffer.
- **Semantic Memory Engine:** Advanced TF-IDF Keyword-overlap semantic search for long-term facts, combined with a rolling 5-turn short-term conversational history buffer.
- **Native Toast Notifications:** Seamless integration with the Windows 11 Action Center for background task alerts.
- **Asynchronous TTS:** Non-blocking SAPI5 speech synthesis via isolated QThreads.
- **System Diagnostics:** Live system health checks and hardware polling (CPU, RAM, Battery) via `psutil`.

---

## 🛠 Installation & Setup

Ensure you have Python 3.10+ and `ollama` installed on your system.

```bash
# 1. Clone the repository
git clone https://github.com/Madhu-36/MXB.git
cd MXB/mxb_app

# 2. Setup Virtual Environment
python -m venv .venv
.\.venv\Scripts\activate

# 3. Install Requirements
pip install -r requirements.txt

# 4. Start the Brain
run.bat
```

## 🧠 AI Models & Dynamic Compilation
MXB utilizes a custom Llama-3.1 based `Modelfile` to intelligently route intents (OS commands vs conversation). On first launch, `main.py` will automatically invoke the `LLMBuilder` module to compile and hash the `mxb-brain` model directly into your local Ollama instance. If you update the prompts in the `Modelfile`, MXB will automatically detect the changes and recompile the brain on your next boot.

---
*Developed with a commitment to privacy, speed, and continuous ultimate upgrades.*
