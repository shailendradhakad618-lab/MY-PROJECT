import re
from .models import TaskPlan, Action

OPEN = r"\b(?:open|kholo|khol|launch|start)\b"
TYPE = r"\b(?:likho|likh|type|write|enter)\b"
APP = {
    "file explorer":"explorer", "note pad":"notepad", "notepad":"notepad",
    "calculator":"calculator", "calc":"calculator", "chrome":"chrome",
    "browser":"chrome", "explorer":"explorer",
}

def clean(s): return " ".join(str(s or "").lower().split())

def norm(s):
    s = clean(s)
    s = re.sub(r"\b(?:sev|seve|sve|saev|savee|sew|saye|sayv)\b", "save", s)
    s = s.replace(" fir ", " phir ")
    return s

def split_steps(s):
    return [x.strip(" ,.!?") for x in re.split(
        r"\s*(?:phir|then|uske baad|after that|finally|aakhir mein)\s*", s
    ) if x.strip(" ,.!?")]

def app_of(s):
    for a, v in sorted(APP.items(), key=lambda x: -len(x[0])):
        if a in s and re.search(OPEN, s, re.I):
            return v
    return None

def payload(s):
    """Extract text for both 'likho X' and 'usmein X likho' styles."""
    # Natural Hinglish: 'notepad kholo usmein hello jarvis likho'
    m = re.search(r"\busmein\s+(.+?)\s+" + TYPE + r"\b", s, re.I)
    if m:
        text = m.group(1).strip(" ,.!?")
        if text:
            return text
    # Variants: 'usme X likho', 'ismein X likho', 'isko X likho'
    m = re.search(r"\b(?:usme|ismein|isme|isko|usko)\s+(.+?)\s+" + TYPE + r"\b", s, re.I)
    if m:
        text = m.group(1).strip(" ,.!?")
        if text:
            return text
    # English/Hinglish: 'type/write/likho X'
    m = re.search(TYPE + r"\s+(.+?)(?=\s+(?:phir|then|aur|save|save as|usko|isko)\b|$)", s, re.I)
    if m:
        text = m.group(1).strip(" ,.!?")
        if text:
            return text
    return None

class Planner:
    def plan(self, goal, intent=None):
        s = norm(goal)
        has_sequence = bool(re.search(r"\b(?:phir|then|uske baad|after that|finally|aakhir mein)\b", s))
        parts = split_steps(s) if has_sequence else [s]
        p = TaskPlan(goal=goal, actions=[], source="local")
        for part in parts:
            a = app_of(part)
            if a:
                p.actions.append(Action("open_app", {"name": a}))
            t = payload(part)
            if t:
                p.actions.append(Action("type_text", {"text": t}))
            if re.search(r"\bsave\s+as\b", part):
                p.actions.append(Action("save_as", {}))
            elif re.search(r"\bsave\b", part):
                p.actions.append(Action("save", {}))
            m = re.search(r"\bpress\s+([a-z0-9+_-]+)", part, re.I)
            if m:
                p.actions.append(Action("press_key", {"key": m.group(1)}))
        return p
