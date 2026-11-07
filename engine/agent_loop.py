"""
MXB Agent Loop — observe -> think -> act, repeated until the goal is done.

Used for tasks that can't be planned blind, e.g.
  "open the latest email from Ravi and reply thanks"
  "find the cheapest flight on this page and click it"

Each iteration MXB looks at the foreground window (title, clickable elements
with coordinates from UI Automation, OCR text, and optionally a screenshot for a
vision model), asks the LLM for the next 1-3 steps, runs them through the
interruptible ActionPlanner, and feeds the results back. Saying "stop" aborts
between any two steps.
"""
import io
import re
from engine.actions_catalog import prompt_tool_list
from utils.logger import log

AGENT_SYSTEM = """You are MXB operating the user's Windows PC step by step to achieve a goal.
Each turn you get the goal, what you already did, and the current screen.
Respond ONLY with JSON:
{"thought": "<one short sentence>", "done": false, "reply": "", "plan": [{"action": "...", "target": "..."}]}
- Give at most 3 steps per turn, then look again.
- Click elements using their listed coordinates with left_click "x,y", or click_element with the exact name.
- To type into a field, click it first (or use type_into), then type_text.
- When the goal is achieved (or impossible), set "done": true and put a short spoken summary in "reply".
- Never use agent_task.
Available actions:
"""

MOUSE_ACTIONS = {"left_click", "right_click", "double_click", "move_mouse"}


def rescale_step(step: dict, scale: float) -> dict:
    """Maps image-space coordinates from a downscaled screenshot back to screen pixels."""
    if scale == 1.0:
        return step
    action = str(step.get("action", "")).lower()
    target = str(step.get("target", ""))
    if action in MOUSE_ACTIONS:
        m = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*", target)
        if m:
            x, y = int(int(m.group(1)) * scale), int(int(m.group(2)) * scale)
            return {**step, "target": f"{x},{y}"}
    if action in {"drag", "drag_and_drop"}:
        nums = [int(n) for n in re.findall(r"-?\d+", target)]
        if len(nums) >= 4:
            n = [int(v * scale) for v in nums[:4]]
            return {**step, "target": f"{n[0]},{n[1]} -> {n[2]},{n[3]}"}
    return step


class AgentLoop:
    def __init__(self, executor, llm, config: dict | None = None):
        cfg = (config or {}).get("agent", {}) if isinstance(config, dict) else {}
        self.executor = executor
        self.llm = llm
        self.max_steps = int(cfg.get("max_steps", 8))
        self.use_vision = bool(cfg.get("use_vision", False))
        self.max_image_width = int(cfg.get("max_image_width", 1280))

    # ------------------------------------------------------------------ observation
    def observe(self) -> dict:
        obs = {"window": "", "elements": [], "text": "", "image": None, "scale": 1.0}
        uia = getattr(self.executor, "uia", None)
        try:
            if uia is not None:
                obs["window"] = uia.foreground_title()
                obs["elements"] = uia.summarize(limit=45)
        except Exception as e:
            log.warning(f"Agent: UIA observation failed: {e}")
        try:
            obs["text"] = (self.executor.screen.read_active_window_text() or "")[:1500]
        except Exception as e:
            log.warning(f"Agent: OCR observation failed: {e}")
        if self.use_vision:
            try:
                img = self.executor.screen.capture_screen_image()
                if img is not None:
                    w, h = img.size
                    if w > self.max_image_width:
                        ratio = self.max_image_width / float(w)
                        img = img.resize((self.max_image_width, int(h * ratio)))
                        obs["scale"] = 1.0 / ratio
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    obs["image"] = buf.getvalue()
            except Exception as e:
                log.warning(f"Agent: screenshot failed: {e}")
        return obs

    @staticmethod
    def build_prompt(goal: str, history: list[dict], obs: dict) -> str:
        lines = [f"GOAL: {goal}", ""]
        if history:
            lines.append("DONE SO FAR:")
            for i, h in enumerate(history[-8:], 1):
                lines.append(f"{i}. {h['action']} {h['target']!r} -> {h['result'][:160]}")
            lines.append("")
        lines.append(f"ACTIVE WINDOW: {obs.get('window') or 'unknown'}")
        if obs.get("elements"):
            lines.append("CLICKABLE ELEMENTS (type | name | x,y):")
            for el in obs["elements"]:
                lines.append(f"- {el['type']} | {el['name']} | {el['x']},{el['y']}")
        if obs.get("text"):
            lines.append("VISIBLE TEXT: " + obs["text"].replace("\n", " "))
        if obs.get("image") is not None:
            lines.append("A screenshot is attached. Coordinates you give must be in the screenshot's pixel space.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ run
    def run(self, goal: str, feedback=None) -> str:
        planner = self.executor.planner
        planner.reset()
        history: list[dict] = []
        system = AGENT_SYSTEM + prompt_tool_list(exclude=("agent_task",))
        for turn in range(1, self.max_steps + 1):
            if planner.is_aborted:
                return "Agent task stopped."
            if feedback:
                feedback(f"Agent step {turn}/{self.max_steps}: looking at the screen...")
            obs = self.observe()
            data = self.llm.chat_json(system, self.build_prompt(goal, history, obs), image_png=obs.get("image"))
            if planner.is_aborted:
                return "Agent task stopped."
            if not data:
                return "I couldn't reach my reasoning engine to continue that task."
            if data.get("done"):
                return data.get("reply") or "Task complete."
            steps = [s for s in (data.get("plan") or []) if isinstance(s, dict)]
            steps = [rescale_step(s, obs.get("scale", 1.0)) for s in steps if s.get("action") != "agent_task"][:3]
            if not steps:
                return data.get("reply") or "I'm not sure what to do next on this screen."
            if feedback and data.get("thought"):
                feedback(f"Agent: {data['thought']}")
            results = planner.execute_plan(steps, feedback_callback=feedback, reset=False)
            for step, res in zip(steps, results):
                history.append({"action": step.get("action", ""), "target": str(step.get("target", "")), "result": str(res)})
            if planner.is_aborted:
                return "Agent task stopped."
        summary = "; ".join(f"{h['action']} -> {h['result'][:60]}" for h in history[-3:])
        return f"I stopped after {self.max_steps} steps without confirming the goal. Last steps: {summary}"
