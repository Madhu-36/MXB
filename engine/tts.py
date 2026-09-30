import pyttsx3

class VoiceSynthesizer:
    def __init__(self):
        pass

    def speak(self, text: str):
        """
        Synchronously speaks the text using native Windows SAPI5.
        Instantiating locally ensures thread safety across different router calls.
        """
        print(f"[MXB Voice] {text}")
        if not text or text.strip() == "":
            return
            
        try:
            # When running TTS in a background Qt/Python thread on Windows, 
            # we MUST initialize COM before calling pyttsx3.init()
            import pythoncom
            pythoncom.CoInitialize()
            
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            
            # Prefer a natural female voice if available on Windows
            for voice in voices:
                if "Zira" in voice.name or "Hazel" in voice.name or "Female" in voice.name:
                    engine.setProperty('voice', voice.id)
                    break
                    
            engine.setProperty('rate', 175) # A comfortable, snappy reading pace
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTS Error] {e}")
