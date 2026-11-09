"""
MXB-Bench "brain" cases: everyday requests, phrased the way people actually talk, that need the
planner (paraphrases, several steps, Indian English) and the plan MXB must produce for each.

A case passes when the actions MXB asked for contain the expected steps in order (extra steps such
as "wait" are fine) and it took no destructive action nobody asked for.

Each step lists acceptable alternatives: (action, keywords). Every keyword must appear in the
step's target (case-insensitive); "a|b" accepts either word. An empty step list means the right
answer is to just talk (no action at all).
"""

# (utterance, steps, category)
BRAIN_CASES = [
    # ---------------- apps & windows ----------------
    ("fire up spotify and then minimize it",
     [[("open_app", ["spotify"])], [("manage_window", ["minimi"]), ("shortcut", ["win+down"])]], "apps"),
    ("close every chrome window", [[("close_app", ["chrome"]), ("force_close_app", ["chrome"])]], "apps"),
    ("put this window on the left half of the screen",
     [[("manage_window", ["left"]), ("shortcut", ["win+left"])]], "apps"),
    ("bring my vs code window to the front",
     [[("switch_window", ["code"]), ("open_app", ["code"])]], "apps"),
    ("open the calculator for me", [[("open_app", ["calc"])]], "apps"),
    # ---------------- web ----------------
    ("look up the latest iphone price in india",
     [[("search_web", ["iphone"]), ("web_search", ["iphone"])]], "web"),
    ("take me to the leetcode website", [[("open_url", ["leetcode"]), ("web_open", ["leetcode"])]], "web"),
    ("open youtube and play arijit singh songs",
     [[("open_url", ["youtube"]), ("web_open", ["youtube"]), ("search_on_screen", ["arijit"]),
       ("web_search", ["arijit"]), ("search_web", ["arijit"])],
      ], "web"),
    ("do I need an umbrella in mysuru today",
     [[("weather", ["mysuru|mysore"]), ("search_web", ["mysuru|mysore"]), ("web_search", ["mysuru|mysore"])]], "web"),
    # ---------------- keyboard & typing ----------------
    ("write a quick note in notepad saying buy milk",
     [[("open_app", ["notepad"])], [("type_text", ["buy milk"])]], "keyboard"),
    ("select everything and copy it",
     [[("select_all", []), ("shortcut", ["ctrl+a"])], [("copy_text", []), ("shortcut", ["ctrl+c"])]], "keyboard"),
    ("open notepad, type hello world and save it",
     [[("open_app", ["notepad"])], [("type_text", ["hello world"])], [("save_file", []), ("shortcut", ["ctrl+s"])]],
     "keyboard"),
    ("type my email srinivas@example.com in the email box",
     [[("type_into", ["email", "srinivas@example.com"]), ("type_visual", ["email", "srinivas@example.com"])]], "screen"),
    # ---------------- files ----------------
    ("make a folder called projects 2026 on my desktop", [[("create_folder", ["projects 2026"])]], "files"),
    ("find my resume", [[("find_files", ["resume"])]], "files"),
    ("what's inside my downloads folder", [[("list_files", ["download"]), ("directory_tree", ["download"])]], "files"),
    ("rename notes.txt to ideas.txt", [[("rename_file", ["notes.txt", "ideas"])]], "files"),
    ("move report.pdf from downloads to documents", [[("move_file", ["report.pdf", "documents"])]], "files"),
    # ---------------- hardware ----------------
    ("it's too loud, bring the volume down to 30", [[("set_volume", ["30"])]], "hardware"),
    ("make the screen brighter", [[("set_brightness", ["up|100|9|8|7"])]], "hardware"),
    ("connect my airdopes", [[("bluetooth_connect", ["airdopes"])]], "hardware"),
    ("kill the internet connection", [[("wifi_power", ["off"]), ("wifi_disconnect", [])]], "hardware"),
    ("mute my mic", [[("mic_mute", ["on|mute|toggle"])]], "hardware"),
    ("pause the music", [[("media_control", ["pause|play"])]], "hardware"),
    ("switch off the bluetooth na", [[("bluetooth_power", ["off"])]], "hardware"),
    ("turn on bluetooth and connect my headphones",
     [[("bluetooth_power", ["on"])], [("bluetooth_connect", ["headphone"])]], "hardware"),
    # ---------------- system ----------------
    ("why is my laptop so slow", [[("check_system", []), ("top_processes", [])]], "system"),
    ("lock my computer", [[("lock_pc", [])]], "system"),
    ("what's using port 8000", [[("find_port", ["8000"])]], "system"),
    # ---------------- automation & memory ----------------
    ("remind me to drink water in 30 minutes", [[("set_reminder", ["30", "water"])]], "automation"),
    ("every weekday at 9 open outlook", [[("schedule_command", ["9", "outlook"])]], "automation"),
    ("remember that my sister's birthday is on march 3",
     [[("remember_fact", ["march 3|birthday"]), ("remember_preference", ["march 3|birthday"])]], "memory"),
    ("what do you know about my projects", [[("recall_memories", ["project"])]], "memory"),
    # ---------------- screen ----------------
    ("click the blue sign in button",
     [[("click_element", ["sign in"]), ("click_visual", ["sign in"]), ("click_text", ["sign in"])]], "screen"),
    ("what's written on my screen",
     [[("read_screen", []), ("read_active_window", []), ("describe_screen", [])]], "screen"),
    ("grab a picture of my screen", [[("capture_screen", []), ("web_screenshot", [])]], "screen"),
    # ---------------- companion features ----------------
    ("start taking notes for this standup", [[("meeting_start", [])]], "companion"),
    ("I want to study DSA for 45 minutes without distractions", [[("focus_start", ["45"])]], "companion"),
    ("is this message a scam: you won 50000 rupees, click here to claim",
     [[("scam_check", ["won|50000|claim"])]], "companion"),
    ("speak a little slower", [[("speech_rate", ["slow"])]], "companion"),
    # ---------------- just talk ----------------
    ("tell me a joke", [], "talk"),
    ("what's the capital of australia", [], "talk"),
    ("how are you doing today", [], "talk"),
]

# Actions that must never appear unless the case expects them.
DESTRUCTIVE = {"delete_file", "power_action", "kill_process", "force_close_app", "empty_recycle_bin",
               "wifi_disconnect", "close_app", "revoke_file_access", "forget_memory", "screen_time_forget"}
