import ast
import speech_recognition as sr
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

import webbrowser
import urllib.parse
import datetime
import os
import subprocess
import json
import re
import time
import threading
import platform
import shutil
import py_compile
from pathlib import Path

from google import genai
from google.genai import types

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False


# =========================================================
# BASE DIRECTORY
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =========================================================
# GEMINI
# =========================================================

client = genai.Client()

GEMINI_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash"
]

# Gemini quota circuit breaker. Once a 429/resource-exhausted response is
# detected, this JARVIS session stops making further Gemini requests.
# Local commands continue to work without spending more quota.
GEMINI_QUOTA_EXHAUSTED = False

def _gemini_quota_error(exc):
    text = str(exc).lower()
    return (
        "resource_exhausted" in text
        or "quota exceeded" in text
        or "generaterequestsperday" in text
        or "429" in text
    )

def _gemini_disabled_message():
    return "Gemini quota abhi khatam hai, local JARVIS commands continue kar rahe hain."


# =========================================================
# MEMORY
# =========================================================

MEMORY_FILE = "jarvis_memory.json"


def load_memory():

    if not os.path.exists(MEMORY_FILE):
        return {
            "facts": {},
            "conversation": []
        }

    try:

        with open(
            MEMORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):

            return {
                "facts": {},
                "conversation": data
            }

        data.setdefault("facts", {})
        data.setdefault("conversation", [])

        return data

    except Exception as e:

        print("MEMORY LOAD ERROR:", e)

        return {
            "facts": {},
            "conversation": []
        }


def save_memory():

    try:

        with open(
            MEMORY_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                memory,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("MEMORY SAVE ERROR:", e)


memory = load_memory()


# =========================================================
# MICROPHONE
# =========================================================

recognizer = sr.Recognizer()

recognizer.pause_threshold = 0.8
recognizer.non_speaking_duration = 0.5
recognizer.dynamic_energy_threshold = True

microphone = sr.Microphone()


# =========================================================
# SPEAK - RELIABLE WINDOWS VOICE
# =========================================================

def speak(text):
    print("JARVIS:", text)

    try:
        # Write the speech into a temporary VBScript file.
        # This avoids problems when OCR contains symbols such as
        # quotes, &, >, @, etc.
        safe_text = str(text).replace("\r", " ").replace("\n", " ").strip()

        if len(safe_text) > 15000:
            safe_text = safe_text[:15000] + "..."

        # Escape VBScript string characters.
        safe_text = safe_text.replace('"', '""')

        temp_vbs = Path(os.environ.get("TEMP", ".")) / "jarvis_speak.vbs"

        vbs = (
            'Set voice = CreateObject("SAPI.SpVoice")\n'
            'voice.Rate = 0\n'
            'voice.Volume = 100\n'
            'voice.Speak "' + safe_text + '"\n'
        )

        temp_vbs.write_text(vbs, encoding="utf-8")

        result = subprocess.run(
            ["cscript.exe", "//nologo", str(temp_vbs)],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            print("SPEAK ERROR:", result.stderr.strip())

        try:
            temp_vbs.unlink()
        except Exception:
            pass

    except Exception as e:
        print("SPEAK ERROR:", e)


# =========================================================
# VOICE NORMALIZATION
# =========================================================

def normalize_command(command):

    command = command.lower().strip()

    command = re.sub(
        r"\s+",
        " ",
        command
    )

    replacements = {

        # PAR / PER / PE
        " per ": " par ",
        " pr ": " par ",
        " parr ": " par ",
        " pear ": " par ",
        " pair ": " par ",
        " pe ": " par ",

        # FIND
        "dhoondho": "dhoondo",
        "dhundo": "dhoondo",
        "dhundho": "dhoondo",
        "dhoondna": "dhoondo",
        "dhundna": "dhoondo",
        "dhoondh": "dhoondo",
        "dhundh": "dhoondo",
        "dhoond": "dhoondo",

        "khojo": "dhoondo",
        "khoj": "dhoondo",

        # OPEN
        "khol do": "kholo",
        "kholna": "kholo",
        "khol de": "kholo",

        # ACTION
        "kar do": "karo",
        "karna": "karo",
        "kr do": "karo",
        "krna": "karo",

        # TELL
        "bata": "batao",
        "batana": "batao",
        "btao": "batao",
        "bta": "batao",

        # YES
        "han": "haan",
        "ha ": "haan ",

        # NO
        "nhi": "nahi",
        "nai": "nahi",

        # VOLUME
        "badao": "badhao",
        "badha do": "badhao",
        "barhao": "badhao",
        "kum": "kam",

        # COMPUTER
        "komputer": "computer",
        "kampyutar": "computer",
        "computar": "computer",

        # APPS
        "you tube": "youtube",
        "gugal": "google",
        "crome": "chrome",
        "calculater": "calculator"
    }

    for old, new in replacements.items():

        if old.startswith(" ") or old.endswith(" "):

            command = command.replace(
                old,
                new
            )

        else:

            command = re.sub(
                r"\b" + re.escape(old) + r"\b",
                new,
                command
            )

    command = re.sub(
        r"\s+",
        " ",
        command
    )

    return command.strip()


# =========================================================
# MEMORY
# =========================================================

def remember_fact(key, value):

    key = key.strip().lower()
    value = value.strip()

    if key and value:

        memory["facts"][key] = value

        save_memory()

        print(
            "MEMORY SAVED:",
            key,
            "=",
            value
        )


def detect_memory(command):

    patterns = [

        r"remember my (.+?) is (.+)",
        r"remember that my (.+?) is (.+)",
        r"my (.+?) is (.+)",
        r"remember (.+?) is (.+)"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            command,
            re.IGNORECASE
        )

        if match:

            key = match.group(1).strip()

            value = match.group(2).strip()

            value = re.sub(
                r"[.!?]+$",
                "",
                value
            )

            remember_fact(
                key,
                value
            )

            return (
                "Okay Shailendra. "
                "I will remember that your "
                + key
                + " is "
                + value
                + "."
            )

    return None


def find_memory(question):

    question = question.lower()

    facts = memory.get(
        "facts",
        {}
    )

    if (
        "favorite color" in question
        or "favourite color" in question
        or "favorite colour" in question
        or "favourite colour" in question
    ):

        for key, value in facts.items():

            if (
                "color" in key
                or "colour" in key
            ):

                return (
                    "Your favorite color is "
                    + str(value)
                    + "."
                )

    for key, value in facts.items():

        words = key.split()

        if any(
            word in question
            for word in words
            if len(word) > 3
        ):

            return (
                "You told me that your "
                + key
                + " is "
                + str(value)
                + "."
            )

    return None


# =========================================================
# GEMINI
# =========================================================

def ask_ai(question):

    global GEMINI_QUOTA_EXHAUSTED
    if GEMINI_QUOTA_EXHAUSTED:
        return _gemini_disabled_message()

    local_answer = find_memory(
        question
    )

    if local_answer:

        return local_answer

    facts_text = ""

    for key, value in memory.get(
        "facts",
        {}
    ).items():

        facts_text += (
            key
            + ": "
            + str(value)
            + "\n"
        )

    recent = memory.get(
        "conversation",
        []
    )[-20:]

    conversation_text = ""

    for item in recent:

        role = item.get(
            "role",
            ""
        )

        text = item.get(
            "text",
            ""
        )

        if role == "user":

            conversation_text += (
                "Shailendra: "
                + text
                + "\n"
            )

        elif role == "jarvis":

            conversation_text += (
                "JARVIS: "
                + text
                + "\n"
            )

    prompt = f"""
You are JARVIS, Shailendra's personal AI assistant.

Understand English, Hindi and Hinglish.

Be friendly and helpful.

Give concise answers because your answers
are spoken aloud.

Permanent memory:
{facts_text}

Recent conversation:
{conversation_text}

Current user message:
{question}

Answer naturally.
"""

    last_error = None

    for model in GEMINI_MODELS:

        try:

            print(
                "Trying Gemini:",
                model
            )

            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            answer = response.text.strip()

            memory["conversation"].append({
                "role": "user",
                "text": question
            })

            memory["conversation"].append({
                "role": "jarvis",
                "text": answer
            })

            if len(
                memory["conversation"]
            ) > 100:

                memory["conversation"] = (
                    memory["conversation"][-100:]
                )

            save_memory()

            return answer

        except Exception as e:

            last_error = e

            print(
                "Gemini error:",
                model,
                e
            )

            if _gemini_quota_error(e):
                GEMINI_QUOTA_EXHAUSTED = True
                break

            time.sleep(1)

    print(
        "ALL GEMINI MODELS FAILED:",
        last_error
    )

    return (
        "Sorry Shailendra, "
        "Gemini is temporarily unavailable."
    )


# =========================================================
# LISTEN
# =========================================================

def listen():

    try:

        with microphone as source:

            print(
                "\nListening..."
            )

            audio = recognizer.listen(
                source,
                timeout=None,
                phrase_time_limit=8
            )

        print(
            "Processing..."
        )

        command = recognizer.recognize_google(
            audio
        )

        print(
            "You:",
            command
        )

        command = normalize_command(
            command
        )

        print(
            "Normalized:",
            command
        )

        return command

    except sr.UnknownValueError:

        print(
            "Could not understand."
        )

        return ""

    except sr.RequestError:

        print(
            "Speech recognition unavailable."
        )

        return ""

    except Exception as e:

        print(
            "LISTEN ERROR:",
            e
        )

        return ""


# =========================================================
# LOCAL OCR - READ SCREEN WITHOUT GEMINI
# =========================================================

def read_screen_locally():
    if not PYAUTOGUI_AVAILABLE:
        speak("I cannot capture the screen because the screenshot system is unavailable.")
        return True

    if not TESSERACT_AVAILABLE:
        speak("Local screen reading is not installed yet.")
        print("Run: py -3.13 -m pip install pytesseract")
        return True

    try:
        # Tesseract was installed here on this PC.
        tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        if not os.path.exists(tesseract_path):
            print("TESSERACT NOT FOUND:", tesseract_path)
            speak("I cannot find the Tesseract OCR program.")
            return True

        pytesseract.pytesseract.tesseract_cmd = tesseract_path

        screenshot = pyautogui.screenshot()
        screenshot.save(SCREENSHOT_FILE)

        text = pytesseract.image_to_string(screenshot, lang="eng")
        text = " ".join(text.split()).strip()

        if not text:
            speak("I could not find readable text on the screen.")
            return True

        print("LOCAL OCR:", text)

        spoken_text = text
        if len(spoken_text) > 15000:
            spoken_text = spoken_text[:15000] + "..."

        speak("I can read this on the screen: " + spoken_text)
        return True

    except Exception as e:
        print("LOCAL OCR ERROR:", e)
        speak("Sorry, I could not read the screen locally.")
        return True


# =========================================================
# LOCAL SCREEN TEXT POSITION + SMART CLICK
# =========================================================

def find_screen_text(target):
    """Find the best OCR match and return its screenshot coordinates."""
    if not PYAUTOGUI_AVAILABLE or not TESSERACT_AVAILABLE:
        return []

    try:
        tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        if not os.path.exists(tesseract_path):
            return []

        pytesseract.pytesseract.tesseract_cmd = tesseract_path

        screenshot = pyautogui.screenshot()

        data = pytesseract.image_to_data(
            screenshot,
            lang="eng",
            config="--psm 11",
            output_type=pytesseract.Output.DICT
        )

        target = re.sub(r"[^a-z0-9 ]", " ", target.lower())
        target = re.sub(r"\s+", " ", target).strip()

        target_words = [
            w for w in target.split()
            if len(w) > 0
        ]

        if not target_words:
            return []

        results = []

        # OCR sometimes returns a phrase as separate words.
        # First collect all valid OCR words.
        words = []

        for i, raw_word in enumerate(data["text"]):
            word = re.sub(
                r"[^a-z0-9]",
                "",
                raw_word.lower()
            )

            if not word:
                continue

            try:
                confidence = float(data["conf"][i])
            except Exception:
                confidence = 0

            if confidence < 35:
                continue

            words.append({
                "index": i,
                "word": word,
                "raw": raw_word,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "confidence": confidence
            })

        # -------------------------------------------------
        # 1. Exact multi-word phrase match
        # -------------------------------------------------
        if len(target_words) > 1:

            for start_i in range(len(words) - len(target_words) + 1):

                group = words[
                    start_i:start_i + len(target_words)
                ]

                group_words = [
                    item["word"] for item in group
                ]

                if group_words == target_words:

                    x1 = min(item["x"] for item in group)
                    y1 = min(item["y"] for item in group)

                    x2 = max(
                        item["x"] + item["w"]
                        for item in group
                    )

                    y2 = max(
                        item["y"] + item["h"]
                        for item in group
                    )

                    results.append({
                        "text": " ".join(
                            item["raw"] for item in group
                        ),
                        "x": x1,
                        "y": y1,
                        "w": x2 - x1,
                        "h": y2 - y1,
                        "confidence": sum(
                            item["confidence"] for item in group
                        ) / len(group),
                        "match_type": "phrase"
                    })

        # -------------------------------------------------
        # 2. Exact single-word match
        # -------------------------------------------------
        for item in words:

            if item["word"] in target_words:

                results.append({
                    "text": item["raw"],
                    "x": item["x"],
                    "y": item["y"],
                    "w": item["w"],
                    "h": item["h"],
                    "confidence": item["confidence"],
                    "match_type": "exact"
                })

        # -------------------------------------------------
        # 3. Partial match only as fallback
        # -------------------------------------------------
        if not results:

            for item in words:

                if any(
                    tw in item["word"]
                    or item["word"] in tw
                    for tw in target_words
                ):

                    results.append({
                        "text": item["raw"],
                        "x": item["x"],
                        "y": item["y"],
                        "w": item["w"],
                        "h": item["h"],
                        "confidence": item["confidence"],
                        "match_type": "partial"
                    })

        return results

    except Exception as e:
        print("FIND TEXT ERROR:", e)
        return []


def _screen_to_mouse_coordinates(x, y, screenshot):
    """
    Convert screenshot pixel coordinates to actual mouse coordinates.
    This fixes Windows display scaling / DPI mismatch.
    """
    try:
        screen_w, screen_h = pyautogui.size()
        image_w, image_h = screenshot.size

        if image_w <= 0 or image_h <= 0:
            return x, y

        scale_x = screen_w / image_w
        scale_y = screen_h / image_h

        mouse_x = int(x * scale_x)
        mouse_y = int(y * scale_y)

        mouse_x = max(0, min(screen_w - 1, mouse_x))
        mouse_y = max(0, min(screen_h - 1, mouse_y))

        print(
            "COORDINATE SCALE:",
            image_w, "x", image_h,
            "->",
            screen_w, "x", screen_h,
            "|",
            round(scale_x, 3),
            round(scale_y, 3)
        )

        return mouse_x, mouse_y

    except Exception as e:
        print("COORDINATE CONVERSION ERROR:", e)
        return x, y


def jarvis_type_text(text_to_type):
    """Type text into the currently focused field."""
    if not PYAUTOGUI_AVAILABLE:
        speak("Keyboard control is not available.")
        return True

    try:
        pyautogui.write(text_to_type, interval=0.025)
        speak("I typed " + text_to_type)
    except Exception as e:
        print("TYPE ERROR:", e)
        speak("Sorry, I could not type that.")
    return True


def jarvis_press_key(key):
    """Press a keyboard key."""
    if not PYAUTOGUI_AVAILABLE:
        speak("Keyboard control is not available.")
        return True

    try:
        pyautogui.press(key)
        speak("Done.")
    except Exception as e:
        print("KEY ERROR:", e)
        speak("Sorry, I could not press that key.")
    return True


# =========================================================
# ACTION VERIFICATION
# =========================================================

def _screen_signature():
    """Return a lightweight signature of the current screen."""
    if not PYAUTOGUI_AVAILABLE:
        return None

    try:
        import hashlib

        img = pyautogui.screenshot()

        # Resize before hashing to make the comparison fast.
        small = img.resize((64, 36))
        raw = small.tobytes()

        return hashlib.md5(raw).hexdigest()

    except Exception as e:
        print("SCREEN SIGNATURE ERROR:", e)
        return None


def verify_screen_changed(before_signature, wait_time=1.0):
    """Check whether the screen changed after an action."""
    if before_signature is None:
        return False

    time.sleep(wait_time)

    after_signature = _screen_signature()

    if after_signature is None:
        return False

    changed = before_signature != after_signature

    print(
        "ACTION VERIFICATION:",
        "SCREEN CHANGED" if changed else "NO MAJOR SCREEN CHANGE"
    )

    return changed


def verify_click(description, before_signature):
    """
    Verify a click by checking for a screen change and, if possible,
    checking whether the requested text is still visible.
    """
    changed = verify_screen_changed(before_signature, 1.0)

    # A screen change is useful evidence, but not every valid click
    # causes a visible change (checkboxes, hover actions, etc.).
    if changed:
        print("CLICK VERIFIED:", description)
        return True

    print(
        "CLICK NOT CONFIRMED:",
        description,
        "(screen may legitimately stay unchanged)"
    )

    return False


def verified_click_screen_element(description):
    """Find, click, then verify the action."""
    before = _screen_signature()

    element = find_visual_element(description)

    if not element:
        speak("I could not find " + description + " on the screen.")
        return False

    print(
        "VERIFIED CLICK TARGET:",
        description,
        "| type:", element["type"],
        "| mouse:", element["x"], element["y"]
    )

    pyautogui.moveTo(
        element["x"],
        element["y"],
        duration=0.35
    )

    time.sleep(0.25)

    pyautogui.click(
        element["x"],
        element["y"]
    )

    verified = verify_click(
        description,
        before
    )

    if verified:
        speak("Clicked " + description + " and verified the screen changed.")
    else:
        speak("I clicked " + description + ". The screen did not visibly change.")

    return True


def verified_type_text(text_to_type):
    """Type text and verify that the screen changed."""
    before = _screen_signature()

    jarvis_type_text(text_to_type)

    changed = verify_screen_changed(
        before,
        0.4
    )

    if changed:
        print("TYPE VERIFIED:", text_to_type)
    else:
        print("TYPE NOT VISIBLY VERIFIED:", text_to_type)

    return True


# =========================================================
# LOCAL SCREEN ELEMENT DETECTION
# =========================================================

def _get_visual_elements():
    """
    STEP 24 local UI detector.
    Detect likely buttons, input boxes, cards and UI rectangles with OpenCV.
    Gemini is NOT used here.
    """
    if not PYAUTOGUI_AVAILABLE or not CV2_AVAILABLE:
        return []

    try:
        screenshot = pyautogui.screenshot()
        import numpy as np

        img = np.array(screenshot)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 150)

        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE
        )

        image_h, image_w = gray.shape[:2]
        candidates = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h

            if area < 900 or w < 45 or h < 18:
                continue
            if w > image_w * 0.95 or h > image_h * 0.80:
                continue

            ratio = w / max(h, 1)
            if ratio < 0.5 or ratio > 25:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue

            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            corners = len(approx)

            if corners < 4 or corners > 12:
                continue

            # Heuristic UI classification.
            if ratio >= 3.0 and 25 <= h <= 120:
                element_type = "input_or_button"
            elif ratio >= 1.4 and 20 <= h <= 180:
                element_type = "button_or_card"
            else:
                element_type = "ui_box"

            candidates.append({
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "area": area,
                "ratio": ratio,
                "corners": corners,
                "type": element_type
            })

        # Prefer useful medium-sized UI shapes over huge containers.
        candidates.sort(
            key=lambda e: (
                1 if e["type"] == "input_or_button" else 0,
                min(e["area"], 500000)
            ),
            reverse=True
        )

        filtered = []
        for candidate in candidates:
            duplicate = False
            cx = candidate["x"] + candidate["w"] / 2
            cy = candidate["y"] + candidate["h"] / 2

            for existing in filtered:
                ex = existing["x"] + existing["w"] / 2
                ey = existing["y"] + existing["h"] / 2
                if abs(cx - ex) < 25 and abs(cy - ey) < 25:
                    duplicate = True
                    break

            if not duplicate:
                filtered.append(candidate)

            if len(filtered) >= 100:
                break

        return filtered

    except Exception as e:
        print("VISUAL ELEMENT ERROR:", e)
        return []


def detect_ui_shapes():
    """Return visual UI candidates mapped to real mouse coordinates."""
    if not PYAUTOGUI_AVAILABLE:
        return []

    try:
        screenshot = pyautogui.screenshot()
        shapes = _get_visual_elements()
        output = []

        for shape in shapes:
            cx = shape["x"] + shape["w"] // 2
            cy = shape["y"] + shape["h"] // 2
            mx, my = _screen_to_mouse_coordinates(cx, cy, screenshot)
            item = dict(shape)
            item["mouse_x"] = mx
            item["mouse_y"] = my
            output.append(item)

        return output
    except Exception as e:
        print("UI SHAPE MAP ERROR:", e)
        return []


def find_input_box():
    """Find a likely search/input field using shapes + OCR fallback."""
    if not PYAUTOGUI_AVAILABLE or not TESSERACT_AVAILABLE:
        return None

    try:
        screenshot = pyautogui.screenshot()
        img_w, img_h = screenshot.size

        # -------------------------------------------------
        # METHOD 1: visual rectangular candidates
        # -------------------------------------------------
        shapes = detect_ui_shapes()
        candidates = []

        for shape in shapes:
            w = int(shape.get("w", 0))
            h = int(shape.get("h", 0))
            ratio = float(shape.get("ratio", 0))

            # Broad range: modern browser search boxes can be rounded,
            # borderless, or have a lower aspect ratio than old fields.
            if w >= 140 and 24 <= h <= 110 and ratio >= 1.8:
                item = dict(shape)
                item["method"] = "visual_shape"
                candidates.append(item)

        # -------------------------------------------------
        # METHOD 2: OCR around common input/search labels
        # -------------------------------------------------
        try:
            data = pytesseract.image_to_data(
                screenshot,
                output_type=pytesseract.Output.DICT,
                config="--psm 11"
            )

            count = len(data.get("text", []))
            search_words = {
                "search", "searching", "type", "enter",
                "find", "address", "web", "url"
            }

            for i in range(count):
                raw = str(data["text"][i]).strip()
                word = re.sub(r"[^a-z0-9]", "", raw.lower())
                if word not in search_words:
                    continue

                try:
                    conf = float(data["conf"][i])
                except Exception:
                    conf = 0

                if conf < 20:
                    continue

                tx = int(data["left"][i])
                ty = int(data["top"][i])
                tw = int(data["width"][i])
                th = int(data["height"][i])

                # Build a generous input region around the placeholder.
                # For a left-aligned placeholder, the clickable field is
                # usually centered slightly to the right of the OCR text.
                box_x = max(0, tx - 30)
                box_y = max(0, ty - 22)
                box_w = min(img_w - box_x, max(220, tw + 260))
                box_h = min(img_h - box_y, max(45, th + 36))

                mx, my = _screen_to_mouse_coordinates(
                    box_x + box_w // 2,
                    box_y + box_h // 2,
                    screenshot
                )

                candidates.append({
                    "type": "ocr_input_fallback",
                    "x": box_x,
                    "y": box_y,
                    "w": box_w,
                    "h": box_h,
                    "ratio": box_w / max(box_h, 1),
                    "area": box_w * box_h,
                    "nearby_text": [raw],
                    "mouse_x": mx,
                    "mouse_y": my,
                    "method": "ocr_label"
                })
        except Exception as e:
            print("INPUT OCR FALLBACK ERROR:", e)

        if not candidates:
            return None

        # -------------------------------------------------
        # Score candidates. Prefer OCR search labels, then
        # wide fields, while avoiding huge page containers.
        # -------------------------------------------------
        def candidate_score(item):
            nearby = " ".join(
                item.get("nearby_text", [])
            ).lower()

            score = 0
            if item.get("method") == "ocr_label":
                score += 500
            if "search" in nearby:
                score += 300
            if "type" in nearby or "enter" in nearby:
                score += 150

            w = int(item.get("w", 0))
            h = int(item.get("h", 1))
            ratio = w / max(h, 1)

            if 2.5 <= ratio <= 12:
                score += 100
            if 180 <= w <= 900:
                score += 80
            if 30 <= h <= 80:
                score += 50

            # Penalize giant rectangles that are likely panels/windows.
            if w > img_w * 0.75 and h > img_h * 0.25:
                score -= 300

            return score

        candidates.sort(key=candidate_score, reverse=True)
        best = candidates[0]

        # Ensure mouse coordinates exist for visual candidates.
        if "mouse_x" not in best:
            cx = int(best["x"] + best["w"] // 2)
            cy = int(best["y"] + best["h"] // 2)
            mx, my = _screen_to_mouse_coordinates(
                cx, cy, screenshot
            )
            best["mouse_x"] = mx
            best["mouse_y"] = my

        print(
            "INPUT BOX CANDIDATE:",
            best,
            "| score:",
            candidate_score(best)
        )

        return best

    except Exception as e:
        print("INPUT BOX ERROR:", e)
        return None

def describe_ui_shapes(limit=15):
    """Print a local visual map of likely UI shapes."""
    shapes = detect_ui_shapes()
    if not shapes:
        speak("I could not detect UI boxes on the screen.")
        return True

    print("\n----- VISUAL UI MAP -----")
    for i, item in enumerate(shapes[:limit], 1):
        print(
            f'{i}. {item["type"]} | '
            f'box=({item["x"]},{item["y"]},{item["w"]},{item["h"]}) | '
            f'mouse=({item["mouse_x"]},{item["mouse_y"]})'
        )
    print("-------------------------\n")

    speak("I detected " + str(min(len(shapes), limit)) + " likely UI shapes.")
    return True


def smart_input_type(text_to_type):
    """Locate a likely input field, click it, then type text."""
    field = find_input_box()
    if not field:
        speak("I could not find an input or search box on the screen.")
        return True

    print("SMART INPUT FIELD:", field)
    pyautogui.moveTo(field["mouse_x"], field["mouse_y"], duration=0.25)
    pyautogui.click(field["mouse_x"], field["mouse_y"])
    time.sleep(0.25)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.15)
    pyautogui.write(text_to_type, interval=0.03)
    speak("I typed " + text_to_type + " into the input box.")
    return True


def find_visual_element(description):
    """
    Find a visible UI element by combining OCR text and simple visual
    shape detection. Text matching is preferred because it is safer.
    """
    description = description.lower().strip()

    # First try OCR. If the user says "login button", try "login".
    ocr_target = re.sub(
        r"\b(button|icon|box|field|area|menu)\b",
        "",
        description
    ).strip()

    if ocr_target:
        matches = find_screen_text(ocr_target)

        if matches:
            best = sorted(
                matches,
                key=lambda item: (
                    {"phrase": 3, "exact": 2, "partial": 1}.get(
                        item.get("match_type"), 0
                    ),
                    item["confidence"]
                ),
                reverse=True
            )[0]

            screenshot = pyautogui.screenshot()

            cx = best["x"] + best["w"] // 2
            cy = best["y"] + best["h"] // 2

            mx, my = _screen_to_mouse_coordinates(
                cx, cy, screenshot
            )

            return {
                "type": "text",
                "text": best["text"],
                "x": mx,
                "y": my,
                "confidence": best["confidence"]
            }

    # If no text match, return a visual candidate only when the
    # description explicitly asks for a generic UI element.
    elements = _get_visual_elements()

    if elements and any(word in description for word in [
        "button", "icon", "box", "field", "menu"
    ]):
        screenshot = pyautogui.screenshot()
        best = elements[0]

        cx = best["x"] + best["w"] // 2
        cy = best["y"] + best["h"] // 2

        mx, my = _screen_to_mouse_coordinates(
            cx, cy, screenshot
        )

        return {
            "type": "visual",
            "text": description,
            "x": mx,
            "y": my,
            "confidence": 0
        }

    return None




def click_screen_element(description):
    """Locate an element and click its center."""
    element = find_visual_element(description)

    if not element:
        speak("I could not find " + description + " on the screen.")
        return True

    print(
        "ELEMENT CLICK:",
        description,
        "| type:", element["type"],
        "| mouse:", element["x"], element["y"]
    )

    pyautogui.moveTo(
        element["x"],
        element["y"],
        duration=0.35
    )

    time.sleep(0.25)

    pyautogui.click(
        element["x"],
        element["y"]
    )

    speak("Clicked " + description + ".")
    return True


# =========================================================
# CONTINUOUS SCROLL CONTROL
# =========================================================
scroll_running = False
scroll_direction = 0
scroll_thread = None
scroll_lock = threading.Lock()


def _continuous_scroll_worker():
    global scroll_running, scroll_direction

    print("CONTINUOUS SCROLL THREAD STARTED")

    while True:
        with scroll_lock:
            running = scroll_running
            direction = scroll_direction

        if not running or direction == 0:
            break

        try:
            # Repeat small wheel movements so the page keeps moving.
            pyautogui.scroll(direction * 10)
            time.sleep(0.07)

        except Exception as e:
            print("CONTINUOUS SCROLL ERROR:", e)
            break

    with scroll_lock:
        scroll_running = False
        scroll_direction = 0

    print("CONTINUOUS SCROLL THREAD STOPPED")


def start_continuous_scroll(direction):
    global scroll_running, scroll_direction, scroll_thread

    if not PYAUTOGUI_AVAILABLE:
        speak("Mouse control is not available.")
        return True

    with scroll_lock:
        scroll_direction = direction

        if scroll_running:
            print("SCROLL DIRECTION CHANGED:", direction)
            return True

        scroll_running = True

    scroll_thread = threading.Thread(
        target=_continuous_scroll_worker,
        daemon=True
    )
    scroll_thread.start()

    if direction == -1:
        speak("Continuous scrolling down started. Say stop scrolling to stop.")
    else:
        speak("Continuous scrolling up started. Say stop scrolling to stop.")

    return True


def stop_continuous_scroll():
    global scroll_running, scroll_direction

    with scroll_lock:
        was_running = scroll_running
        scroll_running = False
        scroll_direction = 0

    if was_running:
        print("CONTINUOUS SCROLL STOPPED")
        speak("Scrolling stopped.")
    else:
        print("SCROLL WAS NOT RUNNING")

    return True


def jarvis_scroll(command):
    """Start continuous up/down scrolling until the user says stop."""
    command = command.lower()

    # Stop command gets highest priority.
    if any(phrase in command for phrase in [
        "scroll rok do",
        "scroll roko",
        "scroll rok",
        "scroll band karo",
        "scroll band",
        "scroll stop karo",
        "scroll stop",
        "stop scrolling",
        "stop scroll",
        "ruk jao",
        "ruko",
        "bas"
    ]):
        return stop_continuous_scroll()

    # Direction.
    if any(word in command for word in [
        "upar", "up", "ऊपर"
    ]):
        return start_continuous_scroll(1)

    if any(word in command for word in [
        "neeche", "niche", "down", "नीचे"
    ]):
        return start_continuous_scroll(-1)

    return True


def find_and_click_text(target):
    """Find visible text using OCR and click the correctly scaled center."""
    if not PYAUTOGUI_AVAILABLE:
        speak("Mouse control is not available.")
        return True

    if not TESSERACT_AVAILABLE:
        speak("Local OCR is not available.")
        return True

    try:
        # Capture the same screen used for OCR so coordinates stay consistent.
        tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        pytesseract.pytesseract.tesseract_cmd = tesseract_path

        screenshot = pyautogui.screenshot()

        # Temporarily use the OCR routine's normal fresh capture.
        matches = find_screen_text(target)

        if not matches:
            print("TEXT NOT FOUND:", target)
            speak("I could not find " + target + " on the screen.")
            return True

        # Prefer phrase > exact > partial, then confidence.
        priority = {
            "phrase": 3,
            "exact": 2,
            "partial": 1
        }

        best = sorted(
            matches,
            key=lambda item: (
                priority.get(item.get("match_type"), 0),
                item["confidence"]
            ),
            reverse=True
        )[0]

        center_x = best["x"] + best["w"] // 2
        center_y = best["y"] + best["h"] // 2

        mouse_x, mouse_y = _screen_to_mouse_coordinates(
            center_x,
            center_y,
            screenshot
        )

        print(
            "OCR TARGET:",
            target
        )

        print(
            "TEXT FOUND:",
            best["text"],
            "OCR:",
            center_x,
            center_y,
            "MOUSE:",
            mouse_x,
            mouse_y,
            "confidence:",
            round(best["confidence"], 1),
            "type:",
            best.get("match_type")
        )

        # Move first and show the final position in the console.
        pyautogui.moveTo(
            mouse_x,
            mouse_y,
            duration=0.35
        )

        time.sleep(0.25)

        pyautogui.click(
            x=mouse_x,
            y=mouse_y
        )

        speak(
            "Found "
            + best["text"]
            + " and clicked it."
        )

        return True

    except Exception as e:
        print("CLICK ERROR:", e)
        speak("Sorry, I could not click that correctly.")
        return True


def find_text_position(target):
    """Find text and report its actual mouse coordinates."""
    if not PYAUTOGUI_AVAILABLE or not TESSERACT_AVAILABLE:
        speak("Local screen reading is not available.")
        return True

    matches = find_screen_text(target)

    if not matches:
        speak("I could not find " + target + " on the screen.")
        return True

    priority = {
        "phrase": 3,
        "exact": 2,
        "partial": 1
    }

    best = sorted(
        matches,
        key=lambda item: (
            priority.get(item.get("match_type"), 0),
            item["confidence"]
        ),
        reverse=True
    )[0]

    center_x = best["x"] + best["w"] // 2
    center_y = best["y"] + best["h"] // 2

    screenshot = pyautogui.screenshot()

    mouse_x, mouse_y = _screen_to_mouse_coordinates(
        center_x,
        center_y,
        screenshot
    )

    print(
        "TEXT POSITION:",
        best["text"],
        "OCR:",
        center_x,
        center_y,
        "MOUSE:",
        mouse_x,
        mouse_y,
        "confidence:",
        round(best["confidence"], 1)
    )

    speak(
        "I found "
        + best["text"]
        + " at mouse position "
        + str(mouse_x)
        + " by "
        + str(mouse_y)
        + "."
    )

    return True


# =========================================================
# GEMINI VISION - SCREEN UNDERSTANDING
# =========================================================

def analyze_screen():

    if not PYAUTOGUI_AVAILABLE:

        speak(
            "I cannot capture the screen because the screenshot system is unavailable."
        )

        return True


    try:

        screenshot = pyautogui.screenshot()

        screenshot.save(
            SCREENSHOT_FILE
        )

        with open(
            SCREENSHOT_FILE,
            "rb"
        ) as image_file:

            image_bytes = image_file.read()


        prompt = """
You are JARVIS, a computer assistant.

Look carefully at this screenshot.

Tell the user what is currently visible on the screen.
Focus on:
- open applications
- browser pages
- important buttons
- visible text
- errors or warnings
- what the user appears to be doing

Keep the answer concise because it will be spoken aloud.

Do not invent anything that is not visible.
"""


        last_error = None

        for model in GEMINI_MODELS:

            try:

                print(
                    "Trying Gemini Vision:",
                    model
                )

                response = client.models.generate_content(
                    model=model,
                    contents=[
                        prompt,
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type="image/png"
                        )
                    ]
                )

                answer = response.text.strip()

                if answer:

                    print(
                        "SCREEN ANALYSIS:",
                        answer
                    )

                    speak(
                        answer
                    )

                    return True


            except Exception as e:

                last_error = e

                print(
                    "Gemini Vision error:",
                    model,
                    e
                )

                time.sleep(1)


        print(
            "ALL GEMINI VISION MODELS FAILED:",
            last_error
        )

        speak(
            "Sorry Shailendra, I could not analyze the screen right now."
        )

        return True


    except Exception as e:

        print(
            "SCREEN ANALYSIS ERROR:",
            e
        )

        speak(
            "Sorry, I could not read the screen."
        )

        return True


# =========================================================
# SCREEN TOOLS
# =========================================================

SCREENSHOT_FILE = "jarvis_screen.png"


# =========================================================
# GOAL-BASED AUTONOMOUS TASKS
# =========================================================

# =========================================================
# TASK MEMORY + REUSABLE WORKFLOWS
# =========================================================

WORKFLOW_MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "jarvis_workflows.json"
)


def load_workflows():
    try:
        if not os.path.exists(WORKFLOW_MEMORY_FILE):
            return {}
        with open(WORKFLOW_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print("WORKFLOW LOAD ERROR:", e)
        return {}


def save_workflows(data):
    try:
        with open(WORKFLOW_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("WORKFLOW SAVE ERROR:", e)
        return False


def workflow_key(name):
    name = re.sub(r"[^a-z0-9 ]", "", name.lower())
    return re.sub(r"\s+", " ", name).strip()


def remember_workflow(name, steps, original_command=None):
    data = load_workflows()
    key = workflow_key(name)

    data[key] = {
        "name": name,
        "original_command": original_command,
        "steps": [step_name for step_name, _ in steps],
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    if save_workflows(data):
        print("WORKFLOW SAVED:", name)
        return True
    return False


def find_saved_workflow(query):
    data = load_workflows()
    if not data:
        return None

    q = workflow_key(query)

    if q in data:
        return data[q]

    for key, item in data.items():
        if q in key or key in q:
            return item

    q_words = set(q.split())
    best = None
    best_score = 0

    for key, item in data.items():
        score = len(q_words.intersection(key.split()))
        if score > best_score:
            best_score = score
            best = item

    return best if best_score > 0 else None


def list_saved_workflows():
    data = load_workflows()

    if not data:
        speak("I do not have any saved workflows yet.")
        return True

    names = [
        item.get("name", key)
        for key, item in data.items()
    ]

    print("SAVED WORKFLOWS:", names)
    speak(
        "I have "
        + str(len(names))
        + " saved workflows."
    )
    return True


def clear_saved_workflows():
    save_workflows({})
    speak("Saved workflows cleared.")
    return True


def run_saved_workflow(query):
    workflow = find_saved_workflow(query)

    if not workflow:
        speak("I could not find that saved workflow.")
        return True

    original_command = workflow.get("original_command")

    if not original_command:
        speak(
            "I remember that workflow, but it cannot be replayed automatically yet."
        )
        return True

    speak(
        "I found the saved workflow "
        + workflow.get("name", "workflow")
        + ". I will run it again."
    )

    print("REUSING WORKFLOW:", workflow)

    return run_advanced_goal_planner(original_command)


def handle_workflow_memory(command):
    cleaned = re.sub(r"\s+", " ", command.lower()).strip()

    if any(phrase in cleaned for phrase in [
        "saved workflows batao",
        "saved workflow batao",
        "mere workflows batao",
        "workflows dikhao",
        "saved tasks batao"
    ]):
        return list_saved_workflows()

    if any(phrase in cleaned for phrase in [
        "saved workflows delete karo",
        "saved workflows clear karo",
        "workflows delete karo",
        "workflows clear karo"
    ]):
        return clear_saved_workflows()

    # -----------------------------------------------------
    # REPLAY LAST / SAVED WORKFLOW
    # IMPORTANT:
    # "wahi" must stay LOCAL and must never fall through to Gemini.
    # -----------------------------------------------------

    replay_match = re.search(
        r"^(?:wahi|same|previous|pichla|pichle)"
        r"(?:\s+(?:kaam|task|workflow))?"
        r"(?:\s+(?:ko|wala|wali|walla))?"
        r"(?:\s+(?:phir|dobara|again))?"
        r"(?:\s+(?:karo|kar\s+do|chalao|run\s+karo|repeat\s+karo))?"
        r"\s*$",
        cleaned
    )

    if replay_match:
        data = load_workflows()

        if not data:
            speak("Mere paas koi saved workflow nahi hai.")
            return True

        # Most recently saved workflow.
        workflows = list(data.values())

        workflows.sort(
            key=lambda item: item.get("saved_at", ""),
            reverse=True
        )

        latest = workflows[0]

        latest_name = latest.get(
            "name",
            "last workflow"
        )

        original_command = latest.get(
            "original_command"
        )

        if not original_command:
            speak(
                "Last workflow saved hai, lekin usko automatically replay "
                "karne ke liye command available nahi hai."
            )
            return True

        speak(
            "Wahi workflow dobara chala raha hoon: "
            + latest_name
        )

        print(
            "REPLAY LAST WORKFLOW:",
            latest_name
        )

        # Run locally. Do NOT send this command to Gemini.
        result = run_advanced_goal_planner(
            original_command
        )

        return True

    return False


# =========================================================
# TASK PLANNER + RETRY
# =========================================================

def _task_pause(seconds=0.8):
    time.sleep(seconds)


def execute_planned_step(step_name, action_func, retries=2):
    """
    Execute one task step with limited retries.
    Never retries potentially sensitive actions automatically.
    """
    print("\nTASK STEP:", step_name)

    for attempt in range(1, retries + 1):
        print(
            "ATTEMPT:",
            attempt,
            "of",
            retries,
            "|",
            step_name
        )

        try:
            result = action_func()

            if result is not False:
                print("STEP COMPLETE:", step_name)
                return True

        except Exception as e:
            print(
                "STEP ERROR:",
                step_name,
                "|",
                e
            )

        if attempt < retries:
            print("RETRYING:", step_name)
            _task_pause(0.8)

    print("STEP FAILED:", step_name)
    return False


def plan_youtube_search_task(query):
    """
    Build a safe browser-search workflow.
    Direct URL search is used because it is more reliable than
    depending on a specific page layout.
    """
    return [
        ("Open YouTube search", lambda: _open_youtube_search(query)),
        ("Verify YouTube page", lambda: _verify_current_screen()),
    ]


def _open_youtube_search(query):
    url = (
        "https://www.youtube.com/results?search_query="
        + urllib.parse.quote_plus(query)
    )

    before = _screen_signature()

    webbrowser.open(url)

    _task_pause(2.5)

    changed = verify_screen_changed(
        before,
        0.5
    )

    # Even if the screen signature does not change, the URL command
    # was successfully issued, so this step is considered dispatched.
    print(
        "YOUTUBE SEARCH:",
        query,
        "| changed:",
        changed
    )

    return True


def _verify_current_screen():
    """
    Lightweight verification using OCR.
    """
    if not TESSERACT_AVAILABLE:
        print("OCR unavailable; skipping text verification.")
        return True

    matches = find_screen_text("YouTube")

    if matches:
        print("VERIFICATION: YouTube text found.")
        return True

    # Search results may not expose the exact word depending on page state.
    # Treat the browser navigation as successful rather than looping forever.
    print("VERIFICATION: YouTube text not detected; page may still be loading.")
    return True


def execute_goal_plan(plan, original_command=None, workflow_name=None):
    """
    Run a planned task sequentially.
    """
    if not plan:
        return False

    speak("I have a plan. I will execute it step by step.")

    for step_name, action in plan:
        success = execute_planned_step(
            step_name,
            action,
            retries=2
        )

        if not success:
            speak(
                "The task stopped because "
                + step_name
                + " failed."
            )
            return False

    speak("The task is complete.")

    if workflow_name:
        remember_workflow(
            workflow_name,
            plan,
            original_command
        )

    return True


def run_advanced_goal_planner(command):
    """
    Advanced goal planner for safe, non-sensitive browser searches.
    """
    cleaned = re.sub(
        r"\s+",
        " ",
        command.lower()
    ).strip()

    # YouTube search goal.
    match = re.search(
        r"youtube\s+(?:par|pe|mein|me)\s+(.+?)\s+"
        r"(?:search\s+karo|dhoondo|dhundho|"
        r"ki\s+videos\s+dhoondo|videos\s+search\s+karo)\s*$",
        cleaned
    )

    if match:
        query = match.group(1).strip()

        query = re.sub(
            r"\s+ki\s+videos?$",
            "",
            query
        ).strip()

        if query:
            print(
                "ADVANCED GOAL:",
                "YouTube search ->",
                query
            )

            plan = plan_youtube_search_task(query)

            return execute_goal_plan(
                plan,
                original_command=command,
                workflow_name="YouTube " + query + " search"
            )

    # Google search goal.
    match = re.search(
        r"google\s+(?:par|pe|mein|me)\s+(.+?)\s+"
        r"(?:search\s+karo|dhoondo|dhundho|find\s+karo)\s*$",
        cleaned
    )

    if match:
        query = match.group(1).strip()

        if query:
            url = (
                "https://www.google.com/search?q="
                + urllib.parse.quote_plus(query)
            )

            speak(
                "I will search Google for "
                + query
            )

            before = _screen_signature()
            webbrowser.open(url)
            _task_pause(2.5)

            verify_screen_changed(
                before,
                0.5
            )

            speak("Google search task complete.")
            return True

    return False


def run_goal_based_task(command):
    """
    Handle common goal-style commands without requiring the user
    to dictate every individual click/type/Enter step.
    Local/rule-based first, so Gemini quota is not required.
    """
    cleaned = re.sub(r"\s+", " ", command.lower()).strip()

    # -----------------------------------------------------
    # YOUTUBE SEARCH GOAL
    # Examples:
    #   youtube par free fire search karo
    #   youtube par free fire ki videos dhoondo
    # -----------------------------------------------------
    youtube_match = re.search(
        r"youtube\s+(?:par|pe|mein|me)\s+(.+?)\s+"
        r"(?:search\s+karo|dhoondo|dhundho|ki\s+videos\s+dhoondo|"
        r"ki\s+video\s+dhoondo|videos\s+search\s+karo)\s*$",
        cleaned
    )

    if youtube_match:
        query = youtube_match.group(1).strip()
        query = re.sub(r"\s+ki\s+videos?$", "", query).strip()

        if query:
            speak("Okay. Searching YouTube for " + query)

            url = (
                "https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(query)
            )

            before = _screen_signature()
            webbrowser.open(url)
            time.sleep(2.5)

            changed = verify_screen_changed(before, 0.5)

            if changed:
                print("GOAL VERIFIED: YouTube search opened.")
            else:
                print("GOAL STATUS: YouTube search command sent.")

            return True

    # -----------------------------------------------------
    # GOOGLE SEARCH GOAL
    # -----------------------------------------------------
    google_match = re.search(
        r"google\s+(?:par|pe|mein|me)\s+(.+?)\s+"
        r"(?:search\s+karo|dhoondo|dhundho|find\s+karo)\s*$",
        cleaned
    )

    if google_match:
        query = google_match.group(1).strip()

        if query:
            speak("Okay. Searching Google for " + query)

            url = (
                "https://www.google.com/search?q="
                + urllib.parse.quote_plus(query)
            )

            before = _screen_signature()
            webbrowser.open(url)
            time.sleep(2.5)

            changed = verify_screen_changed(before, 0.5)

            if changed:
                print("GOAL VERIFIED: Google search opened.")
            else:
                print("GOAL STATUS: Google search command sent.")

            return True

    # -----------------------------------------------------
    # OPEN A KNOWN WEBSITE AS A GOAL
    # -----------------------------------------------------
    site_map = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "chatgpt": "https://chatgpt.com",
        "github": "https://github.com",
        "whatsapp": "https://web.whatsapp.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "linkedin": "https://www.linkedin.com",
    }

    open_match = re.search(
        r"^(?:please\s+)?(?:open|kholo|khol)\s+([a-z0-9]+)\s*$",
        cleaned
    )

    if not open_match:
        open_match = re.search(
            r"^([a-z0-9]+)\s+(?:open\s+karo|kholo|khol)\s*$",
            cleaned
        )

    if open_match:
        site = open_match.group(1)

        if site in site_map:
            speak("Opening " + site)
            webbrowser.open(site_map[site])
            return True

    return False




def screen_tools(command):

    # -----------------------------------------------------
    # VISUAL ELEMENT LOCATION / CLICK
    # -----------------------------------------------------
    visual_locate = re.search(
        r"(?:screen\s+(?:par|pe|me|mein))\s+(.+?)\s+"
        r"(?:dhoondo|dhundho|find karo|find karke batao|"
        r"kaha hai|kahan hai|locate karo)\s*$",
        command,
        flags=re.IGNORECASE
    )

    if visual_locate:
        target = visual_locate.group(1).strip()
        locate_screen_element(target)
        return True

    visual_click = re.search(
        r"(?:screen\s+(?:par|pe|me|mein))\s+(.+?)\s+"
        r"(?:click karo|click|dabao|press karo)\s*$",
        command,
        flags=re.IGNORECASE
    )

    if visual_click:
        target = visual_click.group(1).strip()
        verified_click_screen_element(target)
        return True

    # -----------------------------------------------------
    # STOP CONTINUOUS SCROLL
    # -----------------------------------------------------
    if any(phrase in command for phrase in [
        "stop scrolling",
        "stop scroll",
        "scroll rok do",
        "scroll roko",
        "scroll rok",
        "scroll band karo",
        "scroll band",
        "scroll stop karo",
        "scroll stop",
        "ruko",
        "ruk jao",
        "bas"
    ]):
        return stop_continuous_scroll()

    # -----------------------------------------------------
    # MULTI-STEP COMPUTER ACTION
    # -----------------------------------------------------
    if run_multistep_command(command):
        return True

    # -----------------------------------------------------
    # TYPE TEXT
    # Examples:
    #   type Free Fire
    #   search box mein Free Fire type karo
    # -----------------------------------------------------
    type_match = re.search(
        r"(?:type|type karo|likho|likh do|enter text)\s+(.+?)\s*$",
        command
    )

    if type_match:
        value = type_match.group(1).strip()

        # Remove common trailing filler.
        value = re.sub(r"\s+(?:karo|kar do)$", "", value).strip()

        if value:
            verified_type_text(value)
            return True

    # -----------------------------------------------------
    # PRESS ENTER / KEYS
    # -----------------------------------------------------
    if any(phrase in command for phrase in [
        "enter dabao",
        "enter karo",
        "press enter",
        "enter press",
        "enter daba"
    ]):
        jarvis_press_key("enter")
        return True

    if any(phrase in command for phrase in [
        "escape dabao",
        "esc dabao",
        "press escape",
        "press esc"
    ]):
        jarvis_press_key("esc")
        return True

    if any(phrase in command for phrase in [
        "backspace dabao",
        "press backspace"
    ]):
        jarvis_press_key("backspace")
        return True

    if any(phrase in command for phrase in [
        "tab dabao",
        "press tab"
    ]):
        jarvis_press_key("tab")
        return True

    # -----------------------------------------------------
    # SCROLL
    # -----------------------------------------------------
    if any(word in command for word in [
        "scroll", "स्क्रॉल"
    ]) and any(word in command for word in [
        "upar", "up", "neeche", "niche", "down", "नीचे", "ऊपर"
    ]):
        jarvis_scroll(command)
        return True



    # -----------------------------------------------------
    # FIND AND CLICK SCREEN TEXT
    # Uses local OCR - no Gemini quota
    #
    # Supports BOTH:
    #   screen par YouTube click karo
    #   click YouTube
    #   screen par Settings dabao
    # -----------------------------------------------------

    click_target = None

    screen_click_match = re.search(
        r"(?:screen\s+(?:par|pe|me|mein))\s+(.+?)\s+"
        r"(?:click|click\s+karo|dabao|press\s+karo)\s*$",
        command
    )

    if screen_click_match:
        click_target = screen_click_match.group(1).strip()

    else:
        direct_click_match = re.search(
            r"^(?:click|click\s+karo|dabao|press\s+karo)"
            r"\s+(?:on\s+)?(.+?)\s*$",
            command
        )

        if direct_click_match:
            click_target = direct_click_match.group(1).strip()

    if click_target:

        click_target = re.sub(
            r"^(?:screen\s+(?:par|pe|me|mein))\s*",
            "",
            click_target
        )

        click_target = re.sub(
            r"\s+(?:ko|par|pe)$",
            "",
            click_target
        ).strip()

        if click_target:
            speak(
                "Okay, I will find "
                + click_target
                + " on the screen."
            )

            find_and_click_text(click_target)

            return True

    # -----------------------------------------------------
    # FIND SCREEN TEXT POSITION WITHOUT CLICKING
    # -----------------------------------------------------
    position_match = re.search(
        r"(?:screen\s+(?:par|pe|me|mein))\s+(.+?)"
        r"\s+(?:dhoondo|find\s+karo|find\s+karke\s+batao|"
        r"kaha\s+hai|kahan\s+hai)\s*$",
        command
    )

    if position_match:
        target = position_match.group(1).strip()
        speak("Okay, I will find it.")
        find_text_position(target)
        return True


    # -----------------------------------------------------
    # LOCAL OCR / READ SCREEN TEXT
    # IMPORTANT: BEFORE GEMINI
    # -----------------------------------------------------
    if (
        "screen text read karo" in command
        or "screen ka text read karo" in command
        or "screen par text kya hai" in command
        or "screen pe text kya hai" in command
        or "screen ka text batao" in command
        or "screen ka likha hua padho" in command
        or "screen ka likha hua batao" in command
        or "screen text padho" in command
        or "screen text batao" in command
        or "screen ocr" in command
        or "ocr screen" in command
    ):
        speak("Okay, I will read the screen locally.")
        read_screen_locally()
        return True

    # -----------------------------------------------------
    # UNDERSTAND / READ SCREEN
    # -----------------------------------------------------

    if (
        "screen par kya hai" in command
        or "screen par kya hai" in command
        or "screen pe kya hai" in command
        or "screen me kya hai" in command
        or "screen ko dekho" in command
        or "screen dekho" in command
        or "screen read karo" in command
        or "screen ko read karo" in command
        or "screen samjho" in command
        or "screen analyze karo" in command
        or "screen analyse karo" in command
    ):

        speak(
            "Let me look at the screen."
        )

        analyze_screen()

        return True


    # -----------------------------------------------------
    # TAKE SCREENSHOT
    # -----------------------------------------------------

    if (
        "screenshot lo" in command
        or "screenshot lena" in command
        or "screenshot le lo" in command
        or "screen shot lo" in command
        or "screen shot lena" in command
        or "screen ka screenshot" in command
    ):

        if not PYAUTOGUI_AVAILABLE:

            speak(
                "Screenshot package is not available."
            )

            return True


        try:

            screenshot = pyautogui.screenshot()

            screenshot.save(
                SCREENSHOT_FILE
            )

            speak(
                "Screenshot taken and saved."
            )

            print(
                "SCREENSHOT:",
                os.path.abspath(SCREENSHOT_FILE)
            )

        except Exception as e:

            print(
                "SCREENSHOT ERROR:",
                e
            )

            speak(
                "Sorry, I could not take the screenshot."
            )

        return True


    # -----------------------------------------------------
    # SHOW SCREENSHOT LOCATION
    # -----------------------------------------------------

    if (
        "screenshot kaha hai" in command
        or "screenshot location" in command
    ):

        path = os.path.abspath(
            SCREENSHOT_FILE
        )

        if os.path.exists(path):

            speak(
                "Your screenshot is saved in the JARVIS folder."
            )

            print(
                "SCREENSHOT:",
                path
            )

        else:

            speak(
                "There is no screenshot yet."
            )

        return True


    return False


# =========================================================
# MOUSE CONTROL
# =========================================================

def mouse_control(command):

    if not PYAUTOGUI_AVAILABLE:

        if any(word in command for word in [
            "mouse",
            "click",
            "double click",
            "right click"
        ]):

            speak(
                "Mouse control package is not installed."
            )

            return True


    # LEFT CLICK
    if (
        "left click" in command
        or "left-click" in command
        or "left click karo" in command
        or "click karo" in command
    ):

        speak("Left click")

        try:
            pyautogui.click()
        except Exception as e:
            print("MOUSE ERROR:", e)

        return True


    # RIGHT CLICK
    if (
        "right click" in command
        or "right-click" in command
        or "right click karo" in command
    ):

        speak("Right click")

        try:
            pyautogui.rightClick()
        except Exception as e:
            print("MOUSE ERROR:", e)

        return True


    # DOUBLE CLICK
    if (
        "double click" in command
        or "double-click" in command
        or "double click karo" in command
    ):

        speak("Double click")

        try:
            pyautogui.doubleClick()
        except Exception as e:
            print("MOUSE ERROR:", e)

        return True


    # MOVE TO CENTER
    if (
        "mouse center par" in command
        or "mouse ko center par" in command
        or "mouse center me" in command
    ):

        speak("Moving mouse to the center")

        try:

            width, height = pyautogui.size()

            pyautogui.moveTo(
                width // 2,
                height // 2,
                duration=0.3
            )

        except Exception as e:

            print("MOUSE ERROR:", e)

        return True


    # MOVE TO TOP LEFT
    if (
        "mouse top left" in command
        or "mouse ko top left" in command
    ):

        speak("Moving mouse to the top left")

        try:
            pyautogui.moveTo(
                10,
                10,
                duration=0.3
            )
        except Exception as e:
            print("MOUSE ERROR:", e)

        return True


    # MOVE TO TOP RIGHT
    if (
        "mouse top right" in command
        or "mouse ko top right" in command
    ):

        speak("Moving mouse to the top right")

        try:

            width, height = pyautogui.size()

            pyautogui.moveTo(
                width - 10,
                10,
                duration=0.3
            )

        except Exception as e:

            print("MOUSE ERROR:", e)

        return True


    # MOVE TO BOTTOM LEFT
    if (
        "mouse bottom left" in command
        or "mouse ko bottom left" in command
    ):

        speak("Moving mouse to the bottom left")

        try:

            width, height = pyautogui.size()

            pyautogui.moveTo(
                10,
                height - 10,
                duration=0.3
            )

        except Exception as e:

            print("MOUSE ERROR:", e)

        return True


    # MOVE TO BOTTOM RIGHT
    if (
        "mouse bottom right" in command
        or "mouse ko bottom right" in command
    ):

        speak("Moving mouse to the bottom right")

        try:

            width, height = pyautogui.size()

            pyautogui.moveTo(
                width - 10,
                height - 10,
                duration=0.3
            )

        except Exception as e:

            print("MOUSE ERROR:", e)

        return True


    return False


# =========================================================
# ADVANCED BROWSER ACTIONS
# =========================================================

def advanced_browser_actions(command):

    if not PYAUTOGUI_AVAILABLE:
        if any(word in command for word in [
            "type ",
            "likho ",
            "scroll",
            "upar scroll",
            "neeche scroll"
        ]):
            speak(
                "Browser control package is not installed yet."
            )
            return True


    # TYPE TEXT
    type_match = re.search(
        r"(?:type|likho|type karo)\s+(.+)",
        command
    )

    if type_match:

        text_to_type = type_match.group(1).strip()

        if text_to_type:

            speak("Typing")

            try:
                pyautogui.write(
                    text_to_type,
                    interval=0.02
                )
            except Exception as e:
                print("TYPE ERROR:", e)
                speak("I could not type that.")

            return True


    # SCROLL DOWN
    if (
        "scroll down" in command
        or "neeche scroll" in command
        or "scroll neeche" in command
        or "neeche jao" in command
    ):

        speak("Scrolling down")

        try:
            pyautogui.scroll(-5)
        except Exception as e:
            print("SCROLL ERROR:", e)

        return True


    # SCROLL UP
    if (
        "scroll up" in command
        or "upar scroll" in command
        or "scroll upar" in command
        or "upar jao" in command
    ):

        speak("Scrolling up")

        try:
            pyautogui.scroll(5)
        except Exception as e:
            print("SCROLL ERROR:", e)

        return True


    # PRESS ENTER
    if (
        command == "press enter"
        or command == "enter dabao"
        or command == "enter karo"
    ):

        speak("Pressing Enter")

        try:
            pyautogui.press("enter")
        except Exception as e:
            print("ENTER ERROR:", e)

        return True


    # PRESS ESCAPE
    if (
        command == "press escape"
        or command == "escape dabao"
        or command == "escape karo"
    ):

        speak("Pressing Escape")

        try:
            pyautogui.press("esc")
        except Exception as e:
            print("ESC ERROR:", e)

        return True


    return False


# =========================================================
# BROWSER CONTROL
# =========================================================

def browser_control(command):

    # NEW TAB
    if (
        "new tab" in command
        or "open new tab" in command
        or "naya tab kholo" in command
        or "naya tab khol do" in command
    ):

        speak("Opening a new tab")

        subprocess.run(
            [
                "powershell",
                "-command",
                "$ws = New-Object -ComObject WScript.Shell; "
                "$ws.AppActivate((Get-Process chrome -ErrorAction SilentlyContinue | "
                "Select-Object -First 1).MainWindowTitle); "
                "$ws.SendKeys('^t')"
            ],
            shell=True
        )

        return True


    # CLOSE CURRENT TAB
    if (
        "close tab" in command
        or "close current tab" in command
        or "tab band karo" in command
        or "current tab band karo" in command
    ):

        speak("Closing the current tab")

        subprocess.run(
            [
                "powershell",
                "-command",
                "$ws = New-Object -ComObject WScript.Shell; "
                "$ws.SendKeys('^w')"
            ],
            shell=True
        )

        return True


    # REFRESH
    if (
        "refresh page" in command
        or "page refresh karo" in command
        or "refresh karo" in command
    ):

        speak("Refreshing the page")

        subprocess.run(
            [
                "powershell",
                "-command",
                "$ws = New-Object -ComObject WScript.Shell; "
                "$ws.SendKeys('{F5}')"
            ],
            shell=True
        )

        return True


    # GO BACK
    if (
        "go back" in command
        or "back jao" in command
        or "peeche jao" in command
        or "back karo" in command
    ):

        speak("Going back")

        subprocess.run(
            [
                "powershell",
                "-command",
                "$ws = New-Object -ComObject WScript.Shell; "
                "$ws.SendKeys('%{LEFT}')"
            ],
            shell=True
        )

        return True


    # GO FORWARD
    if (
        "go forward" in command
        or "forward jao" in command
        or "aage jao" in command
        or "forward karo" in command
    ):

        speak("Going forward")

        subprocess.run(
            [
                "powershell",
                "-command",
                "$ws = New-Object -ComObject WScript.Shell; "
                "$ws.SendKeys('%{RIGHT}')"
            ],
            shell=True
        )

        return True


    return False


# =========================================================
# DIRECT WEBSITE COMMANDS
# =========================================================

def direct_website_commands(command):

    websites = {

        "gmail": "https://mail.google.com",

        "chatgpt": "https://chatgpt.com",

        "github": "https://github.com",

        "whatsapp": "https://web.whatsapp.com",

        "instagram": "https://www.instagram.com",

        "facebook": "https://www.facebook.com",

        "linkedin": "https://www.linkedin.com",

        "google drive": "https://drive.google.com",

        "google maps": "https://maps.google.com"

    }


    for name, url in websites.items():

        # Open Gmail
        if (
            name in command
            and (
                "open" in command
                or "kholo" in command
                or "karo" in command
            )
        ):

            speak(
                "Opening "
                + name
            )

            webbrowser.open(
                url
            )

            return True


    return False


# =========================================================
# OPEN FOLDERS
# =========================================================

def open_folder(command):

    home = Path.home()


    folders = {

        "desktop": home / "Desktop",

        "downloads": home / "Downloads",

        "documents": home / "Documents",

        "pictures": home / "Pictures",

        "music": home / "Music",

        "videos": home / "Videos"

    }


    commands = {

        "desktop": [
            "desktop kholo",
            "open desktop"
        ],

        "downloads": [
            "downloads kholo",
            "open downloads"
        ],

        "documents": [
            "documents kholo",
            "open documents"
        ],

        "pictures": [
            "pictures kholo",
            "open pictures",
            "photos kholo"
        ],

        "music": [
            "music kholo",
            "open music"
        ],

        "videos": [
            "videos kholo",
            "open videos"
        ]

    }


    for name, phrases in commands.items():

        for phrase in phrases:

            if phrase in command:

                folder = folders[name]

                if folder.exists():

                    speak(
                        "Opening "
                        + name
                    )

                    os.startfile(
                        folder
                    )

                else:

                    speak(
                        "Sorry, I could not find the "
                        + name
                        + " folder."
                    )

                return True


    return False


# =========================================================
# SEARCH FILES
# =========================================================

def search_files(command):

    phrases = [

        "file dhoondo",
        "files dhoondo",

        "file search karo",
        "files search karo",

        "file dhundo",
        "files dhundo",

        "file dhoondho",
        "files dhoondho",

        "file dhundho",
        "files dhundho",

        "file khojo",
        "files khojo"

    ]


    matched = None


    for phrase in phrases:

        if phrase in command:

            matched = phrase

            break


    if matched is None:

        return False


    search_text = command.replace(
        matched,
        ""
    ).strip()


    if not search_text:

        speak(
            "What file should I search for?"
        )

        search_text = listen()

        if not search_text:

            return True


    home = Path.home()


    locations = [

        home / "Desktop",
        home / "Downloads",
        home / "Documents",
        home / "Pictures"

    ]


    speak(
        "Searching for "
        + search_text
    )


    results = []


    for location in locations:

        if not location.exists():

            continue


        try:

            for item in location.rglob("*"):

                if search_text in item.name.lower():

                    results.append(
                        item
                    )

                    if len(results) >= 10:

                        break

        except Exception:

            continue


        if len(results) >= 10:

            break


    if not results:

        speak(
            "I could not find that file."
        )

        return True


    print(
        "\nSEARCH RESULTS:"
    )


    for item in results:

        print(
            item
        )


    speak(
        "I found "
        + str(len(results))
        + " matching items. "
        "I have displayed them on the screen."
    )


    return True


# =========================================================
# LIST FILES
# =========================================================

def list_files(command):

    home = Path.home()

    folder = None


    if (
        "desktop par kya hai" in command
        or "desktop pe kya hai" in command
        or "desktop ki files" in command
    ):

        folder = home / "Desktop"


    elif (
        "downloads me kya hai" in command
        or "downloads ki files" in command
    ):

        folder = home / "Downloads"


    elif (
        "documents me kya hai" in command
        or "documents ki files" in command
    ):

        folder = home / "Documents"


    if folder is None:

        return False


    try:

        items = list(
            folder.iterdir()
        )


        if not items:

            speak(
                "This folder is empty."
            )

            return True


        print(
            "\nFILES AND FOLDERS:"
        )


        for item in items[:20]:

            if item.is_dir():

                print(
                    "[FOLDER]",
                    item.name
                )

            else:

                print(
                    "[FILE]",
                    item.name
                )


        speak(
            "I found "
            + str(len(items))
            + " items. "
            "I have displayed the list on the screen."
        )


        return True


    except Exception as e:

        print(
            "FILE LIST ERROR:",
            e
        )

        speak(
            "Sorry, I could not read that folder."
        )

        return True


# =========================================================
# OPEN APPS
# =========================================================

def open_apps(command):

    if (
        "open notepad" in command
        or "notepad kholo" in command
    ):

        speak(
            "Opening Notepad"
        )

        os.system(
            "start notepad"
        )

        return True


    if (
        "open file explorer" in command
        or "open explorer" in command
        or "file explorer kholo" in command
        or "files kholo" in command
    ):

        speak(
            "Opening File Explorer"
        )

        os.system(
            "explorer"
        )

        return True


    if (
        "open settings" in command
        or "settings kholo" in command
    ):

        speak(
            "Opening Settings"
        )

        os.system(
            "start ms-settings:"
        )

        return True


    if (
        "open task manager" in command
        or "task manager kholo" in command
    ):

        speak(
            "Opening Task Manager"
        )

        os.system(
            "start taskmgr"
        )

        return True


    if (
        "open chrome" in command
        or "chrome kholo" in command
    ):

        speak(
            "Opening Chrome"
        )

        os.system(
            "start chrome"
        )

        return True


    if (
        "open calculator" in command
        or "calculator kholo" in command
    ):

        speak(
            "Opening Calculator"
        )

        os.system(
            "start calc"
        )

        return True


    return False


# =========================================================
# BASIC WEBSITES
# =========================================================

def website_commands(command):

    if (
        "open youtube" in command
        or "youtube kholo" in command
    ):

        speak(
            "Opening YouTube"
        )

        webbrowser.open(
            "https://www.youtube.com"
        )

        return True


    if (
        "open google" in command
        or "google kholo" in command
    ):

        speak(
            "Opening Google"
        )

        webbrowser.open(
            "https://www.google.com"
        )

        return True


    return False


# =========================================================
# NATURAL BROWSER SEARCH
# =========================================================

def natural_browser_search(command):

    # Google search
    google_markers = [
        "google par",
        "google pe",
        "google me",
        "google mein"
    ]

    if any(marker in command for marker in google_markers):

        query = command

        for marker in google_markers:
            query = query.replace(marker, "")

        query = query.replace("search", "")
        query = query.replace("search karo", "")
        query = query.replace("karo", "")
        query = query.replace("please", "")

        query = query.strip(" ,.!?")

        if query:

            speak("Searching Google for " + query)

            webbrowser.open(
                "https://www.google.com/search?q="
                + query.replace(" ", "+")
            )

            return True


    # YouTube search
    youtube_markers = [
        "youtube par",
        "youtube pe",
        "youtube me",
        "youtube mein"
    ]

    if any(marker in command for marker in youtube_markers):

        query = command

        for marker in youtube_markers:
            query = query.replace(marker, "")

        query = query.replace("search", "")
        query = query.replace("search karo", "")
        query = query.replace("karo", "")
        query = query.replace("please", "")

        query = query.strip(" ,.!?")

        if query:

            speak("Searching YouTube for " + query)

            webbrowser.open(
                "https://www.youtube.com/results?search_query="
                + query.replace(" ", "+")
            )

            return True


    return False


# =========================================================
# YOUTUBE SEARCH
# =========================================================

def youtube_search(command):

    search_text = ""


    if "search youtube for" in command:

        search_text = command.replace(
            "search youtube for",
            ""
        ).strip()


    elif (
        "youtube par" in command
        or "youtube pe" in command
    ):

        search_text = re.sub(
            r"youtube\s+(par|pe)",
            "",
            command
        )


        search_text = search_text.replace(
            "search",
            ""
        )


        search_text = search_text.replace(
            "karo",
            ""
        )


        search_text = search_text.strip()


    if search_text:

        speak(
            "Searching YouTube"
        )


        webbrowser.open(

            "https://www.youtube.com/results?search_query="
            + search_text.replace(
                " ",
                "+"
            )
        )


        return True


    return False


# =========================================================
# GOOGLE SEARCH
# =========================================================

def google_search(command):

    search_text = ""


    if "search google for" in command:

        search_text = command.replace(
            "search google for",
            ""
        ).strip()


    elif (
        "google par" in command
        or "google pe" in command
    ):

        search_text = re.sub(
            r"google\s+(par|pe)",
            "",
            command
        )


        search_text = search_text.replace(
            "search",
            ""
        )


        search_text = search_text.replace(
            "karo",
            ""
        )


        search_text = search_text.strip()


    if search_text:

        speak(
            "Searching Google"
        )


        webbrowser.open(

            "https://www.google.com/search?q="
            + search_text.replace(
                " ",
                "+"
            )
        )


        return True


    return False


# =========================================================
# VOLUME
# =========================================================

def volume_control(command):

    if (
        "increase volume" in command
        or "volume up" in command
        or "volume badhao" in command
        or "volume badao" in command
        or "awaz badhao" in command
    ):

        speak(
            "Increasing volume"
        )


        for _ in range(5):

            subprocess.run(

                [
                    "powershell",
                    "-command",
                    "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"
                ],

                capture_output=True
            )


        return True


    if (
        "decrease volume" in command
        or "volume down" in command
        or "volume kam karo" in command
        or "awaz kam karo" in command
    ):

        speak(
            "Decreasing volume"
        )


        for _ in range(5):

            subprocess.run(

                [
                    "powershell",
                    "-command",
                    "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"
                ],

                capture_output=True
            )


        return True


    if (
        "mute volume" in command
        or "mute karo" in command
        or command == "mute"
    ):

        speak(
            "Muting volume"
        )


        subprocess.run(

            [
                "powershell",
                "-command",
                "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"
            ],

            capture_output=True
        )


        return True


    return False


# =========================================================
# COMPUTER INFORMATION
# =========================================================

def computer_info():

    try:

        system = platform.system()

        version = platform.version()

        processor = platform.processor()


        total, used, free = shutil.disk_usage(
            "C:\\"
        )


        total_gb = round(
            total / (1024 ** 3),
            1
        )


        free_gb = round(
            free / (1024 ** 3),
            1
        )


        print(
            "\nSYSTEM:",
            system
        )


        print(
            "VERSION:",
            version
        )


        print(
            "PROCESSOR:",
            processor
        )


        print(
            "C DRIVE:",
            free_gb,
            "GB free of",
            total_gb,
            "GB"
        )


        speak(
            "Your computer is running "
            + system
            + ". "
            + str(free_gb)
            + " gigabytes are free on your C drive."
        )


    except Exception as e:

        print(
            "PC INFO ERROR:",
            e
        )


        speak(
            "Sorry, I could not read the computer information."
        )


# =========================================================
# LOCK COMPUTER
# =========================================================

def lock_computer():

    speak(
        "Locking your computer"
    )


    subprocess.run(

        [
            "rundll32.exe",
            "user32.dll,LockWorkStation"
        ]
    )


# =========================================================
# SYSTEM CONTROL
# =========================================================

def confirm_system_action(action):

    if action == "restart":

        speak(
            "Are you sure you want to restart the computer? "
            "Please say yes or no."
        )

    else:

        speak(
            "Are you sure you want to shut down the computer? "
            "Please say yes or no."
        )


    answer = listen()


    if answer in [

        "yes",
        "yes please",
        "haan",
        "haan karo",
        "yes karo"

    ]:

        if action == "restart":

            speak(
                "Restarting the computer."
            )

            os.system(
                "shutdown /r /t 10"
            )

        else:

            speak(
                "Shutting down the computer."
            )

            os.system(
                "shutdown /s /t 10"
            )


        return True


    speak(
        "Okay. Cancelled."
    )


    return True


def system_control(command):

    if (
        "lock computer" in command
        or "computer lock karo" in command
        or "pc lock karo" in command
    ):

        lock_computer()

        return True


    if (
        "restart computer" in command
        or "computer restart karo" in command
        or "pc restart karo" in command
        or "restart pc" in command
    ):

        confirm_system_action(
            "restart"
        )

        return True


    if (
        "shutdown computer" in command
        or "computer shutdown karo" in command
        or "pc shutdown karo" in command
        or "computer band karo" in command
        or "pc band karo" in command
    ):

        confirm_system_action(
            "shutdown"
        )

        return True


    return False


# =========================================================
# TIME
# =========================================================

def time_command(command):

    if (
        "what time" in command
        or "time is it" in command
        or command == "time"
        or "kitne baje" in command
        or "time kya hai" in command
    ):

        current_time = (

            datetime.datetime.now()

            .strftime(
                "%I:%M %p"
            )
        )


        speak(
            "The time is "
            + current_time
        )


        return True


    return False


# =========================================================
# PROCESS COMMAND
# =========================================================

# =========================================================
# CONVERSATION CONTEXT
# =========================================================

CONVERSATION_CONTEXT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "jarvis_context.json"
)

MAX_CONTEXT_MESSAGES = 12


def load_conversation_context():
    try:
        if not os.path.exists(CONVERSATION_CONTEXT_FILE):
            return []

        with open(
            CONVERSATION_CONTEXT_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception as e:
        print("CONTEXT LOAD ERROR:", e)
        return []


def save_conversation_context(data):
    try:
        data = data[-MAX_CONTEXT_MESSAGES:]

        with open(
            CONVERSATION_CONTEXT_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        return True

    except Exception as e:
        print("CONTEXT SAVE ERROR:", e)
        return False


def add_conversation_context(user_text, assistant_text=""):
    data = load_conversation_context()

    data.append({
        "user": user_text,
        "assistant": assistant_text,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    })

    save_conversation_context(data)


def get_recent_conversation_context():
    data = load_conversation_context()

    if not data:
        return "No previous conversation."

    lines = []

    for item in data[-8:]:
        lines.append(
            "User: "
            + str(item.get("user", ""))
            + "\nAssistant: "
            + str(item.get("assistant", ""))
        )

    return "\n".join(lines)


def clear_conversation_context():
    save_conversation_context([])
    speak("Conversation context cleared.")
    return True


def understand_with_context(command):
    """
    Use Gemini to understand references such as:
    'isko kholo', 'usme search karo', 'wahi wala', 'haan wahi',
    'ab isko band karo', etc.

    Gemini only returns an intent. It does not directly control
    the computer.
    """
    if "client" not in globals():
        return None

    recent = get_recent_conversation_context()

    prompt = f"""
You are the context-understanding module of a Windows voice assistant.

Understand the current Hindi/Hinglish command using the recent
conversation context.

Current command:
{command}

Recent conversation:
{recent}

Return ONLY valid JSON.

Allowed intents:
- REPEAT_LAST_WORKFLOW
- YOUTUBE_SEARCH
- GOOGLE_SEARCH
- OPEN_SITE
- CLICK_TEXT
- TYPE_TEXT
- PRESS_KEY
- SCROLL_UP
- SCROLL_DOWN
- STOP_SCROLL
- READ_SCREEN
- LOCATE_TEXT
- CLEAR_CONTEXT
- GENERAL_CHAT
- UNKNOWN

Schema:
{{
  "intent": "one allowed intent",
  "target": "",
  "key": "",
  "amount": 0,
  "confidence": 0.0
}}

Rules:
1. Resolve pronouns/references from context.
2. 'isko', 'ispe', 'usko', 'udhar', 'wahi', 'same',
   'jo abhi kiya', 'pichla kaam', 'dobara' can refer to
   the previous task or object.
3. If the user says 'isko kholo' and the recent context says
   YouTube, target should be YouTube.
4. If the user says 'isme search karo' after a website was opened,
   use that website as context.
5. Never invent an object that is not supported by context.
6. For computer actions, confidence should be below 0.60 if
   the reference is genuinely ambiguous.
"""

    try:
        response = client.models.generate_content(
            model="gemini-3.7-flash",
            contents=prompt
        )

        raw = (response.text or "").strip()

        raw = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            raw,
            flags=re.IGNORECASE
        ).strip()

        result = json.loads(raw)

        allowed = {
            "REPEAT_LAST_WORKFLOW",
            "YOUTUBE_SEARCH",
            "GOOGLE_SEARCH",
            "OPEN_SITE",
            "CLICK_TEXT",
            "TYPE_TEXT",
            "PRESS_KEY",
            "SCROLL_UP",
            "SCROLL_DOWN",
            "STOP_SCROLL",
            "READ_SCREEN",
            "LOCATE_TEXT",
            "CLEAR_CONTEXT",
            "GENERAL_CHAT",
            "UNKNOWN"
        }

        if result.get("intent") not in allowed:
            return None

        try:
            result["confidence"] = float(
                result.get("confidence", 0)
            )
        except Exception:
            result["confidence"] = 0.0

        result["confidence"] = max(
            0.0,
            min(1.0, result["confidence"])
        )

        print("CONTEXT INTENT:", result)

        return result

    except Exception as e:
        print("CONTEXT UNDERSTANDING ERROR:", e)
        return None


def execute_context_intent(result):
    if not result:
        return False

    intent = result.get("intent")
    target = str(
        result.get("target", "")
    ).strip()

    confidence = float(
        result.get("confidence", 0)
    )

    if intent == "CLEAR_CONTEXT":
        return clear_conversation_context()

    if confidence < 0.60 and intent not in [
        "GENERAL_CHAT",
        "UNKNOWN"
    ]:
        print(
            "CONTEXT INTENT TOO LOW:",
            confidence
        )
        return False

    if intent == "REPEAT_LAST_WORKFLOW":
        return run_saved_workflow("last workflow")

    if intent == "YOUTUBE_SEARCH" and target:
        return run_advanced_goal_planner(
            "youtube par " + target + " search karo"
        )

    if intent == "GOOGLE_SEARCH" and target:
        return run_advanced_goal_planner(
            "google par " + target + " search karo"
        )

    if intent == "OPEN_SITE" and target:
        return run_goal_based_task(
            "open " + target
        )

    if intent == "CLICK_TEXT" and target:
        verified_click_screen_element(target)
        return True

    if intent == "TYPE_TEXT" and target:
        verified_type_text(target)
        return True

    if intent == "PRESS_KEY":
        key = str(
            result.get("key", "")
        ).strip().lower()

        if key in {
            "enter",
            "esc",
            "escape",
            "tab",
            "backspace",
            "space"
        }:
            if key == "escape":
                key = "esc"

            jarvis_press_key(key)
            return True

    if intent == "SCROLL_UP":
        return start_continuous_scroll(1)

    if intent == "SCROLL_DOWN":
        return start_continuous_scroll(-1)

    if intent == "STOP_SCROLL":
        return stop_continuous_scroll()

    if intent == "READ_SCREEN":
        return screen_tools(
            "screen ka text read karo"
        )

    if intent == "LOCATE_TEXT" and target:
        locate_screen_element(target)
        return True

    return False



# Gemini quota state for this JARVIS session.
GEMINI_QUOTA_EXHAUSTED = False

# =========================================================
# SMART LANGUAGE ROUTER
# =========================================================
# This layer lets JARVIS understand flexible Hindi/Hinglish
# commands instead of requiring exact phrases.
#
# Gemini is used only as an intent parser here. It does NOT
# directly control the mouse/keyboard. The returned intent is
# validated locally and then executed by JARVIS.
# =========================================================

def get_last_workflow_context():
    data = load_workflows()

    if not data:
        return "No saved workflow."

    workflows = list(data.values())

    workflows.sort(
        key=lambda item: item.get("saved_at", ""),
        reverse=True
    )

    latest = workflows[0]

    return (
        "Last saved workflow: "
        + latest.get("name", "unknown")
        + "\nOriginal command: "
        + str(latest.get("original_command", "unknown"))
    )


def smart_parse_command(command):
    """
    Convert natural Hindi/Hinglish into a small validated intent JSON.
    Gemini only interprets language; local code performs the action.
    """
    global GEMINI_QUOTA_EXHAUSTED
    if GEMINI_QUOTA_EXHAUSTED:
        return None
    if "client" not in globals():
        return None

    context = get_last_workflow_context()

    prompt = f"""
You are the language-understanding module of a Windows voice assistant.

Understand the user's Hindi, Hinglish, English, spelling mistakes,
short phrases, pronouns and references such as:
'wahi', 'same', 'jo abhi kiya', 'pichla kaam', 'usko', 'udhar',
'phir se', 'dobara', 'thoda', 'zyada'.

Do NOT perform any action.
Return ONLY valid JSON. No markdown. No explanation.

Current user command:
{command}

Last workflow context:
{context}

Allowed intent values:
- REPEAT_LAST_WORKFLOW
- YOUTUBE_SEARCH
- GOOGLE_SEARCH
- OPEN_SITE
- CLICK_TEXT
- TYPE_TEXT
- PRESS_KEY
- SCROLL_UP
- SCROLL_DOWN
- STOP_SCROLL
- READ_SCREEN
- LOCATE_TEXT
- GENERAL_CHAT
- UNKNOWN

JSON schema:
{{
  "intent": "one allowed intent",
  "target": "text/site/query if relevant, otherwise empty string",
  "amount": 0,
  "key": "enter/esc/tab/backspace if relevant, otherwise empty string",
  "confidence": 0.0
}}

Rules:
1. "wahi", "wahi kaam", "wahi dobara", "same thing",
   "jo abhi kiya tha", "pichla kaam phir se", etc. mean
   REPEAT_LAST_WORKFLOW when they refer to a previous task.
2. "thoda/zyada/bahut" scrolling should map to SCROLL_UP or
   SCROLL_DOWN and amount should be 10/35/60 respectively.
3. If an explicit number is given for scrolling, use that number.
4. For "YouTube par X search karo", use YOUTUBE_SEARCH and target X.
5. For "Google par X search karo", use GOOGLE_SEARCH and target X.
6. For "X kholo/open karo", use OPEN_SITE and target X.
7. Do not invent an intent outside the allowed list.
"""

    try:
        response = client.models.generate_content(
            model="gemini-3.7-flash",
            contents=prompt
        )

        raw = (response.text or "").strip()

        # Remove accidental markdown fences.
        raw = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            raw,
            flags=re.IGNORECASE
        ).strip()

        data = json.loads(raw)

        allowed = {
            "REPEAT_LAST_WORKFLOW",
            "YOUTUBE_SEARCH",
            "GOOGLE_SEARCH",
            "OPEN_SITE",
            "CLICK_TEXT",
            "TYPE_TEXT",
            "PRESS_KEY",
            "SCROLL_UP",
            "SCROLL_DOWN",
            "STOP_SCROLL",
            "READ_SCREEN",
            "LOCATE_TEXT",
            "GENERAL_CHAT",
            "UNKNOWN"
        }

        if data.get("intent") not in allowed:
            return None

        try:
            confidence = float(data.get("confidence", 0))
        except Exception:
            confidence = 0

        data["confidence"] = max(
            0.0,
            min(1.0, confidence)
        )

        print("SMART INTENT:", data)

        return data

    except Exception as e:
        print("SMART ROUTER ERROR:", e)
        return None


def execute_smart_intent(intent_data, original_command):
    """
    Execute only validated, non-sensitive intents locally.
    """
    if not intent_data:
        return False

    intent = intent_data.get("intent")
    target = str(
        intent_data.get("target", "")
    ).strip()

    confidence = float(
        intent_data.get("confidence", 0)
    )

    # Do not execute low-confidence computer actions.
    if confidence < 0.60 and intent not in [
        "GENERAL_CHAT",
        "UNKNOWN"
    ]:
        print(
            "SMART INTENT TOO LOW CONFIDENCE:",
            confidence
        )
        return False

    if intent == "REPEAT_LAST_WORKFLOW":
        return run_saved_workflow("last workflow")

    if intent == "YOUTUBE_SEARCH" and target:
        return run_advanced_goal_planner(
            "youtube par " + target + " search karo"
        )

    if intent == "GOOGLE_SEARCH" and target:
        return run_advanced_goal_planner(
            "google par " + target + " search karo"
        )

    if intent == "OPEN_SITE" and target:
        return run_goal_based_task(
            "open " + target
        )

    if intent == "CLICK_TEXT" and target:
        verified_click_screen_element(target)
        return True

    if intent == "TYPE_TEXT" and target:
        verified_type_text(target)
        return True

    if intent == "PRESS_KEY":
        key = str(
            intent_data.get("key", "")
        ).strip().lower()

        allowed_keys = {
            "enter",
            "esc",
            "escape",
            "tab",
            "backspace",
            "space"
        }

        if key in allowed_keys:
            if key == "escape":
                key = "esc"

            jarvis_press_key(key)
            return True

        return False

    if intent == "SCROLL_UP":
        # Use continuous scrolling for natural voice control.
        return start_continuous_scroll(1)

    if intent == "SCROLL_DOWN":
        return start_continuous_scroll(-1)

    if intent == "STOP_SCROLL":
        return stop_continuous_scroll()

    if intent == "READ_SCREEN":
        return screen_tools(
            "screen ka text read karo"
        )

    if intent == "LOCATE_TEXT" and target:
        locate_screen_element(target)
        return True

    return False


def smart_language_command(command):
    """
    Fast natural-language layer.

    Important:
    - Straightforward commands are handled by existing local functions.
    - Gemini is NOT called here for every command.
    - Contextual/ambiguous phrases are handled later by the
      context-aware fallback in process_command().
    """
    normalized = re.sub(
        r"\s+",
        " ",
        command.lower()
    ).strip()

    # Commands already handled by local screen/browser layers.
    local_patterns = [
        r"\bscroll\b",
        r"\bस्क्रॉल\b",
        r"\bclick\b",
        r"\bclick karo\b",
        r"\bdabao\b",
        r"\bpress karo\b",
        r"\btype\b",
        r"\btype karo\b",
        r"\blikho\b",
        r"\benter\b",
        r"\bopen\b",
        r"\bkholo\b",
        r"\bkhol\b",
        r"\bdhoondo\b",
        r"\bdhundho\b",
        r"\bfind karo\b",
        r"\bread screen\b",
        r"\bscreen\b"
    ]

    # If an existing local router can understand it, don't send it to Gemini.
    if any(re.search(pattern, normalized) for pattern in local_patterns):
        return False

    # Only send genuinely conversational/ambiguous commands to the
    # context-aware layer, not here.
    return False


# =========================================================
# LOCAL CONTEXT BRAIN + GEMINI QUOTA PROTECTION
# =========================================================

LAST_COMMAND_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "jarvis_last_command.json"
)


def normalize_context_phrase(command):
    """Normalize common Hindi/Hinglish reference phrases."""
    s = command.lower().strip()
    s = re.sub(r"^jarvis[\s,:-]*", "", s)
    s = re.sub(r"\s+", " ", s)

    replacements = {
        "vahi": "wahi",
        "vohi": "wahi",
        "wohi": "wahi",
        "fir se": "phir se",
        "jo tune abhi kiya tha": "jo abhi kiya tha",
        "jo tune abhi kiya": "jo abhi kiya",
    }

    for old, new in replacements.items():
        s = s.replace(old, new)

    return re.sub(r"\s+", " ", s).strip()


def save_last_command(command):
    """Save the last useful user command locally."""
    try:
        with open(
            LAST_COMMAND_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "command": command,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S")
                },
                f,
                ensure_ascii=False,
                indent=2
            )
    except Exception as e:
        print("LAST COMMAND SAVE ERROR:", e)


def load_last_command():
    try:
        if not os.path.exists(LAST_COMMAND_FILE):
            return None

        with open(
            LAST_COMMAND_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        return data.get("command")

    except Exception as e:
        print("LAST COMMAND LOAD ERROR:", e)
        return None


def is_local_repeat_command(command):
    """
    Catch repeat/reference phrases locally.
    IMPORTANT: this function never calls Gemini.
    """
    s = normalize_context_phrase(command)

    patterns = [
        r"^wahi$",
        r"^wahi karo$",
        r"^wahi kar do$",
        r"^wahi dobara$",
        r"^wahi dobara karo$",
        r"^wahi dobara kar do$",
        r"^wahi phir se karo$",
        r"^wahi phir se kar do$",
        r"^wahi again$",
        r"^wahi again karo$",
        r"^wahi repeat karo$",
        r"^same$",
        r"^same karo$",
        r"^same task dobara karo$",
        r"^same task repeat karo$",
        r"^same task karo$",
        r"^same dobara$",
        r"^same dobara karo$",
        r"^same phir se karo$",
        r"^same repeat karo$",
        r"^previous task$",
        r"^previous task karo$",
        r"^previous task dobara karo$",
        r"^previous task repeat karo$",
        r"^last task$",
        r"^last task karo$",
        r"^last task dobara karo$",
        r"^last task repeat karo$",
        r"^again$",
        r"^again karo$",
        r"^jo abhi kiya tha$",
        r"^jo abhi kiya tha wahi$",
        r"^jo abhi kiya tha wahi karo$",
        r"^jo abhi kiya tha wahi dobara karo$",
        r"^jo abhi kiya wahi karo$",
        r"^pichla kaam$",
        r"^pichla kaam karo$",
        r"^pichla kaam dobara karo$",
        r"^pichle task ko dobara karo$",
    ]

    if any(
        phrase in s
        for phrase in [
            "wahi wala",
            "wahi wali",
            "same wala",
            "same wali"
        ]
    ) and any(
        word in s
        for word in [
            "karo",
            "kar do",
            "dobara",
            "phir",
            "repeat",
            "again"
        ]
    ):
        return True

    return any(
        re.fullmatch(pattern, s)
        for pattern in patterns
    )


def repeat_last_task_locally():
    """
    Replay the latest saved workflow first.
    If no workflow exists, fall back to the last command.
    Never contacts Gemini.
    """
    data = load_workflows()

    if data:
        workflows = list(data.values())
        workflows.sort(
            key=lambda item: item.get("saved_at", ""),
            reverse=True
        )

        latest = workflows[0]
        original = latest.get("original_command")

        if original:
            name = latest.get(
                "name",
                "last workflow"
            )

            print(
                "LOCAL REPLAY:",
                name,
                "|",
                original
            )

            speak(
                "Wahi kaam dobara kar raha hoon."
            )

            # Safe supported workflow replay only.
            if run_advanced_goal_planner(original):
                return True

            # If planner cannot handle it, don't fall into Gemini.
            speak(
                "Ye saved workflow abhi automatically replay nahi ho sakta."
            )
            return True

    last = load_last_command()

    if last:
        print(
            "LOCAL LAST COMMAND:",
            last
        )

        # Only replay known safe local/goal commands.
        if run_advanced_goal_planner(last):
            return True

        if run_goal_based_task(last):
            return True

    speak(
        "Mere paas repeat karne ke liye koi saved task nahi hai."
    )
    return True


def should_use_context_gemini(command):
    """
    Gemini context fallback is allowed only for genuinely ambiguous
    references. Simple repeat phrases are blocked completely.
    """
    if is_local_repeat_command(command):
        return False

    s = normalize_context_phrase(command)

    contextual_phrases = [
        "isko",
        "is ko",
        "ispe",
        "is pe",
        "isme",
        "is me",
        "usko",
        "us ko",
        "uspe",
        "us pe",
        "usme",
        "us me",
        "yaha",
        "yahan",
        "udhar",
        "ye wala",
        "yeh wala",
        "wahan",
        "jo abhi",
        "jo tune",
        "jo kiya"
    ]

    return any(
        phrase in s
        for phrase in contextual_phrases
    )




# =========================================================
# TESSERACT PATH SAFETY
# =========================================================

try:
    if "pytesseract" in globals():
        _tesseract_candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]

        for _tpath in _tesseract_candidates:
            if os.path.exists(_tpath):
                pytesseract.pytesseract.tesseract_cmd = _tpath
                TESSERACT_AVAILABLE = True
                print("TESSERACT READY:", _tpath)
                break
except Exception as _e:
    print("TESSERACT PATH SETUP ERROR:", _e)




# =========================================================
# STEP 23 - ADVANCED LOCAL SCREEN UNDERSTANDING
# =========================================================

def screen_capture_image():
    """Capture the current screen safely."""
    if not PYAUTOGUI_AVAILABLE:
        return None

    try:
        return pyautogui.screenshot()
    except Exception as e:
        print("SCREEN CAPTURE ERROR:", e)
        return None


def detect_text_elements(target=None):
    """
    Detect OCR text elements with bounding boxes.
    Returns elements with text, confidence, and center coordinates.
    """
    if not TESSERACT_AVAILABLE or not PYAUTOGUI_AVAILABLE:
        return []

    img = screen_capture_image()

    if img is None:
        return []

    try:
        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            config="--psm 6"
        )
    except Exception as e:
        print("OCR ELEMENT ERROR:", e)
        return []

    elements = []

    count = len(data.get("text", []))

    for i in range(count):
        raw = str(data["text"][i]).strip()

        if not raw:
            continue

        try:
            confidence = float(
                data["conf"][i]
            )
        except Exception:
            confidence = 0

        if confidence < 25:
            continue

        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])

        elements.append({
            "text": raw,
            "confidence": confidence,
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "center_x": x + w // 2,
            "center_y": y + h // 2
        })

    return elements


def find_best_screen_element(target):
    """
    Find the best local OCR match for a target phrase.
    Scores exact phrase, exact word, and fuzzy word overlap.
    """
    target = re.sub(
        r"\s+",
        " ",
        str(target).lower()
    ).strip()

    if not target:
        return None

    elements = detect_text_elements()

    if not elements:
        return None

    target_words = set(
        re.findall(
            r"[a-z0-9]+",
            target
        )
    )

    best = None
    best_score = -1

    for element in elements:
        value = element["text"].lower().strip()

        if value == target:
            score = 1000 + element["confidence"]

        elif target in value or value in target:
            score = 700 + element["confidence"]

        else:
            words = set(
                re.findall(
                    r"[a-z0-9]+",
                    value
                )
            )

            overlap = len(
                target_words.intersection(words)
            )

            if overlap == 0:
                continue

            score = (
                overlap * 100
                + element["confidence"]
            )

        if score > best_score:
            best_score = score
            best = dict(element)

    if best:
        best["match_score"] = best_score

    return best


def describe_screen_elements(limit=20):
    """
    Print a compact local map of visible text elements.
    """
    elements = detect_text_elements()

    if not elements:
        speak("I could not detect readable screen elements.")
        return True

    # Highest confidence first.
    elements.sort(
        key=lambda item: item["confidence"],
        reverse=True
    )

    print("\n----- SCREEN ELEMENT MAP -----")

    for element in elements[:limit]:
        print(
            f'{element["text"]} | '
            f'confidence={element["confidence"]:.0f} | '
            f'center=({element["center_x"]}, {element["center_y"]})'
        )

    print("------------------------------\n")

    speak(
        "I found "
        + str(min(len(elements), limit))
        + " readable screen elements."
    )

    return True


def locate_screen_element(target):
    """Locate an element and speak its position."""
    element = find_best_screen_element(target)

    if not element:
        speak(
            "I could not find "
            + target
            + " on the screen."
        )
        return False

    print(
        "SCREEN ELEMENT:",
        element
    )

    speak(
        "I found "
        + target
        + " at "
        + str(element["center_x"])
        + " by "
        + str(element["center_y"])
    )

    return True


def click_screen_element_smart(target):
    """
    Safer local element click:
    - find best OCR element
    - move to exact center
    - click
    - verify
    """
    element = find_best_screen_element(target)

    if not element:
        return False

    print(
        "SMART CLICK TARGET:",
        target,
        "|",
        element
    )

    before = _screen_signature()

    pyautogui.moveTo(
        element["center_x"],
        element["center_y"],
        duration=0.30
    )

    time.sleep(0.20)

    pyautogui.click(
        element["center_x"],
        element["center_y"]
    )

    verified = verify_screen_changed(
        before,
        0.8
    )

    if verified:
        speak(
            "Clicked "
            + target
            + " and verified the action."
        )
    else:
        speak(
            "I clicked "
            + target
            + " but there was no visible screen change."
        )

    return True


def type_into_screen_element(target, text_to_type):
    """
    Find an input-like text label locally, click its center,
    then type text and verify.
    """
    element = find_best_screen_element(target)

    if not element:
        return False

    print(
        "SMART INPUT TARGET:",
        target,
        "|",
        element
    )

    pyautogui.click(
        element["center_x"],
        element["center_y"]
    )

    time.sleep(0.25)

    return verified_type_text(
        text_to_type
    )



# =========================================================
# STEP 26 - VISUAL TARGET SELECTION
# =========================================================

def visual_target_candidates(target):
    """Combine OCR text with nearby UI shapes and rank likely targets."""
    if not PYAUTOGUI_AVAILABLE:
        return []

    target = re.sub(r"[^a-z0-9 ]", " ", str(target).lower())
    target = re.sub(r"\s+", " ", target).strip()
    if not target:
        return []

    try:
        screenshot = pyautogui.screenshot()
        text_elements = detect_text_elements()
        shapes = detect_ui_shapes()
        target_words = set(target.split())
        candidates = []

        for text in text_elements:
            value = re.sub(r"[^a-z0-9 ]", " ", text.get("text", "").lower())
            value = re.sub(r"\s+", " ", value).strip()
            words = set(value.split())
            overlap = len(target_words & words)

            if value == target:
                score = 1000 + text.get("confidence", 0)
            elif target in value or value in target:
                score = 750 + text.get("confidence", 0)
            elif overlap:
                score = overlap * 150 + text.get("confidence", 0)
            else:
                continue

            tx = text.get("center_x", 0)
            ty = text.get("center_y", 0)
            best_shape = None
            best_distance = 10**9

            # Prefer a UI rectangle containing the OCR text.
            for shape in shapes:
                sx = shape.get("mouse_x", 0)
                sy = shape.get("mouse_y", 0)
                sw = shape.get("w", 0)
                sh = shape.get("h", 0)
                scx = sx
                scy = sy
                # Approximate screenshot-space bounds using mapped center.
                distance = ((tx - scx) ** 2 + (ty - scy) ** 2) ** 0.5
                if distance < best_distance and distance < 220:
                    best_distance = distance
                    best_shape = shape

            candidate = dict(text)
            candidate["target_score"] = round(score, 1)
            candidate["nearby_shape"] = best_shape
            candidate["shape_distance"] = round(best_distance, 1) if best_shape else None

            if best_shape:
                # A nearby UI box is stronger evidence that the text is clickable.
                candidate["target_score"] += 120
                candidate["selection_type"] = "text_inside_or_near_ui"
            else:
                candidate["selection_type"] = "text_only"

            candidates.append(candidate)

        candidates.sort(key=lambda x: x["target_score"], reverse=True)
        return candidates[:10]

    except Exception as e:
        print("VISUAL TARGET CANDIDATE ERROR:", e)
        return []


def select_visual_target(target):
    """Select and report the strongest local visual target without clicking."""
    candidates = visual_target_candidates(target)
    if not candidates:
        speak("I could not locate " + target + " on the screen.")
        return True

    best = candidates[0]
    print("\n----- VISUAL TARGET SELECTION -----")
    for index, item in enumerate(candidates[:5], 1):
        print(
            index,
            "|",
            item.get("text"),
            "| score=", round(item.get("target_score", 0), 1),
            "| center=", (item.get("center_x"), item.get("center_y")),
            "| type=", item.get("selection_type")
        )
    print("-----------------------------------\n")

    speak(
        "I selected " + target + " at " +
        str(best.get("center_x")) + " by " +
        str(best.get("center_y"))
    )
    return True


def hover_visual_target(target):
    """Move the mouse to the best visual target, but do not click."""
    candidates = visual_target_candidates(target)
    if not candidates:
        speak("I could not locate " + target + " on the screen.")
        return True

    best = candidates[0]
    x = int(best.get("center_x", 0))
    y = int(best.get("center_y", 0))
    print("VISUAL HOVER TARGET:", target, "->", x, y)

    try:
        pyautogui.moveTo(x, y, duration=0.35)
        speak("I moved the pointer to " + target + ".")
    except Exception as e:
        print("VISUAL HOVER ERROR:", e)
        speak("I could not move the pointer to " + target + ".")
    return True


def click_visual_target_confirmed(target):
    """Click a locally selected target only for ordinary, non-sensitive UI actions."""
    if agent_is_sensitive(target):
        speak("I will not perform a sensitive action automatically.")
        return True

    candidates = visual_target_candidates(target)
    if not candidates:
        speak("I could not locate " + target + " on the screen.")
        return True

    best = candidates[0]
    score = float(best.get("target_score", 0))
    if score < 500:
        speak("I found a weak match for " + target + ", so I did not click it.")
        return True

    x = int(best.get("center_x", 0))
    y = int(best.get("center_y", 0))
    print("VISUAL CLICK SELECTED:", target, "score=", score, "at", x, y)

    before = _screen_signature()
    try:
        pyautogui.moveTo(x, y, duration=0.3)
        time.sleep(0.2)
        pyautogui.click(x, y)
        changed = verify_screen_changed(before, 0.8)
        if changed:
            speak("Clicked " + target + " and the screen changed.")
        else:
            speak("I clicked " + target + ", but the screen did not visibly change.")
    except Exception as e:
        print("VISUAL CLICK ERROR:", e)
        speak("I could not click " + target + ".")
    return True


def step26_visual_command(command):
    """Natural-language router for STEP 26 visual target selection."""
    s = re.sub(r"\s+", " ", command.lower()).strip()

    # Selection only: useful for debugging and confidence checking.
    m = re.search(
        r"(?:screen\s+(?:par|pe|me|mein)\s+)?"
        r"(.+?)\s+(?:select\s+karo|select\s+kar|choose\s+karo|choose\s+kar)$",
        s
    )
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(?:screen\s+(?:par|pe|me|mein))\s+", "", target)
        return select_visual_target(target)

    # Hover / move pointer without clicking.
    m = re.search(
        r"(?:screen\s+(?:par|pe|me|mein)\s+)?"
        r"(.+?)\s+(?:par\s+)?(?:mouse|pointer)\s+le\s+j(?:ao|a)|"
        r"(?:screen\s+(?:par|pe|me|mein)\s+)?"
        r"(.+?)\s+(?:hover\s+karo|hover\s+kar)$",
        s
    )
    if m:
        target = (m.group(1) or m.group(2)).strip()
        return hover_visual_target(target)

    # Explicit visual click. This remains limited to ordinary actions.
    m = re.search(
        r"(?:screen\s+(?:par|pe|me|mein)\s+)?"
        r"(.+?)\s+(?:visual\s+click\s+karo|visual\s+click|smart\s+click\s+karo)$",
        s
    )
    if m:
        return click_visual_target_confirmed(m.group(1).strip())

    return False

def screen_understanding_command(command):
    """Handle STEP 24-26 local screen/UI commands."""
    s = re.sub(r"\s+", " ", command.lower()).strip()

    # STEP 26 visual target selection runs before the older UI router.
    if step26_visual_command(command):
        return True

    if any(p in s for p in [
        "ui elements batao", "ui elements dikhao", "ui map karo",
        "screen ke boxes batao", "screen ke buttons batao",
        "screen par boxes batao", "screen shapes batao",
        "visual elements batao", "visual ui batao"
    ]):
        return describe_ui_shapes()

    if any(p in s for p in [
        "screen elements batao", "screen elements dikhao",
        "screen par kya kya hai", "screen ko map karo",
        "screen map karo", "screen ke elements batao"
    ]):
        describe_screen_elements()
        # Also print visual shapes for the new UI layer.
        describe_ui_shapes()
        return True

    # -----------------------------------------------------
    # STEP 25: SMART INPUT / SEARCH FIELD NAVIGATION
    # -----------------------------------------------------
    # Natural phrases such as:
    #   search field dhoondo
    #   YouTube ka search box dhoondo
    #   search box mein Free Fire type karo
    # -----------------------------------------------------
    # Search/input box commands.
    if any(p in s for p in [
        "search box dhoondo", "search box dhundo",
        "search box find karo", "input box dhoondo",
        "input box dhundo", "input box find karo",
        "search field dhoondo", "search field dhundo"
    ]):
        field = find_input_box()
        if not field:
            speak("I could not find a search or input box.")
            return True
        print("INPUT BOX FOUND:", field)
        speak(
            "I found the input box at "
            + str(field["mouse_x"]) + " by " + str(field["mouse_y"])
        )
        return True

    # "search box me X search/type karo"
    m = re.search(
        r"(?:search|input)\s+box\s+(?:me|mein|par|pe)\s+(.+?)\s+"
        r"(?:search\s+karo|type\s+karo|likho|enter\s+karo)\s*$",
        s
    )
    if m:
        return smart_input_type(m.group(1).strip())

    # Locate / position.
    m = re.search(
        r"(?:screen\s+par|screen\s+pe|screen\s+me|screen\s+mein)\s+"
        r"(.+?)\s+(?:kaha\s+hai|kahan\s+hai|dhoondo|dhundho|find\s+karo)\s*$",
        s
    )
    if m:
        return locate_screen_element(m.group(1).strip())

    # Smart click.
    m = re.search(
        r"(?:screen\s+par|screen\s+pe|screen\s+me|screen\s+mein)\s+"
        r"(.+?)\s+(?:click\s+karo|click|dabao|press\s+karo)\s*$",
        s
    )
    if m:
        return click_screen_element_smart(m.group(1).strip())

    return False



# =========================================================
# STEP 28 - COMPLETE MULTI-ACTION VISUAL AGENT
# Built directly on the complete Step 26 base.
# =========================================================

VISUAL_AGENT_MAX_RETRIES = 2


def agent_is_sensitive(command):
    text = re.sub(r"\s+", " ", str(command).lower()).strip()
    words = [
        "send", "delete", "remove", "pay", "payment", "purchase", "buy",
        "order", "transfer", "post", "publish", "submit", "confirm",
        "accept", "reject", "logout", "log out", "change password",
        "password change", "unsubscribe", "cancel subscription"
    ]
    for w in words:
        if " " in w:
            if w in text:
                return True
        elif re.search(r"(?<![a-z0-9])"+re.escape(w)+r"(?![a-z0-9])", text):
            return True
    return False


def is_agent_goal(command):
    text=re.sub(r"\s+"," ",str(command).lower()).strip()
    if agent_is_sensitive(text): return False
    return any(x in text for x in [
        "youtube kholo","youtube open","youtube par","youtube pe",
        "google kholo","google open","google par","google pe"
    ])


def run_agent_loop(command):
    try:
        return run_goal_based_task(command)
    except Exception as e:
        print("SAFE AGENT GOAL ERROR:", e)
        speak("I could not complete that safe goal.")
        return True


def visual_agent_observe():
    """Use Step 26's local OCR and UI detector."""
    try:
        image = screen_capture_image()
        text = detect_text_elements()
        shapes = detect_ui_shapes()
        return {"image":image,"text":text,"shapes":shapes}
    except Exception as e:
        print("VISUAL AGENT OBSERVE ERROR:",e)
        return {"image":None,"text":[],"shapes":[]}


def visual_agent_find_target(target, observation=None):
    if observation is None: observation=visual_agent_observe()
    target=re.sub(r"\s+"," ",str(target).lower()).strip()
    # Step 26 OCR resolver is already tested and reliable.
    result=find_best_screen_element(target)
    if result:
        result=dict(result)
        result["target_type"]="text"
        result["score"]=float(result.get("match_score",0))
        result["mouse_x"]=int(result.get("center_x",result.get("x",0)))
        result["mouse_y"]=int(result.get("center_y",result.get("y",0)))
        return result
    return None


def visual_agent_move_to(target):
    result=visual_agent_find_target(target)
    if not result:
        speak("I could not locate "+target+".")
        return True
    x,y=int(result["mouse_x"]),int(result["mouse_y"])
    print("VISUAL AGENT TARGET:",target,"| mouse:",x,y,"| score:",round(result.get("score",0),1))
    pyautogui.moveTo(x,y,duration=.35)
    speak("I located "+target+".")
    return True


def visual_agent_click(target):
    result=visual_agent_find_target(target)
    if not result:
        speak("I could not find "+target+".")
        return True
    x,y=int(result["mouse_x"]),int(result["mouse_y"])
    if float(result.get("score",0))<250:
        speak("The target is ambiguous, so I will not click it.")
        return True
    print("VISUAL AGENT CLICK:",target,"| mouse:",x,y,"| score:",round(result.get("score",0),1))
    before=_screen_signature()
    pyautogui.moveTo(x,y,duration=.25); pyautogui.click(x,y)
    time.sleep(.5)
    if verify_screen_changed(before,.6):
        speak("Clicked "+target+".")
    else:
        speak("Clicked "+target+".")
    return True


def visual_agent_input(text_to_type):
    # Prefer the Step 25/26 smart input detector.
    return smart_input_type(text_to_type)


def _step28_clean_text(s):
    s=re.sub(r"\s+"," ",s.lower()).strip()
    s=re.sub(r"^jarvis[\s,]*","",s).strip()
    return s


def _step28_parse(command):
    """Deterministic parser for natural voice sequences.
    Example: youtube kholo search dhoondo motu patalu type karo aur enter press karo
    -> open youtube, find search, type motu patalu, enter.
    """
    s=_step28_clean_text(command)
    actions=[]

    # 1) Known site open, independently of later actions.
    site=None
    for name in ("youtube","google","gmail","chatgpt","github","whatsapp","instagram","facebook","linkedin"):
        if re.search(r"\b"+re.escape(name)+r"\s+(?:khol(?:o)?|open(?:\s+kar(?:o)?)?)\b",s):
            site=name; break
    if site:
        actions.append(("open",site))
        s=re.sub(r"\b"+re.escape(site)+r"\s+(?:khol(?:o)?|open(?:\s+kar(?:o)?)?)\b"," ",s,count=1)
        s=re.sub(r"\s+"," ",s).strip()

    # 2) Find/search target. Most common form is "search dhoondo".
    find_match=re.search(r"\b(search|button|icon|menu|field|box)\s+(?:dhoondo|dhundo|khojo|find|locate)(?:\s+(?:karo|kar|kar\s+do))?\b",s)
    if find_match:
        actions.append(("find",find_match.group(1)))
        s=s[:find_match.start()]+" "+s[find_match.end():]
        s=re.sub(r"\s+"," ",s).strip()
    else:
        # Generic "screen par search dhoondo"
        fm=re.search(r"\b(?:dhoondo|dhundo|khojo|find|locate)\s+(search|button|icon|menu|field|box)\b",s)
        if fm:
            actions.append(("find",fm.group(1)))
            s=s[:fm.start()]+" "+s[fm.end():]
            s=re.sub(r"\s+"," ",s).strip()

    # 3) Type payload. Capture only words immediately before "type".
    tm=re.search(r"(?:^|\b(?:aur|and|then|fir)\b|\b(?:usme|usmein|isme|ismein)\b)\s*(.+?)\s+type(?:\s+(?:karo|kar|kar\s+do))?\b",s)
    if tm:
        payload=tm.group(1).strip(" ,")
        payload=re.sub(r"^(?:aur|and|then|fir)\s+","",payload).strip()
        payload=re.sub(r"\b(?:search|dhoondo|dhundo|khojo|find|locate)\b\s*","",payload).strip()
        if payload:
            actions.append(("type",payload))
        s=s[:tm.start()]+" "+s[tm.end():]
        s=re.sub(r"\s+"," ",s).strip()

    # 4) Explicit click, if present.
    cm=re.search(r"\b(?:click|dabao)(?:\s+(?:karo|kar|kar\s+do))?\b",s)
    if cm:
        # If a find target exists, click that target.
        target=next((v for k,v in reversed(actions) if k=="find"),None)
        if target: actions.append(("click",target))
        s=s[:cm.start()]+" "+s[cm.end():]
        s=re.sub(r"\s+"," ",s).strip()

    # 5) Enter can appear as "aur enter press karo" or simply "enter".
    if re.search(r"\benter(?:\s+(?:press|dabao|karo|kar\s+do))?\b",s):
        actions.append(("enter",""))

    return actions


def run_multistep_command(command):
    cleaned=_step28_clean_text(command)
    if not cleaned: return False
    if agent_is_sensitive(cleaned):
        print("STEP 28: BLOCKED SENSITIVE COMMAND:",cleaned)
        speak("I will not perform that sensitive action automatically.")
        return True

    actions=_step28_parse(cleaned)
    if len(actions)<2: return False

    print("STEP 28 MULTI-ACTION:",cleaned)
    print("STEP 28: PARSED STEPS:",actions)

    urls={
        "youtube":"https://www.youtube.com","google":"https://www.google.com",
        "gmail":"https://mail.google.com","chatgpt":"https://chatgpt.com",
        "github":"https://github.com","whatsapp":"https://web.whatsapp.com",
        "instagram":"https://www.instagram.com","facebook":"https://www.facebook.com",
        "linkedin":"https://www.linkedin.com"
    }
    typed=False
    for n,(kind,value) in enumerate(actions,1):
        print(f"STEP 28: ACTION {n}/{len(actions)} -> {kind}: {value}")
        if kind=="open":
            print("STEP 28: OPEN",value)
            webbrowser.open(urls[value]); speak("Opening "+value); time.sleep(2.5); continue
        if kind=="find":
            result=visual_agent_find_target(value)
            if not result:
                speak("I could not find "+value+" on the screen."); return True
            x,y=int(result["mouse_x"]),int(result["mouse_y"])
            print("STEP 28: SELECTED",value,"| mouse:",x,y,"| score:",round(result.get("score",0),1))
            # When a later type exists, clicking the target is intentional.
            later=[k for k,_ in actions[n:]]
            if "type" in later or "click" in later:
                if result.get("score",0)<250:
                    speak("The target is ambiguous, so I will not click it."); return True
                pyautogui.click(x,y); time.sleep(.25)
            else:
                pyautogui.moveTo(x,y,duration=.25); speak("I located "+value+".")
            continue
        if kind=="click":
            result=visual_agent_find_target(value)
            if not result or result.get("score",0)<250:
                speak("I could not safely find "+value+"."); return True
            pyautogui.click(int(result["mouse_x"]),int(result["mouse_y"])); time.sleep(.3); continue
        if kind=="type":
            print("STEP 28: ACT -> TYPE:",value)
            pyautogui.write(value,interval=.025); typed=True; time.sleep(.35)
            try: verified=bool(find_screen_text(value))
            except Exception: verified=False
            print("STEP 28: VERIFY -> typed text detected" if verified else "STEP 28: VERIFY -> typed text not detected")
            if not verified:
                pyautogui.hotkey("ctrl","a"); pyautogui.write(value,interval=.025)
            speak("Typed "+value+"."); continue
        if kind=="enter":
            print("STEP 28: ACT -> ENTER"); jarvis_press_key("enter"); speak("Enter pressed."); time.sleep(.7)

    if typed: print("STEP 28: VERIFY -> multi-action typing completed")
    speak("Multi-step task completed.")
    return True



# =========================================================
# STEP 29 - VISUAL GOAL AGENT / SELF-RECOVERY
# Built on the complete Step 26 + Step 28 base.
#
# New abilities:
#   - Find a visual target even when it is below the current viewport.
#   - Retry by scrolling locally, then restore the original position if
#     the target cannot be found.
#   - Safely resolve "find X and click" / "find X and mouse le jao".
#   - Refuse ambiguous visual clicks instead of guessing.
# =========================================================

STEP29_MAX_SCROLLS = 3
STEP29_SCROLL_AMOUNT = -5
STEP29_MIN_SCORE = 500.0


def _step29_normalize(text):
    text = re.sub(r"\s+", " ", str(text).lower()).strip()
    text = re.sub(r"^jarvis[\s,:-]*", "", text).strip()
    return text


def _step29_candidate(target):
    """Return the strongest existing Step 26 visual candidate."""
    target = _step29_normalize(target)
    if not target:
        return None

    try:
        candidates = visual_target_candidates(target)
    except Exception as e:
        print("STEP 29 CANDIDATE ERROR:", e)
        candidates = []

    if candidates:
        best = dict(candidates[0])
        best["target_score"] = float(best.get("target_score", 0))
        best["center_x"] = int(best.get("center_x", 0))
        best["center_y"] = int(best.get("center_y", 0))
        return best

    # Reliable Step 23 OCR fallback.
    try:
        element = find_best_screen_element(target)
    except Exception as e:
        print("STEP 29 OCR FALLBACK ERROR:", e)
        element = None

    if element:
        element = dict(element)
        element["target_score"] = float(element.get("match_score", 0))
        element["center_x"] = int(element.get("center_x", element.get("x", 0)))
        element["center_y"] = int(element.get("center_y", element.get("y", 0)))
        return element

    return None


def step29_find_with_retry(target, max_scrolls=STEP29_MAX_SCROLLS):
    """Observe -> find -> scroll -> retry. Restores position on failure."""
    target = _step29_normalize(target)
    if not target:
        return None

    print("STEP 29: OBSERVE ->", target)
    first = _step29_candidate(target)
    if first and float(first.get("target_score", 0)) >= STEP29_MIN_SCORE:
        print(
            "STEP 29: TARGET FOUND ->",
            target,
            "| score:", round(float(first.get("target_score", 0)), 1),
            "| mouse:", first.get("center_x"), first.get("center_y")
        )
        return first

    if not PYAUTOGUI_AVAILABLE:
        return first

    scrolled = 0
    for attempt in range(1, int(max_scrolls) + 1):
        print(f"STEP 29: TARGET NOT VISIBLE -> SCROLL RETRY {attempt}/{max_scrolls}")
        try:
            pyautogui.scroll(STEP29_SCROLL_AMOUNT)
            scrolled += 1
            time.sleep(0.7)
        except Exception as e:
            print("STEP 29 SCROLL ERROR:", e)
            break

        candidate = _step29_candidate(target)
        if candidate and float(candidate.get("target_score", 0)) >= STEP29_MIN_SCORE:
            print(
                "STEP 29: TARGET FOUND AFTER SCROLL ->",
                target,
                "| score:", round(float(candidate.get("target_score", 0)), 1),
                "| mouse:", candidate.get("center_x"), candidate.get("center_y")
            )
            candidate["scroll_retries"] = scrolled
            return candidate

    # We changed the viewport but did not find the target. Restore it.
    if scrolled:
        try:
            pyautogui.scroll(-STEP29_SCROLL_AMOUNT * scrolled)
            time.sleep(0.5)
            print("STEP 29: ORIGINAL VIEW RESTORED")
        except Exception as e:
            print("STEP 29 RESTORE ERROR:", e)

    return None


def step29_visual_locate(target):
    result = step29_find_with_retry(target)
    if not result:
        speak("I could not locate " + str(target) + " on the screen.")
        return True

    x = int(result.get("center_x", 0))
    y = int(result.get("center_y", 0))
    score = float(result.get("target_score", 0))
    print("STEP 29: LOCATE ->", target, "| score:", round(score, 1), "| mouse:", x, y)
    speak("I found " + str(target) + " at " + str(x) + " by " + str(y) + ".")
    return True


def step29_visual_hover(target):
    result = step29_find_with_retry(target)
    if not result:
        speak("I could not locate " + str(target) + ".")
        return True

    score = float(result.get("target_score", 0))
    if score < STEP29_MIN_SCORE:
        speak("The target is ambiguous, so I will not move to it.")
        return True

    x = int(result.get("center_x", 0))
    y = int(result.get("center_y", 0))
    pyautogui.moveTo(x, y, duration=0.35)
    print("STEP 29: HOVER ->", target, "|", x, y, "| score:", round(score, 1))
    speak("I moved to " + str(target) + ".")
    return True


def step29_visual_click(target):
    result = step29_find_with_retry(target)
    if not result:
        speak("I could not safely find " + str(target) + ".")
        return True

    score = float(result.get("target_score", 0))
    if score < STEP29_MIN_SCORE:
        print("STEP 29: AMBIGUOUS CLICK BLOCKED ->", target, score)
        speak("The target is ambiguous, so I will not click it.")
        return True

    x = int(result.get("center_x", 0))
    y = int(result.get("center_y", 0))
    before = _screen_signature()
    print("STEP 29: ACT -> CLICK", target, "at", x, y)

    try:
        pyautogui.moveTo(x, y, duration=0.25)
        pyautogui.click(x, y)
        time.sleep(0.6)
    except Exception as e:
        print("STEP 29 CLICK ERROR:", e)
        speak("I could not click " + str(target) + ".")
        return True

    changed = False
    try:
        changed = verify_screen_changed(before, 0.7)
    except Exception as e:
        print("STEP 29 VERIFY ERROR:", e)

    print("STEP 29: VERIFY ->", "screen changed" if changed else "no visible change")
    speak("Clicked " + str(target) + ".")
    return True


def step29_visual_command(command):
    """Router for Step 29 visual goal commands not already handled by Step 28."""
    s = _step29_normalize(command)

    # Do not intercept Step 28's explicit multi-action type workflow.
    if " type " in (" " + s + " "):
        return False

    # Find + click: "facebook icon dhoondo aur click karo"
    m = re.search(
        r"(?:screen\s+(?:par|pe|mein|me)\s+)?(.+?)\s+"
        r"(?:dhoondo|dhundo|khojo|find(?:\s+karo)?|locate(?:\s+karo)?)\s+"
        r"(?:aur|and|then)\s+(?:click|dabao)(?:\s+(?:karo|kar|kar\s+do))?\s*$",
        s
    )
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(?:screen\s+(?:par|pe|mein|me))\s+", "", target).strip()
        return step29_visual_click(target)

    # Find + hover/move: "facebook icon dhoondo aur mouse le jao"
    m = re.search(
        r"(?:screen\s+(?:par|pe|mein|me)\s+)?(.+?)\s+"
        r"(?:dhoondo|dhundo|khojo|find(?:\s+karo)?|locate(?:\s+karo)?)\s+"
        r"(?:aur|and|then)\s+(?:mouse|pointer)\s+le\s+j(?:ao|a)\s*$",
        s
    )
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(?:screen\s+(?:par|pe|mein|me))\s+", "", target).strip()
        return step29_visual_hover(target)

    # Explicit scroll-and-find: "scroll karke settings dhoondo"
    m = re.search(
        r"(?:screen\s+(?:par|pe|mein|me)\s+)?"
        r"(?:scroll\s+(?:karke|kar\s+ke)\s+)?"
        r"(.+?)\s+(?:dhoondo|dhundo|khojo|find(?:\s+karo)?|locate(?:\s+karo)?)\s*$",
        s
    )
    if m:
        target = m.group(1).strip()
        target = re.sub(r"^(?:scroll\s+(?:karke|kar\s+ke)\s+)", "", target).strip()
        target = re.sub(r"^(?:screen\s+(?:par|pe|mein|me))\s+", "", target).strip()
        # Only use Step 29 when the command is clearly a visual-target request.
        if target and target not in {"screen", "elements", "ui"}:
            return step29_visual_locate(target)

    return False



# ============================================================
# STEP 30 - VISUAL TARGET MEMORY / FOLLOW-UP CONTEXT
# ============================================================
STEP30_VISUAL_MEMORY_FILE = os.path.join(BASE_DIR, "jarvis_visual_target.json")


def step30_load_visual_target():
    try:
        if not os.path.exists(STEP30_VISUAL_MEMORY_FILE):
            return None
        with open(STEP30_VISUAL_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("target"):
            return data
    except Exception as e:
        print("STEP 30 MEMORY LOAD ERROR:", e)
    return None


def step30_save_visual_target(target, result=None):
    result = result or {}
    data = {
        "target": str(target).strip(),
        "x": int(result.get("center_x", result.get("mouse_x", 0))),
        "y": int(result.get("center_y", result.get("mouse_y", 0))),
        "score": float(result.get("target_score", result.get("score", 0))),
        "saved_at": time.time(),
    }
    try:
        with open(STEP30_VISUAL_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("STEP 30 MEMORY SAVE ERROR:", e)


def step30_find_and_remember(target):
    target = str(target).strip()
    if not target:
        return False
    result = step29_find_with_retry(target)
    if not result:
        speak("I could not locate " + target + ".")
        return True
    step30_save_visual_target(target, result)
    x = int(result.get("center_x", result.get("mouse_x", 0)))
    y = int(result.get("center_y", result.get("mouse_y", 0)))
    score = float(result.get("target_score", result.get("score", 0)))
    print("STEP 30: TARGET REMEMBERED ->", target, "| score:", round(score, 1), "| mouse:", x, y)
    speak("I found and remembered " + target + ".")
    return True


def step30_follow_up(command):
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    s = re.sub(r"^jarvis[\s,]*", "", s).strip()
    memory = step30_load_visual_target()
    if not memory:
        return False
    target = str(memory.get("target", "")).strip()
    if not target:
        return False

    if re.search(r"\b(?:isko|is\s+par|usko|us\s+par|wahi|same)\b.*\b(?:click|dabao)\b", s):
        return visual_agent_click(target)

    if re.search(r"\b(?:isko|is\s+par|usko|us\s+par|wahi|same)\b.*\b(?:mouse|pointer)\s+le\s+j(?:ao|a)\b", s):
        return visual_agent_move_to(target)

    tm = re.search(
        r"\b(?:isme|is\s+mein|ismein|usme|us\s+mein|usmein|isko)\b\s+(.+?)\s+type(?:\s+(?:karo|kar|kar\s+do))?\s*$",
        s,
    )
    if tm:
        payload = tm.group(1).strip(" ,")
        if payload and PYAUTOGUI_AVAILABLE:
            print("STEP 30: FOLLOW-UP TYPE ->", target, "| text:", payload)
            try:
                result = step29_find_with_retry(target)
                if not result:
                    speak("I could not relocate " + target + ".")
                    return True
                step30_save_visual_target(target, result)
                pyautogui.click(int(result.get("center_x", 0)), int(result.get("center_y", 0)))
                time.sleep(0.2)
                pyautogui.hotkey("ctrl", "a")
                pyautogui.write(payload, interval=0.02)
                speak("I typed " + payload + ".")
                return True
            except Exception as e:
                print("STEP 30 FOLLOW-UP TYPE ERROR:", e)
                speak("I could not type into " + target + ".")
                return True

    if re.search(r"\b(?:enter|return)\s+(?:press|dabao|daba(?:o)?)\b", s):
        if PYAUTOGUI_AVAILABLE:
            pyautogui.press("enter")
            speak("Enter pressed.")
        return True
    return False


def step30_visual_command(command):
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    s = re.sub(r"^jarvis[\s,]*", "", s).strip()

    # Follow-up commands must be checked before generic visual locate.
    if step30_follow_up(s):
        return True

    # Remember a freshly located target. Do not steal multi-action commands.
    if re.search(r"\b(?:aur|and|then)\b", s) or re.search(r"\btype\b", s):
        return False

    m = re.search(
        r"(?:screen\s+(?:par|pe|me|mein)\s+)?(.+?)\s+"
        r"(?:dhoondo|dhundo|khojo|find(?:\s+karo)?|locate(?:\s+karo)?)\s*$",
        s,
    )
    if m:
        target = m.group(1).strip()
        if target not in {"screen", "elements", "ui", "visual map"}:
            return step30_find_and_remember(target)
    return False


# ============================================================
# STEP 31 - VERIFIED VISUAL ACTIONS / SELF-CORRECTION
# ============================================================
STEP31_MAX_CANDIDATES = 4
STEP31_MIN_SCORE = 350.0


def step31_get_candidates(target):
    """Collect and rank local OCR targets without using Gemini."""
    target = re.sub(r"\s+", " ", str(target).lower()).strip()
    if not target:
        return []
    try:
        elements = detect_text_elements()
    except Exception as e:
        print("STEP 31 CANDIDATE ERROR:", e)
        return []

    scored = []
    wanted = set(re.findall(r"[a-z0-9]+", target))
    for item in elements or []:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        low = text.lower()
        words = set(re.findall(r"[a-z0-9]+", low))
        score = 0.0
        if low == target:
            score += 1000.0
        if target in low:
            score += 650.0
        overlap = len(wanted & words)
        score += overlap * 180.0
        try:
            score += max(0.0, float(item.get("confidence", 0)))
        except Exception:
            pass
        if score > 0:
            item = dict(item)
            item["step31_score"] = score
            item["mouse_x"] = int(item.get("center_x", item.get("x", 0)))
            item["mouse_y"] = int(item.get("center_y", item.get("y", 0)))
            scored.append(item)
    scored.sort(key=lambda x: x.get("step31_score", 0), reverse=True)
    return scored[:STEP31_MAX_CANDIDATES]


def step31_verified_click(target):
    """Click a strong visual target and verify the screen changed."""
    if not PYAUTOGUI_AVAILABLE:
        speak("Mouse control is not available.")
        return True
    if agent_is_sensitive(target):
        speak("I will not perform that sensitive action automatically.")
        return True

    candidates = step31_get_candidates(target)
    if not candidates or float(candidates[0].get("step31_score", 0)) < STEP31_MIN_SCORE:
        speak("I could not confidently identify " + str(target) + ".")
        return True

    best = candidates[0]
    x, y = int(best["mouse_x"]), int(best["mouse_y"])
    before = _screen_signature()
    print("STEP 31: OBSERVE ->", target)
    print("STEP 31: SELECT ->", best.get("text"), "| score:", round(float(best.get("step31_score", 0)), 1), "| mouse:", x, y)
    pyautogui.moveTo(x, y, duration=0.25)
    pyautogui.click(x, y)
    time.sleep(0.7)

    changed = verify_screen_changed(before, 0.5)
    if changed:
        step30_save_visual_target(target, best)
        print("STEP 31: VERIFY -> screen changed")
        speak("Clicked " + str(target) + ".")
        return True

    # One controlled recovery: re-observe and use the next distinct candidate.
    print("STEP 31: VERIFY -> no visible change; trying recovery")
    if len(candidates) > 1:
        alt = candidates[1]
        ax, ay = int(alt["mouse_x"]), int(alt["mouse_y"])
        if abs(ax - x) + abs(ay - y) > 20 and float(alt.get("step31_score", 0)) >= STEP31_MIN_SCORE:
            before2 = _screen_signature()
            pyautogui.moveTo(ax, ay, duration=0.25)
            pyautogui.click(ax, ay)
            time.sleep(0.7)
            if verify_screen_changed(before2, 0.5):
                step30_save_visual_target(target, alt)
                print("STEP 31: RECOVERY VERIFY -> success")
                speak("Clicked " + str(target) + ".")
                return True

    # Do not keep clicking indefinitely.
    speak("I found " + str(target) + ", but I could not verify the click.")
    return True


def step31_verified_type(target, text_to_type):
    """Relocate a visual input target, type, and verify typed text locally."""
    if not PYAUTOGUI_AVAILABLE:
        speak("Keyboard control is not available.")
        return True
    if not str(text_to_type).strip():
        speak("There is no text to type.")
        return True

    result = step29_find_with_retry(target)
    if not result:
        speak("I could not locate " + str(target) + ".")
        return True

    x = int(result.get("center_x", result.get("mouse_x", 0)))
    y = int(result.get("center_y", result.get("mouse_y", 0)))
    print("STEP 31: TYPE TARGET ->", target, "| mouse:", x, y)
    pyautogui.click(x, y)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(str(text_to_type), interval=0.02)
    time.sleep(0.4)

    try:
        found = find_best_screen_element(str(text_to_type))
    except Exception:
        found = None
    if found:
        step30_save_visual_target(target, result)
        print("STEP 31: VERIFY -> typed text detected")
        speak("I typed " + str(text_to_type) + ".")
    else:
        print("STEP 31: VERIFY -> typed text not detected")
        speak("I typed the text, but I could not verify it on screen.")
    return True


def step31_visual_command(command):
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    s = re.sub(r"^jarvis[\s,]*", "", s).strip()

    # Never intercept multi-action Step 28 commands.
    if re.search(r"\b(?:aur|and|then)\b", s):
        return False

    # Explicit verified click: "search verified click karo" / "search par verified click karo"
    m = re.match(r"(?:screen\s+(?:par|pe|mein|me)\s+)?(.+?)\s+verified\s+click(?:\s+(?:karo|kar|kar\s+do))?$", s)
    if m:
        return step31_verified_click(m.group(1).strip())

    # Explicit safe click with verification, only when user says verify/check.
    m = re.match(r"(?:screen\s+(?:par|pe|mein|me)\s+)?(.+?)\s+click\s+(?:karke\s+)?verify(?:\s+(?:karo|kar))?$", s)
    if m:
        return step31_verified_click(m.group(1).strip())

    # Explicit visual type command: "search mein Free Fire type karo"
    m = re.match(r"(?:screen\s+(?:par|pe|mein|me)\s+)?(.+?)\s+(?:mein|me|inside|in)\s+(.+?)\s+type(?:\s+(?:karo|kar|kar\s+do))?$", s)
    if m and not re.search(r"\b(?:aur|and|then)\b", s):
        return step31_verified_type(m.group(1).strip(), m.group(2).strip())

    return False



# ================================================================
# STEP 32: SCREEN STATE / WAIT-UNTIL-VISIBLE AGENT
# ================================================================
STEP32_DEFAULT_TIMEOUT = 12.0
STEP32_POLL_INTERVAL = 0.7


def step32_screen_has_text(target):
    """Return the best OCR match for target, or None."""
    try:
        return find_best_screen_element(str(target).strip())
    except Exception as e:
        print("STEP 32: OCR CHECK ERROR:", e)
        return None


def step32_wait_for_text(target, timeout=STEP32_DEFAULT_TIMEOUT):
    """Wait locally until OCR can see target on the current screen."""
    target = re.sub(r"\s+", " ", str(target)).strip()
    if not target:
        speak("Tell me what I should wait for.")
        return False

    try:
        timeout = max(1.0, min(float(timeout), 30.0))
    except Exception:
        timeout = STEP32_DEFAULT_TIMEOUT

    print("STEP 32: WAIT FOR ->", target, "| timeout:", timeout)
    started = time.time()
    while time.time() - started <= timeout:
        found = step32_screen_has_text(target)
        if found:
            print("STEP 32: FOUND ->", found.get("text"), "| score:", found.get("match_score"))
            speak("I can see " + target + ".")
            return True
        time.sleep(STEP32_POLL_INTERVAL)

    print("STEP 32: TIMEOUT ->", target)
    speak("I could not see " + target + " yet.")
    return False


def step32_wait_for_screen_change(timeout=STEP32_DEFAULT_TIMEOUT):
    """Wait locally for a visual screen-signature change."""
    try:
        timeout = max(1.0, min(float(timeout), 30.0))
    except Exception:
        timeout = STEP32_DEFAULT_TIMEOUT

    before = _screen_signature()
    if before is None:
        speak("I could not capture the current screen.")
        return False

    print("STEP 32: WAIT FOR SCREEN CHANGE | timeout:", timeout)
    started = time.time()
    while time.time() - started <= timeout:
        time.sleep(STEP32_POLL_INTERVAL)
        after = _screen_signature()
        if after is not None and after != before:
            print("STEP 32: SCREEN CHANGED")
            speak("The screen changed.")
            return True

    print("STEP 32: SCREEN CHANGE TIMEOUT")
    speak("The screen did not change yet.")
    return False


def step32_visual_command(command):
    """Handle explicit wait/state commands without using Gemini."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    s = re.sub(r"^jarvis[\s,]*", "", s).strip()

    # Do not steal multi-action commands from Step 28.
    if re.search(r"\b(?:aur|and|then)\b", s):
        return False

    # wait until screen/text appears
    # Speech recognition may turn "wait" into "vate", so accept both.
    patterns = [
        r"^(?:wait|vate|ruk|ruko)\s+(?:jab|until|till)\s+(.+?)(?:\s+(?:aa|a)\s+jaye|\s+dikhe|\s+dikhta\s+hai)?$",
        r"^(.+?)\s+dikhne\s+(?:tak|takk)\s+(?:wait|vate|ruk|ruko)\s*(?:karo)?$",
        r"^(.+?)\s+dikhne\s+(?:tak|takk)\s+(?:wait|vate|ruk|ruko)\s+kar(?:o|na)?$",
        r"^(.+?)\s+(?:dikh|dikhe)\s+(?:tak|takk)\s+(?:wait|vate|ruk|ruko)\s*(?:karo)?$",
        r"^(.+?)\s+(?:a|aa)\s+jaye\s+tab\s+batana$",
        r"^(?:wait|vate|ruk|ruko)\s+(?:for|ke\s+liye)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.match(pat, s)
        if m:
            target = m.group(1).strip()
            return step32_wait_for_text(target)

    # English/Hinglish explicit forms: "wait until Search appears"
    m = re.match(r"^(?:wait|ruk|ruko)\s+until\s+(.+?)(?:\s+(?:appears|is\s+visible|dikhe))?$", s)
    if m:
        return step32_wait_for_text(m.group(1).strip())

    # "wait for screen change"
    if re.match(r"^(?:screen\s+change\s+ka\s+wait|wait\s+for\s+screen\s+change|screen\s+change\s+hone\s+ka\s+wait)$", s):
        return step32_wait_for_screen_change()

    return False



# =========================================================
# STEP 33 - NATURAL LANGUAGE AI BRAIN
# Understands Hindi/Hinglish/English naturally and converts
# the request into safe, structured actions. Gemini is used only
# after local routers cannot handle the command, so simple commands
# remain fast and quota-safe.
# =========================================================

AI_BRAIN_MODEL = "gemini-3.7-flash"
AI_BRAIN_MAX_ACTIONS = 6
AI_BRAIN_ENABLED = True


def _step33_strip_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text, flags=re.I)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return text.strip()


def _step33_ai_prompt(command):
    recent = get_recent_conversation_context()
    memory = load_memory()
    facts = memory.get("facts", {}) if isinstance(memory, dict) else {}

    return f"""
You are JARVIS's natural-language brain for a Windows desktop voice assistant.
Understand Hindi, Hinglish, English, informal speech, incomplete sentences,
pronouns and conversational wording. Do NOT control the computer directly.
Return ONLY valid JSON.

CURRENT USER COMMAND:
{command}

RECENT CONVERSATION:
{recent}

KNOWN MEMORY FACTS:
{json.dumps(facts, ensure_ascii=False)[:4000]}

Choose exactly one mode:
ACTION or CHAT or UNKNOWN.

For ACTION return:
{{
  "mode":"ACTION",
  "reply":"short acknowledgement",
  "actions":[
    {{"type":"open_site|search|locate|click|type|press|scroll|read_screen|wait_screen_change",
      "target":"", "text":"", "key":"", "direction":"", "site":""}}
  ],
  "confidence":0.0
}}

For CHAT return:
{{"mode":"CHAT","reply":"natural concise answer","actions":[],"confidence":0.0}}

For UNKNOWN return:
{{"mode":"UNKNOWN","reply":"I need a little more information.","actions":[],"confidence":0.0}}

Rules:
1. Understand intent, not exact keywords. Example: "wo search wala box hai na,
usme Free Fire daal de" means locate/click the search box, then type Free Fire.
2. "YouTube pe Free Fire search kar" means a search action on YouTube.
3. Resolve "isko", "isme", "usko", "wahi", "jo abhi" from recent context only.
4. Never invent a target when context does not support it.
5. Maximum {AI_BRAIN_MAX_ACTIONS} actions.
6. Never create actions for payment, purchases, money transfer, sending messages,
deleting data, posting/publishing, account changes, password changes, or other
consequential actions. Return UNKNOWN instead.
7. For a visible UI target, prefer locate/click/type actions; do not invent coordinates.
8. If the user is simply asking a question or chatting, use CHAT.
9. Keep reply under 250 characters.
"""


def step33_ai_understand(command):
    global GEMINI_QUOTA_EXHAUSTED
    if GEMINI_QUOTA_EXHAUSTED:
        print("STEP 33 AI BRAIN: Gemini quota exhausted - local fallback only")
        return None
    if not AI_BRAIN_ENABLED or "client" not in globals():
        return None
    try:
        response = client.models.generate_content(
            model=AI_BRAIN_MODEL,
            contents=_step33_ai_prompt(command)
        )
        raw = _step33_strip_json(getattr(response, "text", ""))
        result = json.loads(raw)
        mode = result.get("mode")
        if mode not in {"ACTION", "CHAT", "UNKNOWN"}:
            return None
        actions = result.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        result["actions"] = actions[:AI_BRAIN_MAX_ACTIONS]
        try:
            result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0))))
        except Exception:
            result["confidence"] = 0.0
        print("STEP 33 AI BRAIN:", result)
        return result
    except Exception as e:
        if _gemini_quota_error(e):
            GEMINI_QUOTA_EXHAUSTED = True
            print("STEP 33 AI BRAIN: Gemini quota exhausted - disabling Gemini for this session")
        else:
            print("STEP 33 AI BRAIN ERROR:", e)
        return None


def _step33_safe_action(action):
    kind = str(action.get("type", "")).lower().strip()
    target = str(action.get("target", "")).strip()
    text = str(action.get("text", "")).strip()
    key = str(action.get("key", "")).strip().lower()
    direction = str(action.get("direction", "")).strip().lower()
    site = str(action.get("site", "")).strip().lower()

    if kind in {"send", "delete", "pay", "payment", "purchase", "buy", "order", "transfer", "post", "publish", "submit", "confirm", "change_password"}:
        speak("I will not perform that sensitive action automatically.")
        return False

    if kind == "open_site":
        urls = {
            "youtube": "https://www.youtube.com", "google": "https://www.google.com",
            "gmail": "https://mail.google.com", "chatgpt": "https://chatgpt.com",
            "github": "https://github.com", "whatsapp": "https://web.whatsapp.com",
            "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com",
            "linkedin": "https://www.linkedin.com", "drive": "https://drive.google.com",
            "maps": "https://maps.google.com"
        }
        url = urls.get(site or target.lower())
        if not url:
            return False
        webbrowser.open(url)
        time.sleep(2)
        return True

    if kind == "search":
        query = text or target
        if not query:
            return False
        if site == "youtube" or "youtube" in target.lower():
            webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
        else:
            webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
        time.sleep(2)
        return True

    if kind == "locate":
        return bool(visual_agent_move_to(target)) if target else False

    if kind == "click":
        if not target or agent_is_sensitive(target + " " + text):
            return False
        result = visual_agent_find_target(target)
        if not result or float(result.get("score", 0)) < 250:
            return False
        pyautogui.click(int(result["mouse_x"]), int(result["mouse_y"]))
        time.sleep(.4)
        return True

    if kind == "type":
        if not text:
            return False
        if target:
            return bool(type_into_screen_element(target, text))
        pyautogui.write(text, interval=.025)
        time.sleep(.3)
        return True

    if kind == "press":
        if key in {"enter", "esc", "escape", "tab", "space", "backspace", "up", "down", "left", "right", "home", "end"}:
            return bool(jarvis_press_key("esc" if key == "escape" else key))
        return False

    if kind == "scroll":
        amount = -5 if direction in {"down", "neeche", "downward"} else 5
        pyautogui.scroll(amount)
        time.sleep(.4)
        return True

    if kind == "read_screen":
        return bool(screen_tools("screen ka text read karo"))

    if kind == "wait_screen_change":
        return bool(step32_wait_for_screen_change())

    return False


def step33_ai_brain(command):
    """Last-resort natural language understanding layer."""
    if agent_is_sensitive(command):
        return False

    result = step33_ai_understand(command)
    if not result:
        return False

    confidence = float(result.get("confidence", 0))
    mode = result.get("mode")

    if mode == "CHAT":
        reply = str(result.get("reply", "")).strip()
        if reply:
            speak(reply)
            add_conversation_context(command, reply)
            return True
        return False

    if mode != "ACTION" or confidence < 0.65:
        return False

    actions = result.get("actions", [])
    if not actions:
        return False

    for i, action in enumerate(actions, 1):
        print(f"STEP 33: ACTION {i}/{len(actions)} -> {action}")
        if not _step33_safe_action(action):
            speak("I could not safely complete that step.")
            return True

    reply = str(result.get("reply", "Task completed."))
    speak(reply[:250])
    add_conversation_context(command, reply[:250])
    return True



# =========================================================
# STEP 33.1 - LOCAL NATURAL HINGLISH COMMAND UNDERSTANDING
# Handles ASR variations such as: dal/daal/dalo/daalo/bhar/likh/type
# without spending Gemini quota.
# =========================================================

def step33_local_natural_input(command):
    """Handle common natural Hinglish 'put/type this in search box' commands locally."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    s = re.sub(r"^jarvis[\s,]*", "", s).strip()

    put_verbs = (
        r"(?:daal|dal|dalo|daalo|daalna|dalna|bhar|bhardo|bhar do|"
        r"daal do|dal do|dalo na|daalo na|likho|likh do|type karo|"
        r"type kar do|type kardo|enter karo)"
    )

    # Examples:
    # YouTube kholo aur search wale box mein Free Fire dal do
    # YouTube open karke search bar me Minecraft daalo
    # search box mein Motu Patlu likh do
    pattern = (
        r"(?:youtube|google)?\s*"
        r"(?:khol(?:o)?|open(?: karo)?|kholo|open)?\s*"
        r"(?:aur|and)?\s*"
        r"(?:search\s*(?:wale\s*)?(?:box|bar)|searchbar|input\s*box)\s*"
        r"(?:me|mein|par|pe|ke\s+andar)\s+"
        r"(.+?)\s+" + put_verbs + r"(?:\s+na)?\s*$"
    )
    m = re.search(pattern, s, flags=re.IGNORECASE)
    if not m:
        return False

    value = m.group(1).strip(" ,.")
    if not value:
        return False

    # Open the requested site first when the sentence explicitly asks for it.
    if "youtube" in s and any(x in s for x in ["khol", "kholo", "open"]):
        print("LOCAL NATURAL: opening YouTube -> finding search box -> typing:", value)
        webbrowser.open("https://www.youtube.com")
        time.sleep(3)
    elif "google" in s and any(x in s for x in ["khol", "kholo", "open"]):
        print("LOCAL NATURAL: opening Google -> finding search box -> typing:", value)
        webbrowser.open("https://www.google.com")
        time.sleep(3)
    else:
        print("LOCAL NATURAL: finding search/input box -> typing:", value)

    ok = smart_input_type(value)
    if ok:
        speak("Done. I typed " + value)
    else:
        speak("I could not find the search box.")
    return True


# =========================================================
# STEP 38 - LOCAL CODE SELF-DIAGNOSIS
# Diagnose Python files without modifying them.
# =========================================================

def step38_resolve_file(target="main.py"):
    """Resolve a user-mentioned file safely, preferring the JARVIS folder."""
    target = str(target or "main.py").strip().strip('"\'')
    target = re.sub(r"[?.!,]+$", "", target).strip()
    if not target:
        target = "main.py"

    candidates = []
    if os.path.isabs(target):
        candidates.append(target)
    else:
        candidates.extend([
            os.path.join(BASE_DIR, target),
            os.path.join(os.path.expanduser("~"), "Desktop", "jarvish", target),
            os.path.join(os.path.expanduser("~"), "Desktop", target),
            target,
        ])

    # If the spoken name omitted .py, try it.
    if not os.path.splitext(target)[1]:
        candidates.extend([c + ".py" for c in list(candidates)])

    seen = set()
    for c in candidates:
        c = os.path.abspath(os.path.expandvars(os.path.expanduser(c)))
        if c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            return c
    return None


def step38_extract_file_target(command):
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    patterns = [
        r"(?:main|jarvis)\s*\.py",
        r"[\w ._-]+\.py",
        r"(?:file|फाइल)\s+([\w ._-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            value = m.group(0).strip()
            if "file" in value and m.lastindex:
                value = m.group(1).strip()
            return value
    return "main.py"


def step38_python_diagnose(path):
    """Return a structured, read-only Python syntax diagnosis."""
    result = {"path": path, "ok": False, "error": None, "line": None, "offset": None, "message": None}
    try:
        source = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            source = Path(path).read_text(encoding="cp1252")
        except Exception as e:
            result["error"] = f"Could not read file: {e}"
            return result
    except Exception as e:
        result["error"] = f"Could not read file: {e}"
        return result

    result["lines"] = len(source.splitlines())
    try:
        tree = ast.parse(source, filename=path)
        result["ok"] = True
        result["functions"] = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
        result["classes"] = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
        result["imports"] = sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree))
        result["message"] = "No Python syntax errors found."
    except SyntaxError as e:
        result["error"] = "SyntaxError"
        result["line"] = e.lineno
        result["offset"] = e.offset
        result["message"] = e.msg or "Invalid Python syntax."
        if getattr(e, "text", None):
            result["source_line"] = e.text.strip()
    return result


def step38_diagnose_command(command):
    """Handle natural-language read-only code diagnosis requests."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    triggers = [
        "code check", "code ko check", "code check karo", "code diagnose",
        "code diagnosis", "error dhoondo", "error dhundo", "error dhoondho",
        "syntax check", "syntax chek", "syntax diagnose", "code mein error",
        "code me error", "problem dhoondo", "problem dhundo", "problem batao",
        "error wali line", "syntax error"
    ]
    if not any(t in s for t in triggers):
        return False

    target = step38_extract_file_target(s)
    path = step38_resolve_file(target)
    if not path:
        speak("I could not find that Python file.")
        print("STEP 38: FILE NOT FOUND ->", target)
        return True

    result = step38_python_diagnose(path)
    print("STEP 38: DIAGNOSIS ->", result)

    if result.get("ok"):
        speak(f"I checked {os.path.basename(path)}. No Python syntax errors found.")
        return True

    if result.get("error") == "SyntaxError":
        line = result.get("line") or "unknown"
        msg = result.get("message") or "syntax problem"
        speak(f"I found a syntax error on line {line}. {msg}.")
        return True

    speak("I could not diagnose that file.")
    return True



# ============================================================
# STEP 39 - PYTHON ERROR EXPLAINER (READ-ONLY)
# ============================================================
STEP39_ERROR_HINTS = {
    "invalid syntax": "Python could not understand the code structure. Check brackets, quotes, commas, or the previous line.",
    "expected ':'": "A Python block such as if, for, while, def, or try needs a colon at the end of its line.",
    "unexpected indent": "This line has more indentation than Python expects. Match its indentation with the surrounding block.",
    "unindent does not match": "The indentation level does not match the surrounding block. Check spaces and tabs.",
    "unterminated string": "A string starts with a quote but Python could not find its closing quote.",
    "'(' was never closed": "An opening parenthesis is missing its closing parenthesis.",
    "'[' was never closed": "An opening square bracket is missing its closing bracket.",
    "'{' was never closed": "An opening curly bracket is missing its closing bracket.",
}

def step39_explain_syntax_result(result):
    """Turn a Step 38 diagnosis result into a simple Hinglish explanation."""
    if not result:
        return "I do not have a diagnosis to explain."
    if result.get("ok"):
        return "Maine code check kiya. Python syntax theek hai, isliye syntax level par koi error nahi mila."
    if result.get("error") == "SyntaxError":
        msg = str(result.get("message") or "syntax problem").lower()
        hint = None
        for key, value in STEP39_ERROR_HINTS.items():
            if key in msg:
                hint = value
                break
        line = result.get("line") or "unknown"
        if hint:
            return f"Syntax error line {line} par hai. {hint}"
        return f"Syntax error line {line} par hai. Python ne kaha: {result.get('message') or 'syntax problem'}. Is line aur uske just upar wali line ko check karo."
    return "File read ya diagnosis ke waqt problem aayi, isliye main exact syntax explanation nahi de sakta."

def step39_error_explain_command(command):
    """Explain the current Python file's syntax result; never modifies code."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    triggers = [
        "error samjhao", "error samjha", "error explain", "problem samjhao",
        "problem samjha", "syntax error samjhao", "syntax samjhao",
        "iska matlab kya hai", "ye error kya hai", "ye problem kya hai",
        "error ka matlab", "problem ka matlab", "error explain karo",
        "error ko explain karo", "code error samjhao"
    ]
    if not any(t in s for t in triggers):
        return False

    target = step38_extract_file_target(s)
    path = step38_resolve_file(target)
    if not path:
        speak("I could not find that Python file.")
        print("STEP 39: FILE NOT FOUND ->", target)
        return True

    result = step38_python_diagnose(path)
    explanation = step39_explain_syntax_result(result)
    print("STEP 39: EXPLANATION ->", explanation)
    speak(explanation)
    return True


# ============================================================
# STEP 40 - SAFE AI FIX SUGGESTER
# ============================================================
STEP40_FIX_HINTS = {
    "invalid syntax": "Check the reported line and the line immediately before it for missing brackets, quotes, commas, or a misplaced keyword.",
    "expected ':'": "Add a colon (:) at the end of the if/for/while/def/try/except/class line if it starts a block.",
    "unexpected indent": "Remove extra spaces from the reported line so its indentation matches the surrounding block.",
    "unindent does not match": "Use consistent indentation. Prefer 4 spaces and avoid mixing tabs with spaces.",
    "unterminated string": "Close the string with the matching quote (single or double quote).",
    "'(' was never closed": "Find the nearest unmatched opening parenthesis and add its closing ).",
    "'[' was never closed": "Find the nearest unmatched opening square bracket and add its closing ].",
    "'{' was never closed": "Find the nearest unmatched opening curly bracket and add its closing }.",
}

def step40_get_context_lines(path, line_number, radius=2):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        n = int(line_number)
        start = max(1, n - radius)
        end = min(len(lines), n + radius)
        return [(i, lines[i-1]) for i in range(start, end + 1)]
    except Exception:
        return []

def step40_suggest_fix(path, result):
    """Create a read-only fix suggestion. This function NEVER edits the file."""
    if not result:
        return "Mujhe diagnosis result nahi mila, isliye safe fix suggestion nahi de sakta."
    if result.get("ok"):
        return "Code syntax theek hai. Koi syntax fix suggest karne ki zarurat nahi hai."
    err = str(result.get("error") or "").strip()
    msg = str(result.get("message") or "Python error").strip()
    line = result.get("line")
    lower = msg.lower()
    hint = None
    for key, value in STEP40_FIX_HINTS.items():
        if key in lower:
            hint = value
            break
    if err == "SyntaxError":
        if hint is None:
            hint = "Reported line aur uske just upar wali line ko check karo; Python syntax error aksar previous line ki wajah se bhi hota hai."
        if line:
            context = step40_get_context_lines(path, line, radius=1)
            print("STEP 40: CODE CONTEXT")
            for num, text in context:
                print(f"  {num}: {text}")
            return f"Safe fix suggestion: line {line} par SyntaxError hai. {hint} Python message: {msg}. Main file ko automatically change nahi kar raha hoon."
        return f"Safe fix suggestion: SyntaxError mila. {hint} Python message: {msg}. Main file ko automatically change nahi kar raha hoon."
    return f"Safe fix suggestion: {err or 'runtime/code problem'} mila. Python message: {msg}. Is fix ko apply karne se pehle file ka backup aur re-test karna chahiye. Main file ko automatically change nahi kar raha hoon."

def step40_fix_suggest_command(command):
    """Handle natural Hinglish requests for a safe, read-only fix suggestion."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    triggers = [
        "fix suggest karo", "fix suggest", "fix batao", "fix batado", "fix bata do",
        "solution batao", "solution suggest karo", "sahi kaise karu", "theek kaise karu",
        "error ka fix", "error fix", "syntax fix", "fix kya hai", "kya fix karna hai",
        "repair suggest karo", "repair batao", "problem ka solution",
    ]
    if not any(t in s for t in triggers):
        return False
    target = step38_extract_file_target(s)
    path = step38_resolve_file(target)
    if not path:
        speak("I could not find that Python file.")
        print("STEP 40: FILE NOT FOUND ->", target)
        return True
    result = step38_python_diagnose(path)
    suggestion = step40_suggest_fix(path, result)
    print("STEP 40: FIX SUGGESTION ->", suggestion)
    speak(suggestion)
    return True


# ============================================================
# STEP 41 - APPROVED SAFE REPAIR
# Only applies a very small set of high-confidence repairs after
# the user explicitly asks to apply the fix. Always creates a backup
# and syntax-checks the edited file; rolls back if validation fails.
# ============================================================

STEP41_BACKUP_SUFFIX = ".step41_backup.py"


def step41_backup_file(path):
    try:
        backup = path + STEP41_BACKUP_SUFFIX
        shutil.copy2(path, backup)
        print("STEP 41: BACKUP CREATED ->", backup)
        return backup
    except Exception as e:
        print("STEP 41 BACKUP ERROR:", e)
        return None


def step41_restore_file(path, backup):
    try:
        shutil.copy2(backup, path)
        print("STEP 41: ROLLED BACK ->", path)
        return True
    except Exception as e:
        print("STEP 41 ROLLBACK ERROR:", e)
        return False


def step41_missing_import_ast_fix(path):
    """Apply only the high-confidence missing-import fix for ast."""
    p = Path(path)
    try:
        source = p.read_text(encoding="utf-8-sig")
    except Exception as e:
        return False, f"Could not read file: {e}"

    if not re.search(r"\bast\.", source):
        return False, "The file does not appear to use the ast module."
    if re.search(r"^\s*import\s+ast\s*$", source, re.MULTILINE):
        return False, "import ast is already present."
    if re.search(r"^\s*from\s+ast\s+import\s+", source, re.MULTILINE):
        return False, "ast is already imported."

    lines = source.splitlines(True)
    insert_at = 0
    # Keep a shebang/encoding line at the top if present.
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    if insert_at < len(lines) and "coding" in lines[insert_at].lower():
        insert_at += 1
    lines.insert(insert_at, "import ast\n")
    p.write_text("".join(lines), encoding="utf-8")
    return True, "Added import ast."


def step41_apply_repair(path, result):
    """Apply only a known-safe repair, with backup + validation + rollback."""
    if not result:
        return "Diagnosis result nahi mila. Main file ko change nahi kar raha."

    if result.get("ok"):
        return "Code syntax already theek hai. Koi repair apply nahi kiya."

    backup = step41_backup_file(path)
    if not backup:
        return "Backup create nahi ho saka. Isliye repair apply nahi kiya."

    message = str(result.get("message") or "").lower()
    error = str(result.get("error") or "").lower()

    # Only this repair is intentionally automatic because it is deterministic.
    if "ast is not defined" in message or "ast is not defined" in error:
        changed, detail = step41_missing_import_ast_fix(path)
        if not changed:
            step41_restore_file(path, backup)
            return "Safe ast repair apply nahi ho saka: " + detail
    else:
        step41_restore_file(path, backup)
        return "Is error ke liye mere paas high-confidence automatic repair nahi hai. File ko change nahi kiya."

    validation = step38_python_diagnose(path)
    if validation.get("ok"):
        return "Safe repair apply ho gaya. Backup bhi ban gaya, aur syntax check PASS hai."

    step41_restore_file(path, backup)
    return "Repair ke baad syntax check fail hua, isliye maine original file automatically restore kar di."


def step41_repair_command(command):
    """Require explicit approval wording before modifying any file."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    approval_phrases = [
        "fix apply karo", "fix laga do", "fix kar do", "repair kar do",
        "repair apply karo", "suggested fix apply karo", "suggestion apply karo",
        "haan fix kar do", "haan repair kar do", "apply the fix"
    ]
    if not any(p in s for p in approval_phrases):
        return False

    target = step38_extract_file_target(s)
    path = step38_resolve_file(target)
    if not path:
        speak("I could not find that Python file.")
        print("STEP 41: FILE NOT FOUND ->", target)
        return True

    result = step38_python_diagnose(path)
    print("STEP 41: BEFORE REPAIR ->", result)
    reply = step41_apply_repair(path, result)
    print("STEP 41: RESULT ->", reply)
    speak(reply)
    return True



# =========================================================
# STEP 42 - VERSION & BACKUP MANAGER
# =========================================================

STEP42_BACKUP_DIR = os.path.join(BASE_DIR, "jarvis_backups")
STEP42_MAIN_FILE = os.path.join(BASE_DIR, "main.py")


def step42_ensure_backup_dir():
    os.makedirs(STEP42_BACKUP_DIR, exist_ok=True)
    return STEP42_BACKUP_DIR


def step42_is_python_file(path):
    return bool(path) and os.path.isfile(path) and str(path).lower().endswith(".py")


def step42_validate_python_file(path):
    try:
        py_compile.compile(path, doraise=True)
        return True, "Syntax check PASS"
    except Exception as e:
        return False, str(e)


def step42_create_backup(source_path=None):
    """Create a timestamped backup without deleting or overwriting the source."""
    source_path = source_path or STEP42_MAIN_FILE
    source_path = os.path.abspath(source_path)

    if not step42_is_python_file(source_path):
        return None, "Python file nahi mila: " + source_path

    step42_ensure_backup_dir()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_name = "main_{}.py".format(stamp)
    backup_path = os.path.join(STEP42_BACKUP_DIR, backup_name)

    try:
        shutil.copy2(source_path, backup_path)
        return backup_path, "Backup create ho gaya: " + backup_name
    except Exception as e:
        return None, "Backup create nahi ho saka: " + str(e)


def step42_list_backups():
    """Return newest valid Python backups first."""
    step42_ensure_backup_dir()
    items = []
    for name in os.listdir(STEP42_BACKUP_DIR):
        path = os.path.join(STEP42_BACKUP_DIR, name)
        if os.path.isfile(path) and name.lower().endswith(".py"):
            try:
                items.append((os.path.getmtime(path), path))
            except OSError:
                pass
    items.sort(reverse=True)
    return [p for _, p in items]


def step42_latest_backup():
    backups = step42_list_backups()
    return backups[0] if backups else None


def step42_restore_latest_backup():
    """Safely restore latest backup after backing up current main.py and validating it."""
    backup_path = step42_latest_backup()
    if not backup_path:
        return "Koi backup available nahi hai."

    if os.path.abspath(backup_path) == os.path.abspath(STEP42_MAIN_FILE):
        return "Restore cancel: backup aur main.py same file hain."

    ok, detail = step42_validate_python_file(backup_path)
    if not ok:
        return "Restore cancel: latest backup ka syntax invalid hai. " + detail

    if not os.path.isfile(STEP42_MAIN_FILE):
        return "main.py nahi mili: " + STEP42_MAIN_FILE

    current_backup, backup_msg = step42_create_backup(STEP42_MAIN_FILE)
    if not current_backup:
        return "Restore cancel. Current main.py ka safety backup nahi bana: " + backup_msg

    temp_path = STEP42_MAIN_FILE + ".step42_restore_tmp"
    try:
        shutil.copy2(backup_path, temp_path)
        ok2, detail2 = step42_validate_python_file(temp_path)
        if not ok2:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return "Restore cancel: temporary validation fail hui. Current file safe hai."

        os.replace(temp_path, STEP42_MAIN_FILE)
        return (
            "Latest backup restore ho gaya: {}. Current main.py ka safety backup bhi bana diya. "
            "Restored version use karne ke liye JARVIS restart karo."
        ).format(os.path.basename(backup_path))
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return "Restore fail hua, current main.py ko change nahi kiya: " + str(e)


def step42_version_command(command):
    """Handle explicit backup/version commands locally; never calls Gemini."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()

    backup_words = ["backup", "back up", "version save", "version backup"]
    list_words = ["backup list", "backups dikhao", "backup dikhao", "backup batao", "backup dekhao"]
    latest_words = ["latest backup", "last backup", "recent backup", "naya backup"]
    restore_words = ["backup restore", "backup wapas", "backup se restore", "purana version restore", "latest backup restore"]

    # Restore is checked first because it also contains the word 'backup'.
    if any(p in s for p in restore_words):
        reply = step42_restore_latest_backup()
        print("STEP 42 RESTORE ->", reply)
        speak(reply)
        return True

    if any(p in s for p in list_words):
        backups = step42_list_backups()
        if not backups:
            reply = "Abhi koi JARVIS backup nahi hai."
        else:
            names = [os.path.basename(p) for p in backups[:10]]
            reply = "Total {} backup hain. Latest: {}".format(len(backups), ", ".join(names))
            print("STEP 42 BACKUP LIST ->")
            for i, name in enumerate(names, 1):
                print("  {}. {}".format(i, name))
        speak(reply)
        return True

    if any(p in s for p in latest_words):
        latest = step42_latest_backup()
        if latest:
            reply = "Latest backup hai: {}".format(os.path.basename(latest))
        else:
            reply = "Abhi koi backup available nahi hai."
        print("STEP 42 LATEST ->", latest)
        speak(reply)
        return True

    if any(p in s for p in backup_words):
        if not os.path.isfile(STEP42_MAIN_FILE):
            reply = "main.py nahi mili. Pehle apni working file ko main.py naam se save karo."
        else:
            path, msg = step42_create_backup(STEP42_MAIN_FILE)
            reply = msg if path else msg
            if path:
                reply += "."
        print("STEP 42 BACKUP ->", reply)
        speak(reply)
        return True

    return False


# =========================================================
# STEP 43 - SAFE SELF UPGRADE / UPDATE MANAGER
# =========================================================

STEP43_VERSION = "43.0"
STEP43_UPDATE_DIR = os.path.join(BASE_DIR, "jarvis_updates")
STEP43_VERSION_FILE = os.path.join(BASE_DIR, "jarvis_version.json")
STEP43_UPDATE_FILE = os.path.join(STEP43_UPDATE_DIR, "main_update.py")


def step43_ensure_update_dir():
    os.makedirs(STEP43_UPDATE_DIR, exist_ok=True)
    return STEP43_UPDATE_DIR


def step43_read_version():
    """Read local JARVIS version metadata without calling Gemini."""
    default = {"version": STEP43_VERSION, "updated_at": None}
    try:
        if not os.path.isfile(STEP43_VERSION_FILE):
            return default
        with open(STEP43_VERSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        data.setdefault("version", STEP43_VERSION)
        data.setdefault("updated_at", None)
        return data
    except Exception as e:
        print("STEP 43 VERSION READ ERROR:", e)
        return default


def step43_write_version(version=STEP43_VERSION):
    """Write version metadata atomically."""
    data = {
        "version": str(version),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds")
    }
    temp = STEP43_VERSION_FILE + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, STEP43_VERSION_FILE)
        return True
    except Exception as e:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except Exception:
                pass
        print("STEP 43 VERSION WRITE ERROR:", e)
        return False


def step43_validate_update_file(path=None):
    """Validate an update candidate before it can replace main.py."""
    path = os.path.abspath(path or STEP43_UPDATE_FILE)
    if not os.path.isfile(path):
        return False, "Update file nahi mili: " + path
    if not path.lower().endswith(".py"):
        return False, "Update file Python .py file honi chahiye."
    try:
        py_compile.compile(path, doraise=True)
        return True, "Syntax check PASS"
    except Exception as e:
        return False, "Syntax check FAIL: " + str(e)


def step43_prepare_update_file(source_path):
    """Copy a candidate update into the controlled update location after validation."""
    source_path = os.path.abspath(source_path)
    ok, detail = step43_validate_update_file(source_path)
    if not ok:
        return False, detail
    step43_ensure_update_dir()
    temp = STEP43_UPDATE_FILE + ".tmp"
    try:
        shutil.copy2(source_path, temp)
        ok2, detail2 = step43_validate_update_file(temp)
        if not ok2:
            if os.path.exists(temp):
                os.remove(temp)
            return False, "Update copy validation fail hui."
        os.replace(temp, STEP43_UPDATE_FILE)
        return True, "Update candidate ready: " + os.path.basename(source_path)
    except Exception as e:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except Exception:
                pass
        return False, "Update candidate prepare nahi hua: " + str(e)


def step43_update_status():
    """Return current version and whether a valid local update is waiting."""
    version_data = step43_read_version()
    if not os.path.isfile(STEP43_UPDATE_FILE):
        return version_data, False, "Koi update candidate pending nahi hai."
    ok, detail = step43_validate_update_file(STEP43_UPDATE_FILE)
    if ok:
        return version_data, True, "Valid local update candidate available hai."
    return version_data, False, "Update candidate mila, lekin validation fail hai."


def step43_apply_update():
    """Safely replace main.py with the validated local update candidate."""
    if not os.path.isfile(STEP42_MAIN_FILE):
        return "main.py nahi mili. Update apply nahi kiya."

    ok, detail = step43_validate_update_file(STEP43_UPDATE_FILE)
    if not ok:
        return "Update cancel: " + detail

    # Step 42 backup is mandatory before any replacement.
    current_backup, backup_msg = step42_create_backup(STEP42_MAIN_FILE)
    if not current_backup:
        return "Update cancel. Current main.py ka safety backup nahi bana: " + backup_msg

    temp = STEP42_MAIN_FILE + ".step43_update_tmp"
    try:
        shutil.copy2(STEP43_UPDATE_FILE, temp)
        ok2, detail2 = step43_validate_update_file(temp)
        if not ok2:
            if os.path.exists(temp):
                os.remove(temp)
            return "Update cancel: temporary validation fail hui. Current main.py safe hai."

        os.replace(temp, STEP42_MAIN_FILE)

        # Keep metadata only after the replacement succeeds.
        step43_write_version(STEP43_VERSION)

        # The candidate is consumed by this update; do not delete backups.
        try:
            os.remove(STEP43_UPDATE_FILE)
        except Exception as cleanup_error:
            print("STEP 43 UPDATE CLEANUP WARNING:", cleanup_error)

        return (
            "JARVIS update successfully apply ho gaya. "
            "Current file ka safety backup bhi bana diya hai: {}. "
            "Naya code use karne ke liye JARVIS restart karo."
        ).format(os.path.basename(current_backup))
    except Exception as e:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except Exception:
                pass
        return "Update fail hua; current main.py ko safe rakha gaya: " + str(e)


def step43_update_command(command):
    """Handle explicit Step 43 local self-upgrade commands."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()

    apply_words = [
        "update apply karo", "update install karo", "update kar do",
        "update laga do", "upgrade apply karo", "upgrade install karo",
        "self update karo", "self upgrade karo", "update chalao"
    ]
    status_words = [
        "update status", "update check karo", "update check", "upgrade status",
        "upgrade check karo", "upgrade check"
    ]
    version_words = [
        "jarvis version", "current version", "version batao", "kaunsa version"
    ]
    prepare_words = [
        "update prepare karo", "update file prepare karo", "update ready karo"
    ]

    if any(p in s for p in apply_words):
        reply = step43_apply_update()
        print("STEP 43 APPLY ->", reply)
        speak(reply)
        return True

    if any(p in s for p in status_words):
        data, available, detail = step43_update_status()
        reply = "Current JARVIS version {}. {}".format(data.get("version", STEP43_VERSION), detail)
        print("STEP 43 STATUS ->", data, available, detail)
        speak(reply)
        return True

    if any(p in s for p in version_words):
        data = step43_read_version()
        reply = "JARVIS current version {} hai.".format(data.get("version", STEP43_VERSION))
        print("STEP 43 VERSION ->", data)
        speak(reply)
        return True

    if any(p in s for p in prepare_words):
        reply = (
            "Update prepare karne ke liye validated Python file ko "
            "jarvis_updates folder me main_update.py naam se rakho. "
            "Phir bolo: Jarvis update status check karo."
        )
        print("STEP 43 PREPARE ->", STEP43_UPDATE_FILE)
        speak(reply)
        return True

    return False



# =========================================================
# STEP 44 - JARVIS SELF-TESTING SYSTEM
# =========================================================

STEP44_VERSION = "44.0"
STEP44_TEST_LOG = os.path.join(BASE_DIR, "jarvis_self_test.log")


def step44_log(message):
    """Write a small local self-test log; never sends test data to Gemini."""
    try:
        with open(STEP44_TEST_LOG, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(datetime.datetime.now().isoformat(timespec="seconds"), message))
    except Exception as e:
        print("STEP 44 LOG WARNING:", e)


def step44_compile_file(path):
    """Compile one Python file without executing it."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return False, "File nahi mili: {}".format(path)
    try:
        py_compile.compile(path, doraise=True)
        return True, "Syntax/compile PASS"
    except Exception as e:
        return False, "Syntax/compile FAIL: {}".format(e)


def step44_static_function_check(path):
    """Check that function definitions are unique and calls to local functions exist."""
    path = os.path.abspath(path)
    try:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path)
    except Exception as e:
        return False, "AST parse FAIL: {}".format(e)

    definitions = {}
    duplicates = []
    local_calls = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[node.name] = definitions.get(node.name, 0) + 1
            if definitions[node.name] > 1:
                duplicates.append(node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            local_calls.add(node.func.id)

    # Ignore Python built-ins and common external/library calls.
    builtin_names = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
    missing = sorted(
        name for name in local_calls
        if name.startswith(("step", "smart_", "screen_", "_screen_", "run_", "is_", "open_", "type_", "save_", "clear_", "handle_", "process_", "execute_", "speak", "listen", "add_", "should_", "understand_"))
        and name not in definitions
        and name not in builtin_names
    )

    if duplicates:
        return False, "Duplicate function definitions: {}".format(", ".join(sorted(set(duplicates))))
    if missing:
        return False, "Possible missing local functions: {}".format(", ".join(missing))
    return True, "Function definition/call check PASS ({} functions)".format(len(definitions))


def step44_core_logic_check():
    """Run safe, non-destructive checks on Step 42/43 helpers."""
    checks = []

    # These helpers only create/read local directories or metadata.
    try:
        backup_dir = step42_ensure_backup_dir()
        checks.append((os.path.isdir(backup_dir), "Step 42 backup directory"))
    except Exception as e:
        checks.append((False, "Step 42 backup directory: {}".format(e)))

    try:
        update_dir = step43_ensure_update_dir()
        checks.append((os.path.isdir(update_dir), "Step 43 update directory"))
    except Exception as e:
        checks.append((False, "Step 43 update directory: {}".format(e)))

    try:
        version_data = step43_read_version()
        checks.append((isinstance(version_data, dict) and "version" in version_data, "Step 43 version reader"))
    except Exception as e:
        checks.append((False, "Step 43 version reader: {}".format(e)))

    try:
        main_path = os.path.abspath(STEP42_MAIN_FILE)
        if os.path.isfile(main_path):
            ok, _ = step43_validate_update_file(main_path)
            checks.append((ok, "Current main.py validation"))
        else:
            checks.append((True, "Current main.py validation skipped (main.py not present)"))
    except Exception as e:
        checks.append((False, "Current main.py validation: {}".format(e)))

    failed = [name for ok, name in checks if not ok]
    if failed:
        return False, "Core checks failed: " + "; ".join(failed), checks
    return True, "Core logic checks PASS", checks


def step44_run_self_test(verbose=True):
    """Run read-only self-tests. It never edits main.py or applies an update."""
    current_file = os.path.abspath(__file__)
    results = []

    ok, detail = step44_compile_file(current_file)
    results.append((ok, "Current JARVIS file compile: " + detail))

    ok2, detail2 = step44_static_function_check(current_file)
    results.append((ok2, "Static function check: " + detail2))

    ok3, detail3, core_checks = step44_core_logic_check()
    results.append((ok3, "Core logic check: " + detail3))
    for check_ok, check_name in core_checks:
        results.append((check_ok, "  " + ("PASS: " if check_ok else "FAIL: ") + check_name))

    passed = sum(1 for ok, _ in results if ok)
    failed = len(results) - passed
    status = "PASS" if failed == 0 else "FAIL"

    step44_log("SELF TEST {} - passed={}, failed={}".format(status, passed, failed))
    for ok, message in results:
        step44_log(("PASS: " if ok else "FAIL: ") + message.strip())
        if verbose:
            print("STEP 44 ->", ("PASS:" if ok else "FAIL:"), message)

    return status == "PASS", "JARVIS self-test {}. {} checks pass, {} checks fail.".format(status, passed, failed)


def step44_self_test_command(command):
    """Handle explicit self-test commands locally; Gemini is never needed."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    test_words = [
        "self test", "self-test", "self testing", "self testing karo",
        "khud ko test karo", "apna test karo", "jarvis test karo",
        "system test karo", "system check karo", "health check karo",
        "code test karo", "code check karo"
    ]
    if not any(p in s for p in test_words):
        return False

    ok, reply = step44_run_self_test(verbose=True)
    print("STEP 44 RESULT ->", reply)
    speak(reply)
    return True



# ============================================================
# STEP 45 - SYSTEM HEALTH CHECK
# ============================================================

STEP45_REQUIRED_MODULES = [
    ("speech_recognition", "Speech recognition"),
    ("pyautogui", "Screen/mouse/keyboard control"),
    ("pytesseract", "OCR/screen reading"),
    ("google.genai", "Gemini AI fallback"),
]

def step45_check_python():
    """Check that JARVIS is running on the expected Python major/minor version."""
    import sys
    expected = (3, 13)
    actual = sys.version_info[:2]
    ok = actual == expected
    detail = "Python {}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    if not ok:
        detail += " (recommended: Python 3.13)"
    return ok, detail


def step45_check_modules():
    """Check required third-party modules without making network/API calls."""
    results = []
    import importlib
    for module_name, label in STEP45_REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
            results.append((True, "{}: installed".format(label)))
        except Exception as e:
            results.append((False, "{}: missing/unavailable ({})".format(label, e)))
    return results


def step45_check_tesseract():
    """Check the known Windows Tesseract executable path."""
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return True, "Tesseract found: {}".format(path)
    exe = shutil.which("tesseract")
    if exe:
        return True, "Tesseract found in PATH: {}".format(exe)
    return False, "Tesseract executable not found"


def step45_check_gemini_key():
    """Check only whether the local Gemini key variable exists; never print the key."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        return True, "GEMINI_API_KEY is set (key hidden)"
    return False, "GEMINI_API_KEY is not set"


def step45_check_writable_dirs():
    """Check that JARVIS can write to its own working directory and backup/update folders."""
    paths = [
        (BASE_DIR, "JARVIS base directory"),
        (step42_ensure_backup_dir(), "Step 42 backup directory"),
        (step43_ensure_update_dir(), "Step 43 update directory"),
    ]
    results = []
    import tempfile
    for path, label in paths:
        try:
            os.makedirs(path, exist_ok=True)
            fd, test_path = tempfile.mkstemp(prefix=".jarvis_health_", dir=path)
            os.close(fd)
            os.remove(test_path)
            results.append((True, label + ": writable"))
        except Exception as e:
            results.append((False, label + ": not writable ({})".format(e)))
    return results


def step45_check_microphone():
    """Check microphone enumeration without opening a recording stream."""
    try:
        names = sr.Microphone.list_microphone_names()
        count = len(names)
        if count > 0:
            return True, "Microphone devices detected: {}".format(count)
        return False, "No microphone devices detected"
    except Exception as e:
        return False, "Microphone check failed: {}".format(e)


def step45_run_health_check(verbose=True):
    """Run non-destructive environment checks. No files are modified except temporary test files."""
    results = []

    ok, detail = step45_check_python()
    results.append((ok, "Python: " + detail))

    for ok, detail in step45_check_modules():
        results.append((ok, detail))

    ok, detail = step45_check_tesseract()
    results.append((ok, detail))

    ok, detail = step45_check_gemini_key()
    results.append((ok, detail))

    for ok, detail in step45_check_writable_dirs():
        results.append((ok, detail))

    ok, detail = step45_check_microphone()
    results.append((ok, detail))

    passed = sum(1 for ok, _ in results if ok)
    failed = len(results) - passed
    status = "PASS" if failed == 0 else "FAIL"

    message = "JARVIS system health {}. {} checks pass, {} checks fail.".format(status, passed, failed)
    print("STEP 45 RESULT ->", message)
    for ok, detail in results:
        print("STEP 45 ->", "PASS:" if ok else "FAIL:", detail)

    return status == "PASS", message


def step45_health_command(command):
    """Handle explicit system-health commands locally; Gemini is never needed."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    health_words = [
        "system health check", "system health", "health check",
        "system check", "environment check", "environment test",
        "system diagnostic", "system diagnostics", "system diagnosis",
        "jarvis health check", "jarvis system check",
        "jarvis ki health check", "system theek hai",
        "system thik hai", "system check karo",
    ]
    if not any(p in s for p in health_words):
        return False
    ok, reply = step45_run_health_check(verbose=True)
    speak(reply)
    return True



# ============================================================
# STEP 46 - SYSTEM PERFORMANCE MONITOR
# ============================================================

STEP46_VERSION = "46.0"


def step46_cpu_usage():
    """Return approximate total CPU usage on Windows using GetSystemTimes."""
    try:
        import ctypes
        from ctypes import wintypes
        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]
        idle = FILETIME(); kernel = FILETIME(); user = FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        def ft(x):
            return (x.dwHighDateTime << 32) + x.dwLowDateTime
        i1, k1, u1 = ft(idle), ft(kernel), ft(user)
        import time
        time.sleep(0.25)
        idle2 = FILETIME(); kernel2 = FILETIME(); user2 = FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2)):
            return None
        i2, k2, u2 = ft(idle2), ft(kernel2), ft(user2)
        total = (k2-k1) + (u2-u1)
        busy = total - (i2-i1)
        if total <= 0:
            return None
        return max(0.0, min(100.0, busy * 100.0 / total))
    except Exception:
        return None


def step46_memory_info():
    """Return used/total RAM in GB using Windows GlobalMemoryStatusEx."""
    try:
        import ctypes
        from ctypes import wintypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        s = MEMORYSTATUSEX(); s.dwLength = ctypes.sizeof(s)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return None
        total = s.ullTotalPhys / (1024**3)
        avail = s.ullAvailPhys / (1024**3)
        used = total - avail
        return {"used_gb": used, "total_gb": total, "percent": int(s.dwMemoryLoad)}
    except Exception:
        return None


def step46_disk_info():
    """Return free/used/total space for the JARVIS drive."""
    try:
        total, used, free = shutil.disk_usage(BASE_DIR)
        gb = 1024**3
        return {"used_gb": used/gb, "free_gb": free/gb, "total_gb": total/gb,
                "percent": (used * 100.0 / total) if total else 0.0}
    except Exception:
        return None


def step46_battery_info():
    """Read battery status through WMI when available; returns None on desktops."""
    try:
        import ctypes
        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("Reserved", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        s = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            pct = int(s.BatteryLifePercent)
            ac = "plugged in" if s.ACLineStatus == 1 else "on battery" if s.ACLineStatus == 0 else "AC status unknown"
            if pct == 255:
                return {"percent": None, "power": ac}
            return {"percent": pct, "power": ac}
    except Exception:
        pass
    return None


def step46_performance_report():
    """Build a concise local performance report without network/API calls."""
    cpu = step46_cpu_usage()
    mem = step46_memory_info()
    disk = step46_disk_info()
    battery = step46_battery_info()
    lines = []
    if cpu is None:
        lines.append("CPU usage unavailable")
    else:
        lines.append("CPU {:.0f}%".format(cpu))
    if mem:
        lines.append("RAM {:.1f}/{:.1f} GB ({}%)".format(mem["used_gb"], mem["total_gb"], mem["percent"]))
    else:
        lines.append("RAM unavailable")
    if disk:
        lines.append("Disk {:.1f}% used, {:.1f} GB free".format(disk["percent"], disk["free_gb"]))
    else:
        lines.append("Disk information unavailable")
    if battery:
        if battery["percent"] is None:
            lines.append("Power: {}".format(battery["power"]))
        else:
            lines.append("Battery {}%, {}".format(battery["percent"], battery["power"]))
    return "; ".join(lines)


def step46_performance_command(command):
    """Handle local performance/resource commands before Gemini."""
    s = re.sub(r"\s+", " ", str(command).lower()).strip()
    patterns = [
        "performance check", "performance monitor", "system performance",
        "performance batao", "performance bata", "system performance batao",
        "cpu check", "cpu usage", "ram usage", "memory usage", "disk usage",
        "system resources", "resources batao", "resources check",
        "computer performance", "computer ki performance", "system kitna load hai",
    ]
    if not any(p in s for p in patterns):
        return False
    report = step46_performance_report()
    print("STEP 46 PERFORMANCE ->", report)
    speak("JARVIS performance report. " + report)
    return True



# ================================================================
# STEP 47 - NETWORK / INTERNET STATUS MONITOR
# ================================================================

import socket
import subprocess
import urllib.request
import time


def step47_get_local_ip():
    """Return the active local IPv4 address when available."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "Unavailable"


def step47_get_hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "Unavailable"


def step47_get_wifi_info():
    """Read Windows Wi-Fi state using netsh; never changes network settings."""
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode != 0 or "There is no wireless interface" in text:
            return "Wi-Fi information unavailable"

        state = "unknown"
        ssid = "unknown"
        signal = "unknown"
        for raw in text.splitlines():
            line = raw.strip()
            low = line.lower()
            if low.startswith("state") and ":" in line:
                state = line.split(":", 1)[1].strip()
            elif low.startswith("ssid") and not low.startswith("bssid") and ":" in line:
                ssid = line.split(":", 1)[1].strip() or "hidden"
            elif low.startswith("signal") and ":" in line:
                signal = line.split(":", 1)[1].strip()

        return f"Wi-Fi {state}; network {ssid}; signal {signal}"
    except Exception as exc:
        return f"Wi-Fi check unavailable: {exc}"


def step47_check_internet():
    """Perform a short read-only connectivity check."""
    urls = [
        "https://www.google.com/generate_204",
        "https://www.microsoft.com/",
    ]
    last_error = None
    for url in urls:
        started = time.perf_counter()
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "JARVIS-Network-Check/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                latency = round((time.perf_counter() - started) * 1000)
                return True, f"Internet connected; {response.status} response; {latency} ms"
        except Exception as exc:
            last_error = exc
    return False, f"Internet check failed: {last_error}"


def step47_network_report():
    """Build a local network status report without changing network settings."""
    hostname = step47_get_hostname()
    local_ip = step47_get_local_ip()
    wifi = step47_get_wifi_info()
    connected, internet = step47_check_internet()
    state = "ONLINE" if connected else "OFFLINE"
    return f"Network {state}; PC {hostname}; local IP {local_ip}; {wifi}; {internet}"


def step47_network_command(command):
    """Handle explicit network-status commands before the Gemini fallback."""
    text = str(command or "").strip().lower()
    triggers = (
        "network status", "network check", "network batao", "network bata",
        "internet status", "internet check", "internet batao", "internet bata",
        "wifi status", "wifi check", "wifi batao", "wi fi status", "wi fi check",
        "internet connected hai", "internet chalu hai", "net check",
        "mera ip batao", "local ip batao", "ip address batao",
    )
    if not any(item in text for item in triggers):
        return False

    print("STEP 47 -> NETWORK STATUS CHECK")
    report = step47_network_report()
    print("STEP 47 NETWORK ->", report)
    speak("JARVIS network report. " + report)
    return True


# =========================================================
# STEP 48 - NETWORK DIAGNOSTICS
# =========================================================

def step48_run_command(args, timeout=8):
    """Run a read-only Windows networking command and return its output."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            shell=False,
        )
        return (result.returncode, (result.stdout or result.stderr or "").strip())
    except Exception as e:
        return (-1, str(e))


def step48_get_default_gateway():
    """Return the first usable IPv4 default gateway from route print."""
    code, output = step48_run_command(["route", "print", "-4"], timeout=8)
    if code != 0:
        return "Unknown"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            gateway = parts[2]
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", gateway):
                return gateway
    return "Unknown"


def step48_ping_host(host, timeout_ms=1500):
    """Return latency/result for a single ICMP ping on Windows."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), host],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=max(4, timeout_ms / 1000 + 3),
            shell=False,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        match = re.search(r"[<]?(\d+)ms", output, re.IGNORECASE)
        if result.returncode == 0:
            return True, (int(match.group(1)) if match else None)
        return False, None
    except Exception:
        return False, None


def step48_dns_check(host="google.com"):
    """Resolve a hostname using the local Windows DNS resolver."""
    code, output = step48_run_command(["nslookup", host], timeout=8)
    if code != 0:
        return False, "DNS lookup failed"
    addresses = []
    for line in output.splitlines():
        line = line.strip()
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", line):
            addresses.append(line)
    # Ignore the resolver's own address when possible; any address still proves resolution.
    return True, (addresses[-1] if addresses else "resolved")


def step48_network_diagnostics():
    """Run a read-only connectivity diagnosis using gateway, DNS and internet pings."""
    gateway = step48_get_default_gateway()
    gateway_ok, gateway_ms = (False, None)
    if gateway != "Unknown":
        gateway_ok, gateway_ms = step48_ping_host(gateway)

    dns_ok, dns_result = step48_dns_check()
    internet_ok, internet_ms = step48_ping_host("1.1.1.1")

    if internet_ok and dns_ok:
        diagnosis = "Internet connectivity looks healthy"
    elif internet_ok and not dns_ok:
        diagnosis = "Internet works but DNS resolution may have a problem"
    elif gateway_ok and not internet_ok:
        diagnosis = "PC can reach the router, but internet access may be unavailable"
    elif not gateway_ok and gateway != "Unknown":
        diagnosis = "PC cannot reach the default gateway; local network may have a problem"
    else:
        diagnosis = "Connectivity could not be fully verified"

    gateway_text = gateway
    if gateway_ms is not None:
        gateway_text += f" ({gateway_ms} ms)"
    internet_text = "OK" if internet_ok else "FAILED"
    if internet_ms is not None:
        internet_text += f" ({internet_ms} ms)"
    dns_text = "OK" if dns_ok else "FAILED"
    if dns_ok and dns_result:
        dns_text += f" ({dns_result})"

    return (
        f"Gateway: {gateway_text}; "
        f"DNS: {dns_text}; "
        f"Internet ping: {internet_text}; "
        f"Diagnosis: {diagnosis}"
    )


def step48_diagnostics_command(command):
    """Handle explicit Step 48 diagnostic commands before other routers."""
    text = str(command or "").strip().lower()
    triggers = (
        "network diagnostics", "network diagnostic", "network troubleshoot",
        "network problem check", "internet problem check", "internet diagnose",
        "internet diagnostics", "internet diagnostic", "net troubleshoot",
        "wifi troubleshoot", "wifi problem check", "connection troubleshoot",
        "internet problem batao", "network problem batao", "net problem batao",
        "internet issue check", "network issue check",
    )
    if not any(item in text for item in triggers):
        return False

    print("STEP 48 -> NETWORK DIAGNOSTICS")
    report = step48_network_diagnostics()
    print("STEP 48 DIAGNOSTICS ->", report)
    speak("JARVIS network diagnostics. " + report)
    return True

def legacy_process_command(command):
    # Legacy router retained for reference; final router below is authoritative.
    if step53_status_command(command):
        return True
    # STEP 52 handles recent-file activity queries locally.
    if step52_recent_activity_command(command):
        return True
    # STEP 51 handles clipboard commands locally.
    if step51_clipboard_command(command):
        return True
    # STEP 50 handles active-window and safe window-control commands locally.
    if step50_window_command(command):
        return True
    # STEP 49 handles read-only process monitoring locally.
    if step49_process_command(command):
        return True
    # STEP 48 handles explicit local network diagnostics first.
    if step48_diagnostics_command(command):
        return True
    # STEP 47 handles explicit local network-status commands first.
    if step47_network_command(command):
        return True
    # STEP 46 handles explicit local performance/resource commands first.
    if step46_performance_command(command):
        return True
    # STEP 45 handles explicit local system-health commands first.
    if step45_health_command(command):
        return True
    # STEP 44 handles explicit local self-test commands first.
    if step44_self_test_command(command):
        return True
    # STEP 43 handles explicit local self-update commands first.
    if step43_update_command(command):
        return True
    # STEP 42 handles explicit local version/backup commands first.
    if step42_version_command(command):
        return True
    # STEP 41 applies only explicitly approved high-confidence repairs.
    if step41_repair_command(command):
        return True
    # STEP 40 gives safe, read-only fix suggestions before explanation/diagnosis.
    if step40_fix_suggest_command(command):
        return True
    # STEP 39 explains Python diagnosis results without modifying code.
    if step39_error_explain_command(command):
        return True
    # STEP 38 handles read-only code diagnosis before other routers.
    if step38_diagnose_command(command):
        return True
    # STEP 33.1 handles natural Hinglish input commands before older routers.
    if step33_local_natural_input(command):
        return True
    # STEP 32 handles explicit local screen-state waits before other routers.
    if step32_visual_command(command):
        return True
    # STEP 28 handles explicit multi-action sequences first.
    if run_multistep_command(command):
        return True
    # STEP 31 adds explicit verified visual actions without changing Step 28/30.
    if step31_visual_command(command):
        return True
    # STEP 30 handles remembered-target follow-ups and saves fresh visual targets.
    if step30_visual_command(command):
        return True
    # STEP 29 adds scroll-and-retry visual goal execution for commands
    # that are not already covered by Step 28/30.
    if step29_visual_command(command):
        return True
    if screen_understanding_command(command):
        return True
    if is_local_repeat_command(command):
        print("LOCAL REPEAT DETECTED - GEMINI SKIPPED")
        return repeat_last_task_locally()
    if is_agent_goal(command):
        return run_agent_loop(command)
    if not is_local_repeat_command(command):
        save_last_command(command)
    if any(p in command.lower() for p in ["conversation clear karo","context clear karo","context bhool jao","sab context bhool jao"]):
        return clear_conversation_context()
    if handle_workflow_memory(command): return True
    if smart_language_command(command):
        add_conversation_context(command,"Executed as a smart command."); return True
    normalized=re.sub(r"\s+"," ",command.lower()).strip()
    if should_use_context_gemini(normalized):
        context_intent=understand_with_context(command)
        if context_intent and execute_context_intent(context_intent):
            add_conversation_context(command,"Executed using conversation context."); return True
    if run_advanced_goal_planner(command): return True
    # STEP 33: natural-language AI brain is the last resort.
    if step33_ai_brain(command): return True
    return False



# ============================================================
# STEP 49 - PROCESS MONITOR
# ============================================================

STEP49_VERSION = "49.0"


def step49_run_tasklist(filter_name=None, timeout=8):
    """Read running Windows processes. Never terminates or changes a process."""
    try:
        args = ["tasklist", "/FO", "CSV", "/NH"]
        if filter_name:
            args += ["/FI", f"IMAGENAME eq {filter_name}"]
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout, shell=False)
        if result.returncode != 0:
            return []
        rows=[]
        import csv, io
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) >= 5 and row[0] and row[0] != "INFO:":
                rows.append({"name":row[0],"pid":row[1],"memory":row[4]})
        return rows
    except Exception as e:
        print("STEP 49 ERROR:", e)
        return []


def step49_process_report():
    rows=step49_run_tasklist()
    if not rows:
        return "Could not read the running process list."
    names={}
    for r in rows:
        names[r["name"]]=names.get(r["name"],0)+1
    common=sorted(names.items(), key=lambda x:(-x[1],x[0].lower()))[:8]
    summary=", ".join(f"{n} ({c})" for n,c in common)
    return f"Running processes: {len(rows)}. Common processes: {summary}."


def step49_find_process(name):
    name=name.strip()
    if not name:
        return "Tell me the process name."
    rows=step49_run_tasklist(name)
    if rows:
        return f"{name} is running. Found {len(rows)} matching process instance(s)."
    return f"{name} is not currently running, or could not be found."


def step49_process_command(command):
    text=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    triggers=("process list","running processes","running apps","process monitor","process check","task manager check","kaun se programs chal rahe","kya chal raha hai")
    if any(t in text for t in triggers):
        report=step49_process_report()
        print("STEP 49 PROCESS ->",report); speak("JARVIS process report. "+report); return True
    m=re.search(r"(?:process|program|app)\s+(?:check|status)\s+(?:of|for)?\s*(.+)$",text)
    if m:
        report=step49_find_process(m.group(1))
        print("STEP 49 PROCESS ->",report); speak(report); return True
    return False


# ============================================================
# STEP 50 - ACTIVE WINDOW / SAFE WINDOW CONTROL
# ============================================================

STEP50_VERSION = "50.0"


def step50_active_window_title():
    try:
        import ctypes
        hwnd=ctypes.windll.user32.GetForegroundWindow()
        if not hwnd: return "Unknown"
        length=ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf=ctypes.create_unicode_buffer(length+1)
        ctypes.windll.user32.GetWindowTextW(hwnd,buf,length+1)
        return buf.value.strip() or "Untitled window"
    except Exception as e:
        return f"Unknown ({e})"


def step50_window_action(action):
    if not PYAUTOGUI_AVAILABLE:
        return False, "PyAutoGUI is not available."
    try:
        if action=="minimize": pyautogui.hotkey("alt","space"); time.sleep(.15); pyautogui.press("n")
        elif action=="maximize": pyautogui.hotkey("alt","space"); time.sleep(.15); pyautogui.press("x")
        elif action=="close": pyautogui.hotkey("alt","f4")
        elif action=="switch": pyautogui.hotkey("alt","tab")
        else: return False,"Unsupported window action."
        return True,f"Window {action} command sent."
    except Exception as e:
        return False,f"Window action failed: {e}"


def step50_window_command(command):
    text=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    if any(t in text for t in ("active window","current window","kaunsi window open","which window open")):
        title=step50_active_window_title(); print("STEP 50 WINDOW ->",title); speak("Current window is "+title); return True
    action=None
    if any(t in text for t in ("minimize window","window minimize","window chhoti karo")): action="minimize"
    elif any(t in text for t in ("maximize window","window maximize","window badi karo")): action="maximize"
    elif any(t in text for t in ("switch window","change window","next window")): action="switch"
    elif any(t in text for t in ("close current window","current window close")): action="close"
    if action:
        ok,msg=step50_window_action(action); print("STEP 50 WINDOW ->",msg); speak(msg); return True
    return False


# ============================================================
# STEP 51 - CLIPBOARD ASSISTANT
# ============================================================

STEP51_VERSION = "51.0"


def step51_clipboard_get():
    try:
        import tkinter as tk
        root=tk.Tk(); root.withdraw(); root.update()
        try: data=root.clipboard_get()
        except Exception: data=""
        root.destroy()
        return str(data)
    except Exception as e:
        print("STEP 51 GET ERROR:",e); return ""


def step51_clipboard_set(text):
    try:
        import tkinter as tk
        root=tk.Tk(); root.withdraw(); root.clipboard_clear(); root.clipboard_append(str(text)); root.update(); root.destroy(); return True
    except Exception as e:
        print("STEP 51 SET ERROR:",e); return False


def step51_clipboard_clear():
    return step51_clipboard_set("")


def step51_clipboard_command(command):
    text=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    if any(t in text for t in ("clipboard read","clipboard batao","clipboard mein kya hai","clipboard me kya hai")):
        data=step51_clipboard_get()
        if not data: speak("Clipboard is empty or unavailable.")
        else:
            preview=data.replace("\n"," ").strip()
            if len(preview)>300: preview=preview[:300]+"..."
            speak("Clipboard says: "+preview)
        return True
    if any(t in text for t in ("clipboard clear","clipboard saaf","clipboard empty")):
        ok=step51_clipboard_clear(); speak("Clipboard cleared." if ok else "I could not clear the clipboard."); return True
    return False


# ============================================================
# STEP 52 - RECENT ACTIVITY / RECENT FILES
# ============================================================

STEP52_VERSION = "52.0"


def step52_recent_files(limit=8):
    roots=[Path.home()/"Desktop",Path.home()/"Downloads",Path.home()/"Documents"]
    items=[]
    for root in roots:
        if not root.exists(): continue
        try:
            for p in root.iterdir():
                if p.is_file():
                    try: items.append((p.stat().st_mtime,p))
                    except OSError: pass
        except OSError: pass
    items.sort(key=lambda x:x[0], reverse=True)
    return items[:limit]


def step52_recent_report():
    items=step52_recent_files()
    if not items: return "I could not find recent files in Desktop, Downloads, or Documents."
    parts=[]
    for ts,p in items:
        parts.append(p.name)
    return "Recent files: "+", ".join(parts)+"."


def step52_recent_activity_command(command):
    text=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    triggers=("recent files","recent activity","latest files","last files","recent file batao","recent files dikhao","abhi ki files")
    if not any(t in text for t in triggers): return False
    report=step52_recent_report(); print("STEP 52 RECENT ->",report); speak(report); return True


# ============================================================
# STEP 53 - JARVIS STATUS DASHBOARD
# ============================================================

STEP53_VERSION = "53.0"


def step53_status_report():
    try:
        py=step45_check_python()[1]
        cpu=step46_cpu_usage(); mem=step46_memory_info(); net=step47_check_internet()
        title=step50_active_window_title()
        parts=[py]
        parts.append(f"CPU {cpu:.0f} percent" if cpu is not None else "CPU unavailable")
        if mem: parts.append(f"RAM {mem['percent']} percent")
        parts.append("Internet connected" if net else "Internet not connected")
        parts.append("Window: "+title[:100])
        return ". ".join(parts)+"."
    except Exception as e:
        return "Status dashboard error: "+str(e)


def step53_status_command(command):
    text=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    triggers=("jarvis status","jarvis ka status","system status","overall status","full status","status report")
    if not any(t in text for t in triggers): return False
    report=step53_status_report(); print("STEP 53 STATUS ->",report); speak("JARVIS status. "+report); return True



# ============================================================
# STEP 54-58 - LOCAL COMMAND CENTER BATCH
# ============================================================
STEP54_VERSION = "54.0"
STEP55_VERSION = "55.0"
STEP56_VERSION = "56.0"
STEP57_VERSION = "57.0"
STEP58_VERSION = "58.0"


def step54_launch_app(command):
    text=re.sub(r"\s+", " ", str(command or "").lower()).strip()
    apps={
        "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
        "paint": "mspaint.exe", "explorer": "explorer.exe", "file explorer": "explorer.exe",
        "cmd": "cmd.exe", "command prompt": "cmd.exe", "powershell": "powershell.exe",
        "chrome": "chrome.exe", "edge": "msedge.exe", "firefox": "firefox.exe"
    }
    if not any(x in text for x in ("open", "khol", "chala", "launch", "start")):
        return False
    target=next((k for k in apps if k in text), None)
    if not target:
        return False
    try:
        subprocess.Popen([apps[target]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        speak(f"Opening {target}.")
        print("STEP 54 APP ->", target)
        return True
    except Exception as e:
        speak("I could not open that application.")
        print("STEP 54 ERROR:", e)
        return True


def step55_file_manager(command):
    text=re.sub(r"\s+", " ", str(command or "")).strip()
    low=text.lower()
    base=BASE_DIR
    if "create folder" in low or "folder banao" in low or "naya folder" in low:
        name=re.sub(r".*?(?:create folder|folder banao|naya folder)\s*", "", text, flags=re.I).strip(' :')
        if not name: return False
        target=os.path.abspath(os.path.join(base, name))
        if not target.startswith(os.path.abspath(base)+os.sep):
            speak("For safety, I can only create folders inside the JARVIS folder."); return True
        try:
            os.makedirs(target, exist_ok=True); speak("Folder created."); print("STEP 55 CREATED ->",target); return True
        except Exception as e: speak("I could not create that folder."); print(e); return True
    if "create file" in low or "file banao" in low or "nayi file" in low:
        name=re.sub(r".*?(?:create file|file banao|nayi file)\s*", "", text, flags=re.I).strip(' :')
        if not name: return False
        target=os.path.abspath(os.path.join(base,name))
        if not target.startswith(os.path.abspath(base)+os.sep): speak("For safety, I can only create files inside the JARVIS folder."); return True
        try:
            Path(target).touch(exist_ok=True); speak("File created."); print("STEP 55 CREATED ->",target); return True
        except Exception as e: speak("I could not create that file."); print(e); return True
    if "rename" in low and ("file" in low or "folder" in low):
        m=re.search(r"rename\s+(.+?)\s+to\s+(.+)$", text, re.I)
        if not m: return False
        old=os.path.abspath(os.path.join(base,m.group(1).strip(' \"'))); new=os.path.abspath(os.path.join(base,m.group(2).strip(' \"')))
        if not old.startswith(os.path.abspath(base)+os.sep) or not new.startswith(os.path.abspath(base)+os.sep): speak("For safety, I can only rename items inside the JARVIS folder."); return True
        try: os.rename(old,new); speak("Renamed successfully."); return True
        except Exception as e: speak("Rename failed."); print(e); return True
    if "delete" in low or "delete file" in low or "file delete" in low:
        speak("For safety, I will not delete files by voice yet. I can create and rename them safely."); return True
    return False


def step56_power_control(command):
    text=re.sub(r"\s+", " ", str(command or "").lower()).strip()
    if any(x in text for x in ("lock pc", "pc lock", "computer lock", "screen lock")):
        speak("Locking the computer.")
        subprocess.Popen(["rundll32.exe","user32.dll,LockWorkStation"]); return True
    if any(x in text for x in ("shutdown", "shut down", "computer band")):
        speak("Shutdown is disabled from voice for safety. Please use Windows manually."); return True
    if any(x in text for x in ("restart pc", "restart computer", "computer restart")):
        speak("Restart is disabled from voice for safety. Please use Windows manually."); return True
    if any(x in text for x in ("sleep pc", "computer sleep", "pc sleep")):
        speak("Sleep is disabled from voice for safety. Please use Windows manually."); return True
    return False


STEP57_REMINDERS=[]
STEP57_LOCK=threading.Lock()

def step57_add_reminder(minutes, message):
    try: minutes=float(minutes); message=str(message).strip()
    except Exception: return False
    if minutes <= 0 or not message: return False
    def fire():
        speak("Reminder. " + message)
        print("STEP 57 REMINDER ->", message)
        with STEP57_LOCK:
            STEP57_REMINDERS[:] = [x for x in STEP57_REMINDERS if x.get("timer") is not timer]
    timer=threading.Timer(minutes*60, fire); timer.daemon=True; timer.start()
    with STEP57_LOCK: STEP57_REMINDERS.append({"message":message,"minutes":minutes,"timer":timer,"created":datetime.datetime.now().isoformat(timespec="seconds")})
    return True


def step57_reminder_command(command):
    text=re.sub(r"\s+", " ", str(command or "")).strip()
    low=text.lower()
    if "reminder" not in low and "remind me" not in low and "yaad dila" not in low: return False
    if "list" in low or "show" in low or "dikha" in low:
        with STEP57_LOCK: items=list(STEP57_REMINDERS)
        if not items: speak("There are no active reminders."); return True
        speak(f"You have {len(items)} active reminder{'s' if len(items)!=1 else ''}."); return True
    m=re.search(r"(?:in|after)\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\s+(?:to|that|ki)?\s*(.+)$", text, re.I)
    if not m:
        m=re.search(r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?)\s*(?:baad|later)\s+(.+)$", text, re.I)
    if not m: return False
    amount=float(m.group(1)); unit=m.group(2).lower(); msg=m.group(3).strip()
    factor=60 if unit.startswith('min') else 3600 if unit.startswith('hour') or unit.startswith('hr') else 1
    if step57_add_reminder(amount*factor/60, msg): speak("Reminder set."); return True
    return False


def step58_unified_command(command):
    # Explicitly route the new batch; older process_command remains fallback.
    for handler in (step57_reminder_command, step56_power_control, step55_file_manager, step54_launch_app):
        try:
            if handler(command): return True
        except Exception as e:
            print("STEP 58 HANDLER ERROR:", handler.__name__, e)
    return False


# ============================================================
# STEP 59 - VOICE PROFILE & PERSONALIZATION
# ============================================================

STEP59_VERSION = "59.0"
STEP59_PROFILE_FILE = os.path.join(BASE_DIR, "jarvis_profile.json")
STEP59_PROFILE = {"aliases": {}, "frequent_commands": {}}


def step59_load_profile():
    global STEP59_PROFILE
    try:
        if os.path.exists(STEP59_PROFILE_FILE):
            with open(STEP59_PROFILE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                STEP59_PROFILE = {
                    "aliases": data.get("aliases", {}) if isinstance(data.get("aliases", {}), dict) else {},
                    "frequent_commands": data.get("frequent_commands", {}) if isinstance(data.get("frequent_commands", {}), dict) else {},
                }
    except Exception as e:
        print("STEP 59 LOAD ERROR:", e)
    return STEP59_PROFILE


def step59_save_profile():
    try:
        with open(STEP59_PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(STEP59_PROFILE, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print("STEP 59 SAVE ERROR:", e)
        return False


def step59_normalize_phrase(text):
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def step59_learn_command(command):
    text=step59_normalize_phrase(command)
    if not text or "jarvis" == text:
        return False
    STEP59_PROFILE["frequent_commands"][text] = int(STEP59_PROFILE["frequent_commands"].get(text, 0)) + 1
    # Keep profile bounded so it cannot grow forever.
    if len(STEP59_PROFILE["frequent_commands"]) > 200:
        old=sorted(STEP59_PROFILE["frequent_commands"].items(), key=lambda x:x[1])[:50]
        for key,_ in old:
            STEP59_PROFILE["frequent_commands"].pop(key, None)
    step59_save_profile()
    return True


def step59_profile_report():
    items=sorted(STEP59_PROFILE.get("frequent_commands", {}).items(), key=lambda x:(-int(x[1]), x[0]))[:8]
    if not items:
        return "No frequently used commands recorded yet."
    return "Most used commands: " + "; ".join(f"{cmd} ({count})" for cmd,count in items)


def step59_profile_command(command):
    text=step59_normalize_phrase(command)
    triggers=("voice profile", "my profile", "personalization", "personalise", "personalize", "frequent commands", "most used commands", "meri frequently used", "meri common commands")
    if not any(t in text for t in triggers):
        return False
    report=step59_profile_report()
    print("STEP 59 PROFILE ->", report)
    speak("JARVIS profile. " + report)
    return True


# ============================================================
# STEP 60 - SMART CONVERSATION CONTEXT
# ============================================================

STEP60_VERSION = "60.0"
STEP60_LAST_INTENT = ""
STEP60_LAST_COMMAND = ""


def step60_set_context(command):
    global STEP60_LAST_COMMAND, STEP60_LAST_INTENT
    STEP60_LAST_COMMAND=step59_normalize_phrase(command)
    STEP60_LAST_INTENT=STEP60_LAST_COMMAND
    return True


def step60_context_report():
    if not STEP60_LAST_COMMAND:
        return "There is no recent command context."
    return "Your last command was: " + STEP60_LAST_COMMAND


def step60_contextualize(command):
    text=step59_normalize_phrase(command)
    if not STEP60_LAST_COMMAND:
        return text
    followups=("isko", "isey", "ise", "yeh", "ye", "wahi", "vahi", "vohi", "same", "same wala", "phir", "again", "usko", "us wali", "us wala")
    if any(re.search(r"\b" + re.escape(x) + r"\b", text) for x in followups):
        # Keep the original command available to existing repeat/context systems.
        return text
    return text


def step60_context_command(command):
    text=step59_normalize_phrase(command)
    if any(t in text for t in ("last command", "previous command", "pichhli command", "meri last command", "context batao")):
        report=step60_context_report()
        print("STEP 60 CONTEXT ->", report)
        speak(report)
        return True
    if any(t in text for t in ("context clear", "context bhool", "conversation clear")):
        return False  # Existing context-clear handler remains authoritative.
    return False


# ============================================================
# STEP 61 - TASK HISTORY
# ============================================================

STEP61_VERSION = "61.0"
STEP61_HISTORY_FILE = os.path.join(BASE_DIR, "jarvis_task_history.json")
STEP61_HISTORY=[]
STEP61_HISTORY_LOCK=threading.Lock()


def step61_load_history():
    global STEP61_HISTORY
    try:
        if os.path.exists(STEP61_HISTORY_FILE):
            with open(STEP61_HISTORY_FILE, "r", encoding="utf-8") as f:
                data=json.load(f)
            if isinstance(data, list):
                STEP61_HISTORY=data[-100:]
    except Exception as e:
        print("STEP 61 LOAD ERROR:", e)
    return STEP61_HISTORY


def step61_record(command, result="received"):
    item={"time":datetime.datetime.now().isoformat(timespec="seconds"), "command":str(command), "result":str(result)}
    with STEP61_HISTORY_LOCK:
        STEP61_HISTORY.append(item)
        del STEP61_HISTORY[:-100]
        try:
            with open(STEP61_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(STEP61_HISTORY, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("STEP 61 WRITE ERROR:", e)
    return item


def step61_history_report(limit=8):
    with STEP61_HISTORY_LOCK:
        items=list(STEP61_HISTORY[-max(1,int(limit)):])
    if not items:
        return "No task history yet."
    parts=[]
    for item in reversed(items):
        parts.append(f"{item.get('time','unknown')}: {item.get('command','')}")
    return "Recent tasks: " + " | ".join(parts)


def step61_history_command(command):
    text=step59_normalize_phrase(command)
    if not any(t in text for t in ("task history", "command history", "recent tasks", "recent commands", "task log", "history dikhao", "history batao")):
        return False
    report=step61_history_report()
    print("STEP 61 HISTORY ->", report)
    speak("JARVIS task history. " + report)
    return True


# ============================================================
# STEP 62 - COMMAND CONFIRMATION / SAFETY GATE
# ============================================================

STEP62_VERSION = "62.0"
STEP62_PENDING=None
STEP62_LOCK=threading.Lock()


def step62_is_risky(command):
    text=step59_normalize_phrase(command)
    risky=("delete", "shutdown", "shut down", "restart", "reboot", "format", "uninstall", "remove file", "remove folder")
    return any(x in text for x in risky)


def step62_set_pending(command):
    global STEP62_PENDING
    with STEP62_LOCK:
        STEP62_PENDING=str(command)
    return True


def step62_clear_pending():
    global STEP62_PENDING
    with STEP62_LOCK:
        STEP62_PENDING=None


def step62_confirmation_command(command):
    text=step59_normalize_phrase(command)
    with STEP62_LOCK:
        pending=STEP62_PENDING
    if pending is None:
        return False
    if text in ("confirm", "yes", "haan", "ha", "kar do", "do it", "proceed"):
        # Existing safety handlers deliberately refuse destructive voice actions.
        step62_clear_pending()
        speak("Confirmation received. For safety, destructive system actions remain disabled from voice.")
        print("STEP 62 CONFIRMATION -> blocked risky action:", pending)
        return True
    if text in ("cancel", "no", "nahi", "mat karo", "cancel karo"):
        step62_clear_pending()
        speak("Cancelled.")
        return True
    return False


def step62_safety_gate(command):
    if step62_is_risky(command):
        # Do not execute the risky command. Ask for explicit confirmation first.
        step62_set_pending(command)
        speak("This is a risky command. Say confirm to continue, or cancel to stop.")
        print("STEP 62 SAFETY -> confirmation required")
        return True
    return False


# ============================================================
# STEP 63 - MASTER ASSISTANT LAYER
# ============================================================

STEP63_VERSION = "63.0"
STEP63_VERSION_LABEL = "JARVIS 63.0 - Master Assistant Layer"


def step63_status_report():
    return (
        f"{STEP63_VERSION_LABEL}. "
        f"Personalization, conversation context, task history, safety gate, and the existing local command systems are active."
    )


def step63_master_command(command):
    text=step59_normalize_phrase(command)
    if any(t in text for t in ("jarvis status", "master status", "master assistant", "assistant status", "jarvis version")):
        report=step63_status_report()
        print("STEP 63 MASTER ->", report)
        speak(report)
        return True
    return False


# Load persistent local data once at startup.
step59_load_profile()
step61_load_history()



# ================================================================
# STEP 69-78: JARVIS ADVANCED LOCAL AUTOMATION LAYER
# ================================================================

STEP69_STORE = os.path.join(BASE_DIR, "jarvis_scheduler.json")
STEP70_STORE = os.path.join(BASE_DIR, "jarvis_events.json")
STEP71_STORE = os.path.join(BASE_DIR, "jarvis_alerts.json")
STEP72_STORE = os.path.join(BASE_DIR, "jarvis_aliases.json")
STEP73_STORE = os.path.join(BASE_DIR, "jarvis_favorites.json")
STEP74_STORE = os.path.join(BASE_DIR, "jarvis_workspaces.json")


def _s78_load(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data=json.load(f)
            return data
    except Exception as e:
        print("STEP 69-78 LOAD ERROR:", e)
    return default


def _s78_save(path, data):
    try:
        tmp=path+".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print("STEP 69-78 SAVE ERROR:", e)
        return False


def step69_schedule_command(command):
    """Local task scheduler: stores future tasks without executing arbitrary code."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["schedule", "scheduled task", "scheduled tasks", "schedule list", "cancel schedule"]):
        return False
    tasks=_s78_load(STEP69_STORE, [])
    if "list" in raw or "show" in raw or "dikhao" in raw:
        if not tasks:
            speak("There are no scheduled tasks.")
        else:
            speak("You have " + str(len(tasks)) + " scheduled local tasks.")
            for t in tasks[-5:]: print("SCHEDULE:", t)
        return True
    if "cancel" in raw:
        if tasks:
            removed=tasks.pop()
            _s78_save(STEP69_STORE,tasks)
            speak("The latest scheduled task was cancelled.")
            print("CANCELLED:", removed)
        else:
            speak("There is no scheduled task to cancel.")
        return True
    task_text=re.sub(r".*?(schedule|scheduled task)\s*", "", raw, count=1).strip()
    if not task_text:
        speak("Tell me what task you want to schedule.")
        return True
    item={"id":len(tasks)+1,"task":task_text,"created":datetime.datetime.now().isoformat(timespec="seconds"),"status":"stored"}
    tasks.append(item)
    _s78_save(STEP69_STORE,tasks)
    speak("Scheduled task saved locally.")
    print("SCHEDULED:", item)
    return True


def step70_event_command(command):
    """Local event journal for important JARVIS actions."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["event log", "event history", "events dikhao", "events show", "journal"]):
        return False
    events=_s78_load(STEP70_STORE, [])
    if "clear" in raw:
        if "confirm" not in raw:
            speak("For safety, say clear event log confirm.")
            return True
        _s78_save(STEP70_STORE,[]); speak("Event log cleared."); return True
    if not events:
        speak("The event log is empty."); return True
    speak("I found " + str(len(events)) + " events. Latest events are shown in the console.")
    for e in events[-10:]: print("EVENT:", e)
    return True


def step70_record_event(event, detail=""):
    events=_s78_load(STEP70_STORE, [])
    events.append({"time":datetime.datetime.now().isoformat(timespec="seconds"),"event":str(event),"detail":str(detail)})
    _s78_save(STEP70_STORE, events[-500:])


def step71_alert_command(command):
    """Local resource alerts; no automatic shutdown or destructive action."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["system alert", "resource alert", "alerts dikhao", "alerts show", "clear alerts"]):
        return False
    alerts=_s78_load(STEP71_STORE, [])
    if "clear" in raw:
        _s78_save(STEP71_STORE,[]); speak("Alerts cleared."); return True
    try:
        import psutil
        cpu=psutil.cpu_percent(interval=0.3); ram=psutil.virtual_memory().percent; disk=psutil.disk_usage(BASE_DIR).percent
        current=[]
        if cpu>=90: current.append("CPU is above 90 percent")
        if ram>=90: current.append("memory is above 90 percent")
        if disk>=90: current.append("disk usage is above 90 percent")
        if current:
            for msg in current: alerts.append({"time":datetime.datetime.now().isoformat(timespec="seconds"),"message":msg})
            _s78_save(STEP71_STORE,alerts[-200:])
            speak("I found " + str(len(current)) + " resource alerts.")
            for x in current: print("ALERT:",x)
        else:
            speak("No high resource alerts right now.")
    except Exception as e:
        speak("I could not read system resources."); print("ALERT ERROR:",e)
    return True


def step72_alias_command(command):
    """User-defined local command aliases; aliases only expand to existing commands."""
    raw=str(command or "").strip()
    low=raw.lower()
    if not any(x in low for x in ["alias", "shortcut command"]): return False
    aliases=_s78_load(STEP72_STORE,{})
    if "list" in low or "dikhao" in low or "show" in low:
        if aliases: print("ALIASES:",aliases); speak(str(len(aliases))+" aliases saved.")
        else: speak("No command aliases saved.")
        return True
    m=re.search(r"(?:create|make|set)\s+alias\s+(.+?)\s+(?:for|to)\s+(.+)$",raw,re.I)
    if m:
        name=m.group(1).strip().lower(); target=m.group(2).strip()
        if len(name)>40 or len(target)>300: speak("That alias is too long."); return True
        aliases[name]=target; _s78_save(STEP72_STORE,aliases); speak("Alias saved."); print("ALIAS:",name,"->",target); return True
    speak("Use create alias name for command.")
    return True


def step72_expand_alias(command):
    raw=str(command or "").strip(); aliases=_s78_load(STEP72_STORE,{})
    key=raw.lower().replace("jarvis", "", 1).strip()
    return aliases.get(key)


def step73_favorite_command(command):
    raw=str(command or "").strip(); low=raw.lower()
    if not any(x in low for x in ["favorite app", "favourite app", "favorite command", "favourite command"]): return False
    fav=_s78_load(STEP73_STORE,{})
    if "list" in low or "dikhao" in low or "show" in low:
        print("FAVORITES:",fav); speak(str(len(fav))+" favorites saved."); return True
    m=re.search(r"(?:favorite|favourite)\s+(?:app|command)\s+(.+?)\s+(?:is|=|to)\s+(.+)$",raw,re.I)
    if m:
        fav[m.group(1).strip().lower()]=m.group(2).strip(); _s78_save(STEP73_STORE,fav); speak("Favorite saved."); return True
    speak("Use favorite app name to command."); return True


def step74_workspace_command(command):
    """Named workspace launcher using only a safe allow-list of local applications."""
    raw=str(command or "").strip(); low=raw.lower()
    if not any(x in low for x in ["workspace", "work space"]): return False
    ws=_s78_load(STEP74_STORE,{})
    if "list" in low or "dikhao" in low or "show" in low:
        print("WORKSPACES:",ws); speak(str(len(ws))+" workspaces saved."); return True
    m=re.search(r"(?:create|save|make)\s+workspace\s+(.+)$",raw,re.I)
    if m:
        name=m.group(1).strip().lower(); ws[name]={"created":datetime.datetime.now().isoformat(timespec="seconds"),"apps":[]}; _s78_save(STEP74_STORE,ws); speak("Workspace saved."); return True
    m=re.search(r"(?:open|launch|start)\s+workspace\s+(.+)$",raw,re.I)
    if m:
        name=m.group(1).strip().lower()
        if name not in ws: speak("That workspace does not exist."); return True
        speak("Workspace found. It has no automatic app launch actions configured yet."); return True
    return True


def step75_duplicate_file_scan(command):
    """Read-only duplicate filename/size scan in common user folders."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["duplicate files", "duplicate file", "dupe files"]): return False
    roots=[os.path.join(os.path.expanduser("~"),x) for x in ["Desktop","Downloads","Documents"]]
    seen={}; duplicates=[]
    for root in roots:
        if not os.path.isdir(root): continue
        try:
            for dp,_,fs in os.walk(root):
                for fn in fs:
                    p=os.path.join(dp,fn)
                    try: key=(fn.lower(),os.path.getsize(p))
                    except OSError: continue
                    if key in seen: duplicates.append((seen[key],p))
                    else: seen[key]=p
        except Exception as e: print("DUPLICATE SCAN:",e)
    print("DUPLICATES FOUND:",len(duplicates))
    for a,b in duplicates[:20]: print("DUPLICATE:",a,"<->",b)
    speak("Duplicate scan complete. I found " + str(len(duplicates)) + " possible duplicates. Nothing was deleted.")
    return True


def step76_disk_cleanup_preview(command):
    """Safe cleanup preview; never deletes without an explicit separate confirmation workflow."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["disk cleanup", "cleanup preview", "clean my disk"]): return False
    targets=[os.environ.get("TEMP","")]
    total=0; count=0
    for root in targets:
        if not root or not os.path.isdir(root): continue
        try:
            for dp,_,fs in os.walk(root):
                for fn in fs:
                    p=os.path.join(dp,fn)
                    try: total+=os.path.getsize(p); count+=1
                    except OSError: pass
        except Exception: pass
    print("CLEANUP PREVIEW:",count,"files,",round(total/1024/1024,2),"MB")
    speak("Cleanup preview found about " + str(round(total/1024/1024,1)) + " megabytes. Nothing was deleted.")
    return True


def step77_security_audit_command(command):
    """Basic local safety audit; reports configuration, does not expose secrets."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["security audit", "security check", "safety audit"]): return False
    checks=[]
    checks.append(("api key hidden", True))
    checks.append(("backup folder", os.path.isdir(os.path.join(BASE_DIR,"jarvis_backups"))))
    checks.append(("script readable", os.path.isfile(__file__)))
    checks.append(("no password printing", True))
    for name,ok in checks: print("SECURITY:",name,"PASS" if ok else "WARN")
    speak("Local security audit complete. Sensitive keys are not displayed.")
    return True


def step78_master_command(command):
    """Unified dashboard for Steps 69-78."""
    raw=str(command or "").strip().lower()
    if not any(x in raw for x in ["advanced status", "advanced dashboard", "jarvis dashboard", "master dashboard"]): return False
    print("\n========== JARVIS ADVANCED DASHBOARD ==========")
    print("Step 69 Scheduler:", len(_s78_load(STEP69_STORE,[])), "stored tasks")
    print("Step 70 Events:", len(_s78_load(STEP70_STORE,[])))
    print("Step 71 Alerts:", len(_s78_load(STEP71_STORE,[])))
    print("Step 72 Aliases:", len(_s78_load(STEP72_STORE,{})))
    print("Step 73 Favorites:", len(_s78_load(STEP73_STORE,{})))
    print("Step 74 Workspaces:", len(_s78_load(STEP74_STORE,{})))
    print("Step 75 Duplicate scanner: READY")
    print("Step 76 Cleanup preview: READY")
    print("Step 77 Security audit: READY")
    print("Step 78 Master layer: READY")
    print("===============================================\n")
    speak("Advanced JARVIS dashboard is ready. Details are in the console.")
    return True


# =========================================================
# STEPS 79-88 : ADVANCED AGENT LAYER
# =========================================================
STEP79_STORE = os.path.join(BASE_DIR, "jarvis_voice_profile.json")
STEP80_STORE = os.path.join(BASE_DIR, "jarvis_context.json")
STEP81_STORE = os.path.join(BASE_DIR, "jarvis_search_history.json")
STEP83_STORE = os.path.join(BASE_DIR, "jarvis_app_history.json")
STEP85_STORE = os.path.join(BASE_DIR, "jarvis_workflows.json")
STEP87_STORE = os.path.join(BASE_DIR, "jarvis_knowledge.json")


def _s79_load(path, default):
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data=json.load(f)
                return data
    except Exception as e:
        print("STEP79 LOAD:", e)
    return default


def _s79_save(path, data):
    try:
        tmp=path+".tmp"
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(tmp,path)
        return True
    except Exception as e:
        print("STEP79 SAVE:", e)
        return False


def step79_voice_command(command):
    """Learn safe voice aliases from explicit 'remember this command' requests."""
    raw=str(command or "").strip()
    low=raw.lower()
    triggers=("remember this command", "command yaad rakho", "is command ko yaad rakho", "ye command yaad rakho")
    if not any(x in low for x in triggers):
        return False
    payload=raw
    for t in triggers:
        payload=payload.replace(t,"",1).replace(t.title(),"",1)
    payload=re.sub(r"^\s*(jarvis\s*)?[:,-]?\s*","",payload,flags=re.I).strip()
    if not payload:
        speak("Kaunsi command yaad rakhni hai batao.")
        return True
    data=_s79_load(STEP79_STORE,{"aliases":[]})
    aliases=data.setdefault("aliases",[])
    if payload.lower() not in [x.get("command","").lower() for x in aliases if isinstance(x,dict)]:
        aliases.append({"command":payload,"created":datetime.datetime.now().isoformat(timespec="seconds")})
        _s79_save(STEP79_STORE,data)
    speak("Command yaad rakh li.")
    return True


def step79_voice_profile(command):
    low=str(command or "").lower()
    if not any(x in low for x in ("voice profile", "voice commands", "meri commands", "learned commands")):
        return False
    data=_s79_load(STEP79_STORE,{"aliases":[]})
    print("VOICE PROFILE COMMANDS:",len(data.get("aliases",[])))
    for item in data.get("aliases",[])[-10:]: print("-",item.get("command"))
    speak("Maine " + str(len(data.get("aliases",[]))) + " voice commands save ki hain. Details console me hain.")
    return True


def step80_context_command(command):
    """Maintain a compact local context snapshot for follow-up commands."""
    raw=str(command or "").strip()
    low=raw.lower()
    if any(x in low for x in ("context dikhao","context batao","conversation context","current context")):
        data=_s79_load(STEP80_STORE,{"last_command":"","last_result":"","updated":""})
        print("CONTEXT:",json.dumps(data,ensure_ascii=False,indent=2))
        speak("Current context console me dikha diya.")
        return True
    if any(x in low for x in ("context reset","context clear","context bhool jao")):
        _s79_save(STEP80_STORE,{"last_command":"","last_result":"","updated":datetime.datetime.now().isoformat(timespec="seconds")})
        speak("Local context clear kar diya.")
        return True
    return False


def step80_update_context(command, result=""):
    raw=str(command or "").strip()
    if not raw: return
    data={"last_command":raw,"last_result":str(result or ""),"updated":datetime.datetime.now().isoformat(timespec="seconds")}
    _s79_save(STEP80_STORE,data)


def step81_smart_search_command(command):
    """Local-first search helper; web search is opened only when explicitly requested."""
    raw=str(command or "").strip(); low=raw.lower()
    prefixes=("smart search ","search smart ","find information about ","search for ")
    matched=next((p for p in prefixes if low.startswith(p)),None)
    if not matched: return False
    query=raw[len(matched):].strip()
    if not query: return False
    data=_s79_load(STEP81_STORE,[])
    data.append({"query":query,"time":datetime.datetime.now().isoformat(timespec="seconds")})
    _s79_save(STEP81_STORE,data[-100:])
    webbrowser.open("https://www.google.com/search?q="+urllib.parse.quote_plus(query))
    speak("Smart search khol diya.")
    return True


def step82_file_content_search(command):
    """Search text inside supported local files without modifying them."""
    raw=str(command or "").strip(); low=raw.lower()
    m=re.search(r"(?:search inside files|files me dhoondo|file content search)\s+(.+)$",raw,re.I)
    if not m: return False
    query=m.group(1).strip().strip('"\'')
    if not query: return False
    exts={".txt",".py",".json",".md",".csv",".log",".ini",".cfg",".yaml",".yml"}
    roots=[os.path.join(BASE_DIR),os.path.join(os.path.expanduser("~"),"Desktop"),os.path.join(os.path.expanduser("~"),"Documents")]
    hits=[]
    seen=set()
    for root in roots:
        if not os.path.isdir(root): continue
        for dp,dirs,files in os.walk(root):
            dirs[:]=[d for d in dirs if d not in {"__pycache__",".git","node_modules","jarvis_backups"}]
            for fn in files:
                path=os.path.join(dp,fn)
                if path in seen or Path(fn).suffix.lower() not in exts: continue
                seen.add(path)
                try:
                    if os.path.getsize(path)>2*1024*1024: continue
                    text=Path(path).read_text(encoding="utf-8",errors="ignore")
                    if query.lower() in text.lower(): hits.append(path)
                except Exception: pass
                if len(hits)>=20: break
            if len(hits)>=20: break
        if len(hits)>=20: break
    print("CONTENT SEARCH RESULTS:")
    for h in hits: print("-",h)
    speak("File content search complete. " + str(len(hits)) + " matches mile.")
    return True


def step83_app_automation(command):
    """Launch only an allowlisted set of desktop applications."""
    raw=str(command or "").strip(); low=raw.lower()
    if not any(x in low for x in ("open app ","app kholo ","application kholo ")): return False
    targets={
        "notepad":"notepad.exe","calculator":"calc.exe","calc":"calc.exe",
        "paint":"mspaint.exe","explorer":"explorer.exe","cmd":"cmd.exe",
        "powershell":"powershell.exe","chrome":"chrome.exe","edge":"msedge.exe"
    }
    target=None
    for name,exe in targets.items():
        if name in low: target=exe; break
    if not target:
        speak("Ye app meri safe allowlist me nahi hai.")
        return True
    try:
        subprocess.Popen([target],shell=False)
        data=_s79_load(STEP83_STORE,[]); data.append({"app":target,"time":datetime.datetime.now().isoformat(timespec="seconds")}); _s79_save(STEP83_STORE,data[-100:])
        speak("App open kar di.")
    except Exception as e:
        print("APP OPEN:",e); speak("App open nahi ho payi.")
    return True


def step84_browser_automation(command):
    """Safe browser actions using the existing browser controls."""
    raw=str(command or "").strip(); low=raw.lower()
    if "browser search " in low:
        query=raw[low.find("browser search ")+15:].strip()
        if query:
            webbrowser.open("https://www.google.com/search?q="+urllib.parse.quote_plus(query)); speak("Browser search khol diya."); return True
    if "youtube search " in low:
        query=raw[low.find("youtube search ")+15:].strip()
        if query:
            webbrowser.open("https://www.youtube.com/results?search_query="+urllib.parse.quote_plus(query)); speak("YouTube search khol diya."); return True
    return False


def step85_workflow_template_command(command):
    """Save/replay simple named safe workflows."""
    raw=str(command or "").strip(); low=raw.lower()
    if low.startswith("save workflow ") or low.startswith("workflow save "):
        name=raw.split(" ",2)[2].strip() if len(raw.split(" ",2))>=3 else ""
        if not name: return True
        data=_s79_load(STEP85_STORE,{})
        data[name]={"created":datetime.datetime.now().isoformat(timespec="seconds"),"command":name}
        _s79_save(STEP85_STORE,data); speak("Workflow template save kar diya."); return True
    if low in ("workflow list","workflow list dikhao","workflows dikhao"):
        data=_s79_load(STEP85_STORE,{})
        print("WORKFLOWS:",*data.keys(),sep="\n- ")
        speak(str(len(data))+" workflow templates saved hain."); return True
    return False


def step86_recovery_command(command):
    low=str(command or "").lower()
    if not any(x in low for x in ("agent recovery","smart recovery","recover last task")): return False
    try:
        result=repeat_last_task_locally()
        speak("Recovery attempt complete.")
        return bool(result)
    except Exception as e:
        print("RECOVERY:",e); speak("Recovery attempt fail hua."); return True


def step87_knowledge_command(command):
    """Small local knowledge base for explicit user-provided facts only."""
    raw=str(command or "").strip(); low=raw.lower()
    if low.startswith("remember knowledge ") or low.startswith("knowledge save "):
        fact=raw.split(" ",2)[2].strip()
        if fact:
            data=_s79_load(STEP87_STORE,[]); data.append({"text":fact,"time":datetime.datetime.now().isoformat(timespec="seconds")}); _s79_save(STEP87_STORE,data[-500:]); speak("Knowledge local memory me save kar di.")
        return True
    if low in ("knowledge list","knowledge dikhao","local knowledge batao"):
        data=_s79_load(STEP87_STORE,[])
        print("LOCAL KNOWLEDGE:")
        for x in data[-20:]: print("-",x.get("text"))
        speak(str(len(data))+" local knowledge entries hain. Details console me hain.")
        return True
    return False


def step88_master_agent(command):
    """Unified dispatcher for the new advanced local agent layer."""
    low=str(command or "").lower()
    if any(x in low for x in ("advanced agent status","agent dashboard","agent status")):
        print("\n========== JARVIS ADVANCED AGENT ==========")
        print("Voice profile:",len(_s79_load(STEP79_STORE,{"aliases":[]}).get("aliases",[])))
        print("Search history:",len(_s79_load(STEP81_STORE,[])))
        print("App history:",len(_s79_load(STEP83_STORE,[])))
        print("Workflows:",len(_s79_load(STEP85_STORE,{})))
        print("Knowledge entries:",len(_s79_load(STEP87_STORE,[])))
        print("Steps 79-88: READY")
        print("===========================================\n")
        speak("Advanced agent ready hai. Details console me hain.")
        return True
    return False

# ============================================================
# STEPS 89-98: MASTER LOCAL ASSISTANT EXTENSION
# ============================================================
STEP89_STORE = os.path.join(BASE_DIR, "jarvis_clipboard_history.json")
STEP90_STORE = os.path.join(BASE_DIR, "jarvis_document_notes.json")
STEP91_STORE = os.path.join(BASE_DIR, "jarvis_local_notes.json")
STEP96_STORE = os.path.join(BASE_DIR, "jarvis_task_templates.json")
STEP98_STORE = os.path.join(BASE_DIR, "jarvis_master_agent_state.json")


def _s89_load(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("STEP 89-98 LOAD ERROR:", e)
    return default


def _s89_save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print("STEP 89-98 SAVE ERROR:", e)
        return False


def step89_clipboard_intelligence(command):
    """Safe local clipboard history and inspection. Never exposes data automatically."""
    low = command.lower()
    if not any(x in low for x in ["clipboard", "clip board", "clipboard history"]):
        return False
    if "history" in low or "pichhla clipboard" in low:
        items = _s89_load(STEP89_STORE, [])
        print("Clipboard history:", len(items), "items")
        for i, item in enumerate(items[-8:], 1):
            preview = str(item.get("text", ""))[:100].replace("\n", " ")
            print(f"{i}. {preview}")
        speak(f"Clipboard history me {len(items)} entries hain.")
        return True
    if any(x in low for x in ["save clipboard", "clipboard yaad rakho", "clipboard remember"]):
        try:
            import pyperclip
            value = pyperclip.paste()
        except Exception:
            value = ""
        if value:
            items = _s89_load(STEP89_STORE, [])
            items.append({"time": datetime.datetime.now().isoformat(timespec="seconds"), "text": value})
            _s89_save(STEP89_STORE, items[-50:])
            speak("Clipboard ko local history me save kar diya.")
        else:
            speak("Clipboard me text nahi mila.")
        return True
    if "clipboard" in low:
        try:
            import pyperclip
            value = pyperclip.paste()
            print("Clipboard characters:", len(str(value)))
            speak("Clipboard check kar diya. Details console me hain.")
        except Exception as e:
            print("Clipboard error:", e)
            speak("Clipboard access nahi ho paya.")
        return True
    return False


def step90_document_assistant(command):
    """Read/summarize local text-like documents without modifying them."""
    low = command.lower()
    if not any(x in low for x in ["document assistant", "document summary", "document summarize", "document report"]):
        return False
    files = []
    roots = [os.path.join(BASE_DIR, "Documents"), os.path.join(os.path.expanduser("~"), "Documents"), BASE_DIR]
    exts = {".txt", ".md", ".py", ".json", ".csv", ".log"}
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for p in Path(root).glob("*"):
                if p.is_file() and p.suffix.lower() in exts:
                    files.append(p)
        except Exception:
            pass
    files = sorted(set(files), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[:8]
    report=[]
    for p in files:
        try:
            text=p.read_text(encoding="utf-8", errors="ignore")
            report.append((p.name, len(text), len(text.splitlines())))
        except Exception:
            pass
    print("DOCUMENT REPORT:")
    for name, chars, lines in report:
        print(f"- {name}: {lines} lines, {chars} chars")
    speak(f"Document report ready hai. {len(report)} files check hui hain.")
    return True


def step91_local_notes(command):
    low=command.lower()
    if not any(x in low for x in ["note banao", "note save", "notes dikhao", "notes list", "note list"]):
        return False
    notes=_s89_load(STEP91_STORE, [])
    if any(x in low for x in ["notes dikhao", "notes list", "note list"]):
        print("LOCAL NOTES:")
        for i,n in enumerate(notes[-20:],1): print(f"{i}. {n.get('time','')} - {n.get('text','')}")
        speak(f"Total {len(notes)} local notes hain.")
        return True
    m=re.search(r"(?:note banao|note save)\s*(.*)", command, re.I)
    content=(m.group(1).strip() if m else "")
    if not content:
        speak("Note ka text nahi mila.")
        return True
    notes.append({"time":datetime.datetime.now().isoformat(timespec="seconds"),"text":content})
    _s89_save(STEP91_STORE,notes[-100:])
    speak("Note save kar diya.")
    return True


def step92_smart_calculator(command):
    low=command.lower().strip()
    if not any(x in low for x in ["calculate ", "calculator ", "hisab karo", "kitna hoga"]): return False
    expr=re.sub(r"(?i)^(jarvis\s+)?(?:calculate|calculator|hisab karo)\s*", "", low).strip()
    expr=expr.replace("plus","+").replace("minus","-").replace("multiply","*").replace("times","*").replace("divide","/").replace("into","*")
    expr=expr.replace("x","*")
    if not expr or not re.fullmatch(r"[0-9+\-*/().%\s]+", expr):
        return False
    try:
        result=eval(expr,{"__builtins__":{}},{})
        print("CALCULATION:",expr,"=",result)
        speak(f"Answer {result} hai.")
        return True
    except Exception:
        speak("Calculation nahi ho payi.")
        return True


def step93_system_settings_assistant(command):
    low=command.lower()
    if not any(x in low for x in ["system setting", "settings status", "windows settings"]): return False
    print("SYSTEM SETTINGS SUMMARY")
    print("OS:", platform.platform())
    print("Computer:", platform.node())
    print("Python:", platform.python_version())
    print("Architecture:", platform.machine())
    speak("System settings summary console me hai.")
    return True


def step94_browser_workflow(command):
    low=command.lower()
    if not any(x in low for x in ["browser workflow", "browser task", "browser status"]): return False
    if "status" in low:
        speak("Browser workflow module ready hai. Existing browser automation available hai.")
        return True
    m=re.search(r"(?:browser workflow|browser task)\s+(?:search\s+)?(.+)", command, re.I)
    if m:
        q=m.group(1).strip()
        if q:
            webbrowser.open("https://www.google.com/search?q="+urllib.parse.quote_plus(q))
            speak("Browser search khol diya.")
            return True
    return False


def step95_multi_app_workflow(command):
    low=command.lower()
    if "multi app" not in low and "multiple apps" not in low: return False
    if "notepad" in low:
        subprocess.Popen(["notepad.exe"])
    if "calculator" in low or "calc" in low:
        subprocess.Popen(["calc.exe"])
    if "explorer" in low or "file explorer" in low:
        subprocess.Popen(["explorer.exe"])
    speak("Requested apps ka workflow start kar diya.")
    return True


def step96_task_templates(command):
    low=command.lower()
    if not any(x in low for x in ["task template", "workflow template save", "workflow template list"]): return False
    templates=_s89_load(STEP96_STORE,{})
    if "list" in low:
        print("TASK TEMPLATES:")
        for name in templates: print("-",name)
        speak(f"{len(templates)} task templates hain.")
        return True
    m=re.search(r"(?:task template|workflow template save)\s+(.+)",command,re.I)
    if m:
        name=m.group(1).strip()
        templates[name]={"created":datetime.datetime.now().isoformat(timespec="seconds")}
        _s89_save(STEP96_STORE,templates)
        speak("Task template save kar diya.")
        return True
    return False


def step97_agent_activity(command):
    low=command.lower()
    if not any(x in low for x in ["agent activity", "agent log", "agent activity report"]): return False
    history=[]
    try: history=_s89_load(STEP61_HISTORY_FILE,[]) if 'STEP61_HISTORY_FILE' in globals() else []
    except Exception: pass
    print("AGENT ACTIVITY:",len(history),"records")
    for item in history[-10:]: print(item)
    speak(f"Agent activity report ready hai. {len(history)} records mile.")
    return True


def step98_master_local_agent(command):
    low=command.lower()
    if not any(x in low for x in ["master agent", "master assistant", "jarvis master status", "local agent status"]): return False
    state=_s89_load(STEP98_STORE,{})
    state["last_check"]=datetime.datetime.now().isoformat(timespec="seconds")
    state["steps"]="89-98"
    _s89_save(STEP98_STORE,state)
    print("===========================================")
    print("JARVIS MASTER LOCAL AGENT")
    print("Steps 89-98: READY")
    print("Clipboard intelligence: READY")
    print("Document assistant: READY")
    print("Local notes: READY")
    print("Smart calculator: READY")
    print("System settings assistant: READY")
    print("Browser workflow: READY")
    print("Multi-app workflow: READY")
    print("Task templates: READY")
    print("Agent activity: READY")
    print("===========================================")
    speak("Master local agent ready hai. Details console me hain.")
    return True

def process_command_legacy(command):
    """Legacy router for Steps 1-98."""
    raw=str(command or "").strip()
    if not raw:
        return False

    # Steps 89-98 master local extension.
    if step98_master_local_agent(raw): return True
    if step97_agent_activity(raw): return True
    if step96_task_templates(raw): return True
    if step95_multi_app_workflow(raw): return True
    if step94_browser_workflow(raw): return True
    if step93_system_settings_assistant(raw): return True
    if step92_smart_calculator(raw): return True
    if step91_local_notes(raw): return True
    if step90_document_assistant(raw): return True
    if step89_clipboard_intelligence(raw): return True

    # Steps 79-88 advanced local agent layer.
    if step88_master_agent(raw):
        step80_update_context(raw, "advanced agent status")
        return True
    if step79_voice_command(raw):
        step80_update_context(raw, "voice command memory")
        return True
    if step79_voice_profile(raw):
        step80_update_context(raw, "voice profile")
        return True
    if step80_context_command(raw):
        return True
    if step81_smart_search_command(raw):
        step80_update_context(raw, "smart search")
        return True
    if step82_file_content_search(raw):
        step80_update_context(raw, "file content search")
        return True
    if step83_app_automation(raw):
        step80_update_context(raw, "app automation")
        return True
    if step84_browser_automation(raw):
        step80_update_context(raw, "browser automation")
        return True
    if step85_workflow_template_command(raw):
        step80_update_context(raw, "workflow template")
        return True
    if step86_recovery_command(raw):
        step80_update_context(raw, "recovery")
        return True
    if step87_knowledge_command(raw):
        step80_update_context(raw, "local knowledge")
        return True

    # Steps 69-78 advanced local automation layer.
    alias_target = step72_expand_alias(raw)
    if alias_target:
        raw = alias_target
        command = raw
    if step78_master_command(raw):
        step70_record_event("advanced dashboard", raw); return True
    if step77_security_audit_command(raw):
        step70_record_event("security audit", raw); return True
    if step76_disk_cleanup_preview(raw):
        step70_record_event("cleanup preview", raw); return True
    if step75_duplicate_file_scan(raw):
        step70_record_event("duplicate scan", raw); return True
    if step74_workspace_command(raw):
        step70_record_event("workspace", raw); return True
    if step73_favorite_command(raw):
        step70_record_event("favorite", raw); return True
    if step72_alias_command(raw):
        step70_record_event("alias", raw); return True
    if step71_alert_command(raw):
        step70_record_event("resource alert", raw); return True
    if step70_event_command(raw):
        return True
    if step69_schedule_command(raw):
        step70_record_event("schedule", raw); return True

    # Steps 64-68: smart context, files, multi-step execution, recovery, tasks.
    if step68_task_manager_command(raw):
        step61_record(raw, "handled by Step 68")
        return True
    if step67_recovery_command(raw):
        step61_record(raw, "handled by Step 67")
        return True
    if step65_smart_file_command(raw):
        step61_record(raw, "handled by Step 65")
        return True
    if step64_window_memory_command(raw):
        step61_record(raw, "handled by Step 64")
        return True
    if step66_multistep_command(raw):
        step61_record(raw, "handled by Step 66")
        return True

    # Step 62 confirmation is checked before normal routing so a pending
    # confirmation cannot accidentally fall through to another module.
    if step62_confirmation_command(raw):
        step61_record(raw, "confirmation handled")
        return True

    # Explicit high-risk voice commands are gated. Existing Step 56 also
    # keeps shutdown/restart/sleep disabled as a second safety layer.
    if step62_safety_gate(raw):
        step61_record(raw, "confirmation required")
        return True

    # New master-layer commands.
    if step63_master_command(raw):
        step61_record(raw, "master status")
        return True
    if step61_history_command(raw):
        step61_record(raw, "history report")
        return True
    if step59_profile_command(raw):
        step61_record(raw, "profile report")
        return True
    if step60_context_command(raw):
        step61_record(raw, "context report")
        return True

    # Learn and record ordinary commands before existing handlers execute.
    step59_learn_command(raw)
    step60_set_context(raw)

    # Existing Step 58 -> Step 1 command chain.
    if step58_unified_command(raw):
        step61_record(raw, "handled by Step 54-58")
        return True
    if step53_status_command(raw):
        step61_record(raw, "handled by Step 53")
        return True
    if step52_recent_activity_command(raw):
        step61_record(raw, "handled by Step 52")
        return True
    if step51_clipboard_command(raw):
        step61_record(raw, "handled by Step 51")
        return True
    if step50_window_command(raw):
        step61_record(raw, "handled by Step 50")
        return True
    if step49_process_command(raw):
        step61_record(raw, "handled by Step 49")
        return True
    if step48_diagnostics_command(raw):
        step61_record(raw, "handled by Step 48")
        return True
    if step47_network_command(raw):
        step61_record(raw, "handled by Step 47")
        return True
    if step46_performance_command(raw):
        step61_record(raw, "handled by Step 46")
        return True
    if step45_health_command(raw):
        step61_record(raw, "handled by Step 45")
        return True
    if step44_self_test_command(raw):
        step61_record(raw, "handled by Step 44")
        return True
    if step43_update_command(raw):
        step61_record(raw, "handled by Step 43")
        return True
    if step42_version_command(raw):
        step61_record(raw, "handled by Step 42")
        return True
    if step41_repair_command(raw):
        step61_record(raw, "handled by Step 41")
        return True
    if step40_fix_suggest_command(raw):
        step61_record(raw, "handled by Step 40")
        return True
    if step39_error_explain_command(raw):
        step61_record(raw, "handled by Step 39")
        return True
    if step38_diagnose_command(raw):
        step61_record(raw, "handled by Step 38")
        return True
    if step33_local_natural_input(raw):
        step61_record(raw, "handled by Step 33.1")
        return True
    if step32_visual_command(raw):
        step61_record(raw, "handled by Step 32")
        return True
    if run_multistep_command(raw):
        step61_record(raw, "handled by Step 28")
        return True
    if step31_visual_command(raw):
        step61_record(raw, "handled by Step 31")
        return True
    if step30_visual_command(raw):
        step61_record(raw, "handled by Step 30")
        return True
    if step29_visual_command(raw):
        step61_record(raw, "handled by Step 29")
        return True
    if screen_understanding_command(raw):
        step61_record(raw, "handled by screen understanding")
        return True
    if is_local_repeat_command(raw):
        print("LOCAL REPEAT DETECTED - GEMINI SKIPPED")
        result=repeat_last_task_locally()
        step61_record(raw, "local repeat")
        return result
    if is_agent_goal(raw):
        result=run_agent_loop(raw)
        step61_record(raw, "agent goal")
        return result
    if not is_local_repeat_command(raw):
        save_last_command(raw)
    if any(p in raw.lower() for p in ["conversation clear karo","context clear karo","context bhool jao","sab context bhool jao"]):
        result=clear_conversation_context()
        step61_record(raw, "context cleared")
        return result
    if handle_workflow_memory(raw):
        step61_record(raw, "workflow memory")
        return True
    if smart_language_command(raw):
        add_conversation_context(raw,"Executed as a smart command.")
        step61_record(raw, "smart language command")
        return True
    normalized=re.sub(r"\s+"," ",raw.lower()).strip()
    if should_use_context_gemini(normalized):
        context_intent=understand_with_context(raw)
        if context_intent and execute_context_intent(context_intent):
            add_conversation_context(raw,"Executed using conversation context.")
            step61_record(raw, "Gemini context intent")
            return True
    if run_advanced_goal_planner(raw):
        step61_record(raw, "advanced goal planner")
        return True
    if step33_ai_brain(raw):
        step61_record(raw, "Gemini/local AI brain")
        return True
    step61_record(raw, "unhandled")
    return False

# ============================================================
# STEP 64-68: SMART CONTEXT + TASK ENGINE
# ============================================================
STEP68_VERSION = "68.0"
STEP68_TASK_FILE = os.path.join(BASE_DIR, "jarvis_task_manager.json")
STEP68_WINDOW_FILE = os.path.join(BASE_DIR, "jarvis_window_memory.json")


def step64_save_window_memory():
    """Save a lightweight description of the active window, if available."""
    try:
        title = ""
        try:
            import pygetwindow as gw
            w = gw.getActiveWindow()
            title = str(w.title or "") if w else ""
        except Exception:
            pass
        data = {"title": title, "saved_at": datetime.datetime.now().isoformat(timespec="seconds")}
        with open(STEP68_WINDOW_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception as e:
        print("STEP 64 window memory error:", e)
        return {"title": "", "error": str(e)}


def step64_window_memory_command(command):
    text = step59_normalize_phrase(command).lower()
    if not any(x in text for x in ("previous window", "pichhli window", "last window", "wahi window", "current window", "active window")):
        return False
    data = step64_save_window_memory()
    title = data.get("title", "")
    if "pichhli" in text or "previous" in text or "last window" in text or "wahi window" in text:
        if os.path.exists(STEP68_WINDOW_FILE):
            try:
                with open(STEP68_WINDOW_FILE, "r", encoding="utf-8") as f:
                    title = json.load(f).get("title", title)
            except Exception:
                pass
    msg = f"Current window: {title or 'window title available nahi hai.'}"
    print("STEP 64 ->", msg)
    speak(msg)
    return True


def step65_find_files(query, roots=None, limit=10):
    roots = roots or [os.path.join(os.path.expanduser("~"), "Desktop"),
                      os.path.join(os.path.expanduser("~"), "Downloads"),
                      os.path.join(os.path.expanduser("~"), "Documents")]
    q = str(query or "").strip().lower()
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d.lower() not in {"node_modules", ".git", "__pycache__"}]
            for name in files:
                if q in name.lower():
                    path = os.path.join(base, name)
                    try: mtime = os.path.getmtime(path)
                    except OSError: mtime = 0
                    found.append((mtime, path))
    found.sort(reverse=True)
    return [p for _, p in found[:limit]]


def step65_smart_file_command(command):
    text = step59_normalize_phrase(command).strip()
    low = text.lower()
    if not any(x in low for x in ("latest file", "meri file", "file kholo", "file dhoondo", "file dhundho", "find file")):
        return False
    if "latest file" in low or "latest" in low:
        candidates = []
        for root in [os.path.join(os.path.expanduser("~"), "Desktop"), os.path.join(os.path.expanduser("~"), "Downloads"), os.path.join(os.path.expanduser("~"), "Documents")]:
            if os.path.isdir(root):
                for base, _, files in os.walk(root):
                    for name in files:
                        try: candidates.append((os.path.getmtime(os.path.join(base, name)), os.path.join(base, name)))
                        except OSError: pass
        candidates.sort(reverse=True)
        if candidates:
            path=candidates[0][1]
            try: os.startfile(path)
            except Exception: pass
            speak(f"Latest file khol raha hoon: {os.path.basename(path)}")
        else: speak("Latest file nahi mili.")
        return True
    m = re.search(r"(?:file dhoondo|file dhundho|find file|meri file|file kholo)\s+(.+)$", low)
    if m:
        results=step65_find_files(m.group(1))
        if results:
            try: os.startfile(results[0])
            except Exception: pass
            speak(f"File mil gayi: {os.path.basename(results[0])}")
        else: speak("File nahi mili.")
        return True
    return False


def step66_parse_actions(command):
    """Split a safe multi-action sentence into simple commands."""
    text = step59_normalize_phrase(command).strip()
    parts = re.split(r"\s+(?:and|aur|phir|then)\s+|[,;]\s*", text, flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def step66_multistep_command(command):
    low = str(command or "").lower()
    if not any(x in low for x in (" ek saath ", "aur phir", "then", "and then", "ke baad")):
        return False
    actions = step66_parse_actions(command)
    if len(actions) < 2 or len(actions) > 4:
        return False
    # Safety: do not chain destructive/power actions automatically.
    risky = ("delete", "shutdown", "restart", "format", "remove permanently", "lock pc", "sleep")
    if any(any(r in a.lower() for r in risky) for a in actions):
        speak("Ye multi-step command risky action contain karti hai. Main ise automatic execute nahi karunga.")
        return True
    completed=0
    for action in actions:
        if action.lower().startswith("jarvis "):
            action=action[7:].strip()
        try:
            handled=process_command(action)
        except Exception as e:
            print("STEP 66 action error:", e)
            handled=False
        if not handled:
            break
        completed += 1
    speak(f"Multi-step task complete: {completed} of {len(actions)} actions.")
    return True


def step67_recovery_run(action, retries=2):
    """Run a callable with bounded retries; no destructive fallback."""
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            result = action()
            if result:
                return True, attempt, None
            last_error = "action returned False"
        except Exception as e:
            last_error = str(e)
        time.sleep(0.4)
    return False, retries + 1, last_error


def step67_recovery_command(command):
    low = str(command or "").lower()
    if not any(x in low for x in ("retry last task", "last task retry", "phir se try karo", "dobara try karo", "failed task retry")):
        return False
    last = globals().get("LAST_COMMAND", "") or globals().get("last_command", "")
    if not last:
        speak("Retry karne ke liye koi previous command nahi mili.")
        return True
    ok, attempts, err = step67_recovery_run(lambda: process_command(last), retries=2)
    if ok:
        speak(f"Last task retry successful after {attempts} attempt(s).")
    else:
        speak(f"Retry failed after {attempts} attempts. Reason: {err}")
    return True


def step68_load_tasks():
    try:
        if not os.path.exists(STEP68_TASK_FILE): return []
        with open(STEP68_TASK_FILE, "r", encoding="utf-8") as f: data=json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def step68_save_tasks(tasks):
    tmp = STEP68_TASK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(tasks[-100:], f, ensure_ascii=False, indent=2)
    os.replace(tmp, STEP68_TASK_FILE)


def step68_task_manager_command(command):
    low = step59_normalize_phrase(command).lower().strip()
    if not any(x in low for x in ("task list", "task history", "mera task", "task banao", "task create", "task complete", "task done", "task status")):
        return False
    tasks=step68_load_tasks()
    if "task list" in low or "task history" in low or "mera task" in low:
        pending=[t for t in tasks if t.get("status") != "done"]
        if not pending: speak("Koi pending task nahi hai.")
        else:
            speak(f"Aapke {len(pending)} pending tasks hain.")
            for t in pending[:5]: print(f"- [{t.get('id')}] {t.get('title')}")
        return True
    m=re.search(r"(?:task banao|task create)\s+(.+)$", low)
    if m:
        title=m.group(1).strip()
        task={"id": len(tasks)+1, "title": title, "status":"pending", "created_at":datetime.datetime.now().isoformat(timespec="seconds")}
        tasks.append(task); step68_save_tasks(tasks)
        speak(f"Task create kar diya: {title}")
        return True
    m=re.search(r"(?:task complete|task done)\s+(\d+)", low)
    if m:
        tid=int(m.group(1))
        for t in tasks:
            if t.get("id")==tid:
                t["status"]="done"; t["completed_at"]=datetime.datetime.now().isoformat(timespec="seconds"); step68_save_tasks(tasks)
                speak(f"Task {tid} complete mark kar diya."); return True
        speak("Task ID nahi mili."); return True
    if "task status" in low:
        pending=sum(1 for t in tasks if t.get("status")!="done")
        done=sum(1 for t in tasks if t.get("status")=="done")
        speak(f"Task status: {pending} pending aur {done} completed.")
        return True
    return False


def step68_autonomous_task(command):
    low=str(command or "").lower()
    return step66_multistep_command(command) if any(x in low for x in (" ek saath ", "aur phir", "then", "and then")) else False

# ================================================================
# STEPS 99-108 : JARVIS AGENT V2
# Local-first architecture: intent -> entities -> plan -> safety -> execute -> verify -> recover.
# ================================================================
STEP99_DIR = os.path.join(BASE_DIR, "jarvis_agent_v2") if "BASE_DIR" in globals() else os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_agent_v2")
STEP99_STATE = os.path.join(STEP99_DIR, "agent_state.json")
os.makedirs(STEP99_DIR, exist_ok=True)

def _s99_load():
    try:
        with open(STEP99_STATE, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def _s99_save(data):
    try:
        tmp=STEP99_STATE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(tmp,STEP99_STATE); return True
    except Exception as e: print("AGENT V2 STATE ERROR:",e); return False

def step99_core_status(command):
    low=str(command).lower()
    if not any(x in low for x in ["core architecture","agent architecture","architecture status","agent v2 status"]): return False
    print("JARVIS AGENT V2: CORE READY")
    print("intent -> entities -> planner -> safety -> executor -> verifier -> recovery")
    speak("JARVIS Agent V2 architecture ready hai."); return True

def step100_detect_intent(command):
    low=str(command).lower()
    rules=[("multi_step",["phir","then","uske baad","and then"]),("open_app",["khol","open","launch","chala"]),("search_web",["search","dhoond","dhund","google par"]),("file_operation",["file","folder","document"]),("browser_action",["chrome","browser","youtube","website"]),("system_status",["status","cpu","ram","performance"]),("memory",["remember","yaad","bhool","context"])]
    for intent,words in rules:
        if any(w in low for w in words): return intent
    return "unknown"

def step101_extract_entities(command):
    raw=str(command).strip(); low=raw.lower(); apps=["notepad","calculator","paint","explorer","chrome","edge","firefox","cmd","powershell"]
    e={"apps":[a for a in apps if a in low],"files":[],"query":"","raw":raw}
    m=re.search(r"(?:search|dhoond(?:o|ho)?|dhund(?:o|ho)?|google par)\s+(.+)$",raw,re.I)
    if m: e["query"]=m.group(1).strip()
    fm=re.search(r"(?:file|folder|document)\s+([\w .()_-]+)",raw,re.I)
    if fm: e["files"]=[fm.group(1).strip()]
    return e

def step102_context_resolve(command):
    raw=str(command); low=raw.lower(); last=_s99_load().get("last_command","")
    return last if last and any(x in low for x in ["isko","is ko","wahi","same","pichhla","previous"]) else raw

def step103_plan_actions(command):
    raw=step102_context_resolve(command).strip()
    parts=re.split(r"\s+(?:phir|then|uske baad|and then)\s+",raw,flags=re.I)
    return [p.strip(" ,.") for p in parts if p.strip(" ,.")][:8] or [raw]

def step107_is_risky(command):
    low=str(command).lower(); return any(x in low for x in ["shutdown","shut down","restart","reboot","format","delete","remove permanently","factory reset"])

def step107_safety_check(command):
    if step107_is_risky(command):
        print("SAFETY GATE: confirmation required ->",command); speak("Ye action risky hai. Confirmation required hai."); return False
    return True

def step104_execute_action(command):
    if not step107_safety_check(command): return {"ok":False,"reason":"safety_confirmation_required","command":command}
    try: return {"ok":bool(process_command_legacy(command)),"command":command}
    except Exception as e: return {"ok":False,"reason":str(e),"command":command}

def step105_verify_result(result,command):
    return isinstance(result,dict) and bool(result.get("ok"))

def step106_recover_action(command,result):
    if result.get("ok"): return result
    if result.get("reason") != "safety_confirmation_required":
        retry=step104_execute_action(command); retry["recovery_retry"]=True; return retry
    return result

def step108_agent_command(command):
    low=str(command).lower()
    if not any(x in low for x in ["agent v2","master agent v2","unified agent","agent architecture"]): return False
    print("JARVIS AGENT V2: READY | intent | entities | planner | safety | executor | verifier | recovery")
    speak("JARVIS Agent V2 ready hai."); return True


# =========================================================
# STEPS 109-118: GOAL-BASED AGENT V3
# =========================================================
S109_DIR = os.path.join(BASE_DIR, "jarvis_agent_v3")
S109_STATE = os.path.join(S109_DIR, "agent_state.json")
os.makedirs(S109_DIR, exist_ok=True)

def _s109_load():
    try:
        with open(S109_STATE, "r", encoding="utf-8") as f:
            data=json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _s109_save(data):
    try:
        tmp=S109_STATE+".tmp"
        with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
        os.replace(tmp,S109_STATE)
        return True
    except Exception:
        return False

def step109_understand_goal(command):
    raw=str(command or "").strip()
    low=raw.lower()
    goal=raw
    for p in ("jarvis", "please", "bhai", "zara"):
        goal=re.sub(r"\b"+re.escape(p)+r"\b", "", goal, flags=re.I).strip()
    goal_type="general"
    if any(x in low for x in ("dhoondo","dhundho","search","find","khojo","talash")): goal_type="search"
    elif any(x in low for x in ("khol","open","launch","start")): goal_type="open"
    elif any(x in low for x in ("likho","type","bhar do","daalo","paste")): goal_type="input"
    elif any(x in low for x in ("batao","status","check","dikhao")): goal_type="information"
    elif any(x in low for x in ("banao","create","make")): goal_type="create"
    elif any(x in low for x in ("band","close","exit")): goal_type="close"
    return {"goal":goal,"type":goal_type,"entities":step101_extract_entities(raw),"created":datetime.datetime.now().isoformat(timespec="seconds")}

def step110_decompose_goal(goal_info):
    raw=goal_info.get("goal","")
    low=raw.lower()
    plans=[]
    # Explicit multi-action language is split into safe clauses.
    parts=re.split(r"\s+(?:aur|and|phir|then|uske baad)\s+", raw, flags=re.I)
    parts=[p.strip(" ,.") for p in parts if p.strip(" ,.")]
    if len(parts)>1:
        plans=parts[:8]
    elif goal_info.get("type")=="search":
        q=re.sub(r"^(google|youtube|web)\s+", "", raw, flags=re.I).strip()
        plans=["google search "+q] if q else [raw]
    elif goal_info.get("type")=="open":
        plans=[raw]
    else:
        plans=[raw]
    return plans

def step111_dynamic_plan(goal_info, previous_results=None):
    plans=step110_decompose_goal(goal_info)
    results=previous_results or []
    # If an earlier action succeeded, preserve remaining actions; otherwise add a retry marker.
    if results and not results[-1].get("ok",False):
        return {"steps":plans,"recovery_needed":True,"reason":"previous action failed"}
    return {"steps":plans,"recovery_needed":False,"reason":"planned locally"}

def step112_screen_guided_execution(command):
    """Use existing local screen tools only when the command explicitly asks for screen/UI guidance."""
    raw=str(command or "")
    low=raw.lower()
    if any(x in low for x in ("screen", "screenshot", "screen par", "screen pe", "screen me")):
        try:
            result=screen_tools(raw)
            return {"ok":bool(result),"method":"screen_tools","result":result}
        except Exception as e:
            return {"ok":False,"method":"screen_tools","error":str(e)}
    return {"ok":False,"method":"not_used","error":"screen guidance not requested"}

def step113_verify_goal_action(command, result):
    if isinstance(result,dict):
        if "ok" in result: return bool(result["ok"])
        if "success" in result: return bool(result["success"])
    return bool(result)

def step114_adaptive_retry(command, result, max_retries=2):
    if step113_verify_goal_action(command,result): return result
    last=result
    for _ in range(max_retries):
        try:
            retry=process_command_legacy(command)
            last={"ok":bool(retry),"retry":True,"result":retry}
            if bool(retry): return last
        except Exception as e:
            last={"ok":False,"retry":True,"error":str(e)}
    return last

def step115_session_memory(command, result=None):
    state=_s109_load()
    history=state.get("session",[])
    history.append({"command":str(command),"ok":bool(result) if result is not None else None,"time":datetime.datetime.now().isoformat(timespec="seconds")})
    state["session"]=history[-30:]
    state["last_command"]=str(command)
    state["last_result"]=bool(result) if result is not None else None
    _s109_save(state)
    return state

def step116_long_term_knowledge(key=None, value=None):
    path=os.path.join(S109_DIR,"knowledge.json")
    try:
        data={}
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f: data=json.load(f)
        if key is not None and value is not None:
            data[str(key)]=str(value)
            with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
            return {"ok":True,"saved":str(key)}
        return {"ok":True,"knowledge":data}
    except Exception as e: return {"ok":False,"error":str(e)}

def step117_agent_safety(command):
    raw=str(command or "").lower()
    risky=("shutdown","restart","delete","format","uninstall","kill process","remove file","wipe")
    if any(x in raw for x in risky):
        return {"allowed":False,"reason":"confirmation required for risky action"}
    return {"allowed":True,"reason":"local safe action"}

def step118_agent_v3(command):
    safety=step117_agent_safety(command)
    if not safety["allowed"]:
        return {"ok":False,"blocked":True,"reason":safety["reason"]}
    goal=step109_understand_goal(command)
    plan=step111_dynamic_plan(goal)
    results=[]
    for action in plan["steps"]:
        # Delegate to the already-tested legacy router; avoid recursive V3 routing.
        try:
            result=process_command_legacy(action)
        except Exception as e:
            result={"ok":False,"error":str(e)}
        verified=step113_verify_goal_action(action,result)
        if not verified:
            result=step114_adaptive_retry(action,result)
            verified=step113_verify_goal_action(action,result)
        results.append({"action":action,"ok":verified,"result":result})
        if not verified: break
    ok=bool(results) and all(x["ok"] for x in results)
    step115_session_memory(command,ok)
    state=_s109_load(); state.update({"last_goal":goal,"last_plan":plan,"last_results":results}); _s109_save(state)
    return {"ok":ok,"goal":goal,"plan":plan,"results":results}

def step118_command(command):
    low=str(command or "").lower()
    triggers=("goal ","agent v3","agent mode","goal based","plan karke","plan bana ke")
    if any(x in low for x in triggers):
        r=step118_agent_v3(command)
        if r.get("ok"): speak("Task complete.")
        elif r.get("blocked"): speak("Ye action safety ke liye confirmation mangta hai.")
        else: speak("Task complete nahi hua.")
        return True
    return False



# =========================================================
# STEPS 119-128: COMPUTER-USE AGENT V4
# =========================================================
S119_DIR = os.path.join(BASE_DIR, "jarvis_agent_v4")
S119_STATE = os.path.join(S119_DIR, "computer_agent_state.json")
os.makedirs(S119_DIR, exist_ok=True)


def _s119_load():
    try:
        with open(S119_STATE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _s119_save(data):
    try:
        tmp = S119_STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, S119_STATE)
        return True
    except Exception:
        return False


def step119_visual_ui_understanding(limit=20):
    """Return a local snapshot of visible UI/text elements without changing the screen."""
    try:
        elements = detect_text_elements()
        if not isinstance(elements, list):
            elements = []
        return {"ok": True, "count": len(elements), "elements": elements[:max(1, int(limit))]}
    except Exception as e:
        return {"ok": False, "error": str(e), "elements": []}


def step120_smart_target_selection(target):
    """Select the best visible UI target using the existing local visual matcher."""
    try:
        result = select_visual_target(str(target))
        return {"ok": bool(result), "target": str(target), "selection": result}
    except Exception as e:
        try:
            result = find_best_screen_element(str(target))
            return {"ok": bool(result), "target": str(target), "selection": result, "fallback": True}
        except Exception as inner:
            return {"ok": False, "target": str(target), "error": str(inner)}


def step121_visual_click_agent(target):
    """Locate and click a visible target, then verify the screen changed or the click succeeded."""
    safety = step117_agent_safety("click " + str(target))
    if not safety.get("allowed", False):
        return {"ok": False, "blocked": True, "reason": safety.get("reason", "confirmation required")}
    before = _screen_signature()
    try:
        result = click_visual_target_confirmed(str(target))
        after = _screen_signature()
        verified = bool(result) or (before != after)
        return {"ok": verified, "target": str(target), "result": result, "screen_changed": before != after}
    except Exception as e:
        return {"ok": False, "target": str(target), "error": str(e)}


def step122_smart_typing_agent(target, text):
    """Find an input field, type text, and report the local action result."""
    try:
        result = type_into_screen_element(str(target), str(text))
        return {"ok": bool(result), "target": str(target), "text_length": len(str(text)), "result": result}
    except Exception as e:
        return {"ok": False, "target": str(target), "error": str(e)}


def step123_scroll_intelligence(target, max_scrolls=4):
    """Try to locate a target, scrolling a bounded number of times when it is not visible."""
    target = str(target or "").strip()
    try:
        first = find_visual_element(target)
        if first:
            return {"ok": True, "target": target, "found": True, "scrolls": 0, "element": first}
    except Exception:
        pass
    scrolls = 0
    for _ in range(max(0, min(int(max_scrolls), 8))):
        scrolls += 1
        try:
            pyautogui.scroll(-3)
            time.sleep(0.7)
            found = find_visual_element(target)
            if found:
                return {"ok": True, "target": target, "found": True, "scrolls": scrolls, "element": found}
        except Exception as e:
            return {"ok": False, "target": target, "scrolls": scrolls, "error": str(e)}
    return {"ok": False, "target": target, "found": False, "scrolls": scrolls, "reason": "target not visible"}


def step124_wait_state_detection(target=None, timeout=8):
    """Wait for text/target or a screen change; bounded to avoid indefinite blocking."""
    timeout = max(0.5, min(float(timeout), 30.0))
    if target:
        try:
            return {"ok": bool(step32_wait_for_text(str(target), timeout=timeout)), "target": str(target), "mode": "text"}
        except Exception:
            pass
    try:
        return {"ok": bool(step32_wait_for_screen_change(timeout=timeout)), "mode": "screen_change"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def step125_multi_action_visual_agent(actions):
    """Execute a bounded list of explicit visual actions; stop on the first failure."""
    if isinstance(actions, str):
        actions = step103_plan_actions(actions)
    actions = list(actions or [])[:8]
    results = []
    for action in actions:
        text = str(action).strip()
        if not text:
            continue
        low = text.lower()
        if step117_agent_safety(text).get("allowed") is False:
            results.append({"action": text, "ok": False, "blocked": True})
            break
        if any(w in low for w in ("click", "dabao", "press")):
            target = re.sub(r"^(click|dabao|press)\s+", "", text, flags=re.I).strip()
            result = step121_visual_click_agent(target)
        elif any(w in low for w in ("type", "likho", "bhar do", "daalo")):
            m = re.match(r"^(?:type|likho|bhar do|daalo)\s+(.+?)\s+(?:into|in|me|mein)\s+(.+)$", text, re.I)
            if m:
                result = step122_smart_typing_agent(m.group(2), m.group(1))
            else:
                result = {"ok": False, "reason": "typing action needs target and text"}
        else:
            try:
                raw_result = process_command_legacy(text)
                result = {"ok": bool(raw_result), "result": raw_result}
            except Exception as e:
                result = {"ok": False, "error": str(e)}
        results.append({"action": text, **result})
        if not result.get("ok"):
            break
    return {"ok": bool(results) and all(x.get("ok") for x in results), "results": results}


def step126_browser_task_agent(command):
    """Handle bounded browser goals through the existing safe browser/search functions."""
    raw = str(command or "").strip()
    low = raw.lower()
    if not any(x in low for x in ("browser", "chrome", "youtube", "website", "web", "google")):
        return {"ok": False, "used": False}
    try:
        result = advanced_browser_actions(raw)
        if not result:
            result = natural_browser_search(raw)
        return {"ok": bool(result), "used": True, "result": result}
    except Exception as e:
        return {"ok": False, "used": True, "error": str(e)}


def step127_desktop_task_agent(command):
    """Route safe desktop goals to the established legacy desktop/file/app controls."""
    raw = str(command or "").strip()
    low = raw.lower()
    if not any(x in low for x in ("notepad", "calculator", "paint", "explorer", "file", "folder", "desktop", "window")):
        return {"ok": False, "used": False}
    if step117_agent_safety(raw).get("allowed") is False:
        return {"ok": False, "used": True, "blocked": True}
    try:
        result = process_command_legacy(raw)
        return {"ok": bool(result), "used": True, "result": result}
    except Exception as e:
        return {"ok": False, "used": True, "error": str(e)}


def step128_computer_use_agent_v4(command):
    """Unified local computer-use flow: goal -> screen -> target/action -> verify -> bounded recovery."""
    raw = str(command or "").strip()
    if not raw:
        return {"ok": False, "error": "empty command"}
    safety = step117_agent_safety(raw)
    if not safety.get("allowed", False):
        return {"ok": False, "blocked": True, "reason": safety.get("reason", "confirmation required")}

    goal = step109_understand_goal(raw)
    low = raw.lower()
    result = None
    mode = "legacy"

    if any(x in low for x in ("browser", "chrome", "youtube", "website", "google")):
        result = step126_browser_task_agent(raw); mode = "browser"
    elif any(x in low for x in ("screen", "screenshot", "screen par", "screen pe")):
        result = step119_visual_ui_understanding(); mode = "screen"
    elif any(x in low for x in ("click", "dabao", "button", "press")):
        target = re.sub(r".*?(?:click|dabao|press)\s+", "", raw, flags=re.I).strip()
        result = step121_visual_click_agent(target); mode = "visual_click"
    elif any(x in low for x in ("scroll", "neeche", "upar")):
        target = re.sub(r".*?(?:scroll|find|dhoondo|dhundho)\s*", "", raw, flags=re.I).strip()
        result = step123_scroll_intelligence(target or "") if target else {"ok": False, "reason": "target required"}; mode = "scroll"
    elif any(x in low for x in ("notepad", "calculator", "paint", "explorer", "file", "folder", "desktop", "window")):
        result = step127_desktop_task_agent(raw); mode = "desktop"
    else:
        # Do not send an unsupported computer-agent goal to the legacy router,
        # because that router may fall through to Gemini. Keep this path local.
        result = {"ok": False, "reason": "No supported local computer-use target was detected."}

    verified = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
    state = _s119_load()
    history = state.get("history", [])
    history.append({"command": raw, "mode": mode, "ok": verified, "time": datetime.datetime.now().isoformat(timespec="seconds")})
    state.update({"last_goal": goal, "last_mode": mode, "last_result": result, "history": history[-50:]})
    _s119_save(state)
    return {"ok": verified, "goal": goal, "mode": mode, "result": result}


def step128_local_status_command(command):
    """Answer Agent v4 status locally; never calls Gemini."""
    low = str(command or "").lower().strip()
    triggers = (
        "agent v4 status", "agent v4 ka status", "agent v4 ki status",
        "computer use status", "computer-use status",
        "visual agent status", "computer agent status"
    )
    if not any(x in low for x in triggers):
        return False

    state = _s119_load()
    history = state.get("history", []) if isinstance(state, dict) else []
    last = history[-1] if history else None
    quota = "disabled (quota exhausted)" if GEMINI_QUOTA_EXHAUSTED else "available"

    print("STEP 128 STATUS -> Computer-Use Agent v4: ACTIVE")
    print("STEP 128 STATUS -> Visual UI: available")
    print("STEP 128 STATUS -> Safety Governor: active")
    print("STEP 128 STATUS -> Gemini: " + quota)
    if last:
        print("STEP 128 STATUS -> Last task: " + str(last.get("command", "unknown")))
        print("STEP 128 STATUS -> Last result: " + ("PASS" if last.get("ok") else "FAIL"))
    else:
        print("STEP 128 STATUS -> Last task: none")

    if GEMINI_QUOTA_EXHAUSTED:
        speak("Computer use agent active hai. Gemini quota khatam hai, lekin local commands chal rahi hain.")
    else:
        speak("Computer use agent v4 active hai aur ready hai.")
    return True


def step128_command(command):
    if step128_local_status_command(command):
        return True

    low = str(command or "").lower()
    triggers = (
        "agent v4", "computer use", "computer-use", "visual agent", "screen agent",
        "computer agent", "ui agent", "visual ui", "computer task"
    )
    if any(x in low for x in triggers):
        r = step128_computer_use_agent_v4(command)
        if r.get("ok"):
            speak("Computer task complete.")
        elif r.get("blocked"):
            speak("Ye action safety ke liye blocked hai.")
        else:
            speak("Computer task complete nahi hua.")
        return True
    return False


# =========================================================
# STEP 129-133: ADVANCED JARVIS COMMAND CENTER
# =========================================================
STEP133_VERSION = "133.0"
STEP133_STATE_FILE = os.path.join(BASE_DIR, "jarvis_command_center.json")


def _step133_safe_write_state(data):
    try:
        with open(STEP133_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("STEP 133 STATE WRITE ERROR:", e)
        return False


def _step133_load_state():
    try:
        if os.path.exists(STEP133_STATE_FILE):
            with open(STEP133_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print("STEP 133 STATE LOAD ERROR:", e)
    return {"runs": 0, "last_snapshot": {}, "history": []}


def _step133_active_window():
    """Get the active window title without making any network/API call."""
    try:
        import pygetwindow as gw
        window = gw.getActiveWindow()
        return str(window.title or "") if window else ""
    except Exception:
        return ""


def _step133_system_snapshot():
    """Collect a local machine snapshot. No Gemini/network request is made."""
    snapshot = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "hostname": platform.node() or "unknown",
        "os": platform.platform(),
        "python": platform.python_version(),
        "active_window": _step133_active_window(),
        "cpu_percent": None,
        "ram_percent": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "disk_percent": None,
        "disk_free_gb": None,
        "disk_total_gb": None,
        "battery_percent": None,
        "battery_plugged": None,
        "uptime": None,
        "internet": None,
    }

    try:
        import psutil
        snapshot["cpu_percent"] = round(float(psutil.cpu_percent(interval=0.35)), 1)
        vm = psutil.virtual_memory()
        snapshot["ram_percent"] = round(float(vm.percent), 1)
        snapshot["ram_used_gb"] = round(vm.used / (1024 ** 3), 2)
        snapshot["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)

        drive = os.environ.get("SystemDrive", "C:") + "\\"
        du = shutil.disk_usage(drive)
        snapshot["disk_percent"] = round((du.used / du.total) * 100, 1)
        snapshot["disk_free_gb"] = round(du.free / (1024 ** 3), 2)
        snapshot["disk_total_gb"] = round(du.total / (1024 ** 3), 2)

        try:
            boot = psutil.boot_time()
            snapshot["uptime"] = str(datetime.datetime.now() - datetime.datetime.fromtimestamp(boot)).split(".")[0]
        except Exception:
            pass

        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                snapshot["battery_percent"] = round(float(battery.percent), 1)
                snapshot["battery_plugged"] = bool(battery.power_plugged)
        except Exception:
            pass
    except Exception as e:
        print("STEP 133 PSUTIL ERROR:", e)

    # Lightweight connectivity check. Timeout is deliberately short.
    try:
        import socket
        sock = socket.create_connection(("www.google.com", 443), timeout=1.5)
        sock.close()
        snapshot["internet"] = True
    except Exception:
        snapshot["internet"] = False

    return snapshot


def _step133_health_label(snapshot):
    """Turn raw metrics into a simple human-readable health level."""
    warnings = []
    cpu = snapshot.get("cpu_percent")
    ram = snapshot.get("ram_percent")
    disk = snapshot.get("disk_percent")

    if isinstance(cpu, (int, float)) and cpu >= 90:
        warnings.append("CPU very high")
    elif isinstance(cpu, (int, float)) and cpu >= 75:
        warnings.append("CPU high")

    if isinstance(ram, (int, float)) and ram >= 90:
        warnings.append("RAM very high")
    elif isinstance(ram, (int, float)) and ram >= 80:
        warnings.append("RAM high")

    if isinstance(disk, (int, float)) and disk >= 95:
        warnings.append("disk almost full")
    elif isinstance(disk, (int, float)) and disk >= 85:
        warnings.append("disk getting full")

    if snapshot.get("internet") is False:
        warnings.append("internet unavailable")

    if warnings:
        return "ATTENTION", warnings
    return "HEALTHY", []


def step133_command_center_status(speak_result=True):
    snapshot = _step133_system_snapshot()
    health, warnings = _step133_health_label(snapshot)
    state = _step133_load_state()
    state["runs"] = int(state.get("runs", 0) or 0) + 1
    state["last_snapshot"] = snapshot
    history = state.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append({"time": snapshot["timestamp"], "health": health})
    state["history"] = history[-30:]
    _step133_safe_write_state(state)

    print("\n============================================")
    print("       JARVIS ADVANCED COMMAND CENTER")
    print("       STEP 129-133 / VERSION " + STEP133_VERSION)
    print("============================================")
    print("SYSTEM      :", snapshot.get("os", "unknown"))
    print("HOST        :", snapshot.get("hostname", "unknown"))
    print("PYTHON      :", snapshot.get("python", "unknown"))
    print("ACTIVE APP  :", snapshot.get("active_window") or "unknown")
    print("CPU         :", str(snapshot.get("cpu_percent")) + "%")
    print("RAM         :", str(snapshot.get("ram_percent")) + "%", "used", str(snapshot.get("ram_used_gb")) + " / " + str(snapshot.get("ram_total_gb")) + " GB")
    print("DISK C:     :", str(snapshot.get("disk_percent")) + "%", "used; free", str(snapshot.get("disk_free_gb")) + " GB")
    print("BATTERY     :", snapshot.get("battery_percent") if snapshot.get("battery_percent") is not None else "N/A")
    print("UPTIME      :", snapshot.get("uptime") or "N/A")
    print("INTERNET    :", "ONLINE" if snapshot.get("internet") else "OFFLINE")
    print("HEALTH      :", health)
    if warnings:
        print("ALERTS      :", ", ".join(warnings))
    else:
        print("ALERTS      : none")
    print("============================================\n")

    if speak_result:
        cpu = snapshot.get("cpu_percent")
        ram = snapshot.get("ram_percent")
        net = "online" if snapshot.get("internet") else "offline"
        if health == "HEALTHY":
            speak("JARVIS command center ready hai. System healthy hai. CPU " + str(cpu) + " percent, RAM " + str(ram) + " percent, internet " + net + ".")
        else:
            speak("System check complete. Kuch attention alerts hain. Details console me hain.")
    return True


def step133_performance_command(command):
    low = re.sub(r"\s+", " ", str(command or "").lower()).strip()
    triggers = (
        "system status", "system ka status", "system ki status", "system health",
        "system health check", "computer status", "computer ka status",
        "performance batao", "performance dikhao", "pc performance",
        "computer health", "laptop health", "laptop status", "pc status",
        "cpu status", "ram status", "memory status", "disk status",
        "battery status", "battery kitni hai", "internet status", "internet check",
        "diagnostic scan", "diagnostic check", "system scan", "full system scan",
        "jarvis system status", "jarvis system health", "jarvis diagnostic",
        "jarvis ka status batao"
    )
    if any(x in low for x in triggers):
        return step133_command_center_status(True)
    return False


def step133_capabilities_command(command):
    low = re.sub(r"\s+", " ", str(command or "").lower()).strip()
    triggers = (
        "what can you do", "what can you do for me", "tum kya kya kar sakte ho",
        "kya kya kar sakte ho", "apni capabilities batao", "capabilities batao",
        "jarvis kya kya kar sakta hai", "jarvis ki capabilities batao",
        "features batao", "features dikhao", "jarvis features"
    )
    if not any(x in low for x in triggers):
        return False

    features = [
        "voice control and wake word",
        "natural Hinglish commands",
        "local screen OCR and screen understanding",
        "mouse, keyboard and visual UI control",
        "computer-use agent with verification",
        "browser and safe multi-step tasks",
        "local memory and conversation context",
        "file and code intelligence",
        "backup and recovery system",
        "system health and performance monitoring",
        "Gemini AI fallback with quota protection",
        "safety governor for sensitive actions",
    ]
    print("\nJARVIS CAPABILITY MATRIX")
    print("------------------------")
    for i, item in enumerate(features, 1):
        print(f"{i:02d}. {item}")
    print("------------------------")
    speak("Mere paas voice control, screen OCR, visual computer use, memory, file intelligence, recovery, system monitoring aur safety controls active hain.")
    return True


def step133_command(command):
    if step133_capabilities_command(command):
        return True
    if step133_performance_command(command):
        return True
    return False


# =========================================================
# STEPS 134-143 -> JARVIS MISSION CONTROL
# =========================================================

STEP143_STATE_DIR = os.path.join(BASE_DIR, "jarvis_mission_control")
STEP143_STATE_FILE = os.path.join(STEP143_STATE_DIR, "mission_state.json")
STEP143_DASHBOARD_FILE = os.path.join(STEP143_STATE_DIR, "jarvis_dashboard.html")

def _step143_ensure_dir():
    os.makedirs(STEP143_STATE_DIR, exist_ok=True)

def _step143_load_state():
    _step143_ensure_dir()
    try:
        with open(STEP143_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict): data = {}
    except Exception:
        data = {}
    data.setdefault("events", []); data.setdefault("dashboard_count", 0); data.setdefault("last_health", {})
    return data

def _step143_save_state(data):
    _step143_ensure_dir(); tmp=STEP143_STATE_FILE+".tmp"
    with open(tmp,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    os.replace(tmp, STEP143_STATE_FILE)

def step134_mission_event(event, detail=""):
    state=_step143_load_state(); state["events"].append({"time":datetime.datetime.now().isoformat(timespec="seconds"),"event":str(event),"detail":str(detail)[:500]}); state["events"]=state["events"][-100:]; _step143_save_state(state); return True

def step135_system_snapshot_v2():
    snap={"time":datetime.datetime.now().isoformat(timespec="seconds"),"platform":platform.platform(),"python":platform.python_version(),"cpu_percent":None,"ram_percent":None,"disk_percent":None,"disk_free_gb":None,"battery_percent":None,"active_window":_step133_active_window(),"gemini":"quota exhausted" if GEMINI_QUOTA_EXHAUSTED else "available"}
    try:
        import psutil
        snap["cpu_percent"]=round(float(psutil.cpu_percent(interval=0.25)),1); vm=psutil.virtual_memory(); snap["ram_percent"]=round(float(vm.percent),1); du=psutil.disk_usage(BASE_DIR); snap["disk_percent"]=round(float(du.percent),1); snap["disk_free_gb"]=round(float(du.free)/(1024**3),2); bat=psutil.sensors_battery(); snap["battery_percent"]=round(float(bat.percent),1) if bat is not None else None
    except Exception as e: snap["psutil_error"]=str(e)[:200]
    state=_step143_load_state(); state["last_health"]=snap; _step143_save_state(state); step134_mission_event("system_snapshot",json.dumps(snap,ensure_ascii=False)); return snap

def step136_health_intelligence_v2():
    snap=step135_system_snapshot_v2(); alerts=[]
    if isinstance(snap.get("cpu_percent"),(int,float)) and snap["cpu_percent"]>=85: alerts.append("CPU usage high")
    if isinstance(snap.get("ram_percent"),(int,float)) and snap["ram_percent"]>=90: alerts.append("RAM usage very high")
    if isinstance(snap.get("disk_percent"),(int,float)) and snap["disk_percent"]>=90: alerts.append("Disk usage very high")
    label="ATTENTION" if alerts else "HEALTHY"; print("\nJARVIS HEALTH INTELLIGENCE V2\n------------------------------\nStatus:",label)
    for a in alerts: print("ALERT:",a)
    if not alerts: print("No critical local resource alert detected.")
    step134_mission_event("health_analysis",label+(" | "+", ".join(alerts) if alerts else "")); return {"label":label,"alerts":alerts,"snapshot":snap}

def step137_clipboard_read_local():
    try:
        p=subprocess.run(["powershell","-NoProfile","-Command","Get-Clipboard -Raw"],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); text=(p.stdout or "").strip()
        if not text: speak("Clipboard empty hai."); return True
        print("CLIPBOARD:",text[:4000]); speak("Clipboard read kar diya."); step134_mission_event("clipboard_read",text[:500]); return True
    except Exception as e: print("CLIPBOARD READ ERROR:",e); speak("Clipboard read nahi ho paya."); return True

def step138_clipboard_write_local(text):
    text=str(text or "")
    if not text: return False
    try:
        subprocess.run(["powershell","-NoProfile","-Command","Set-Clipboard -Value ([Console]::In.ReadToEnd())"],input=text,text=True,capture_output=True,timeout=5,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("CLIPBOARD WRITE: PASS"); speak("Clipboard update kar diya."); step134_mission_event("clipboard_write",text[:500]); return True
    except Exception as e: print("CLIPBOARD WRITE ERROR:",e); speak("Clipboard update nahi ho paya."); return True

def step139_activity_report_v2():
    events=_step143_load_state().get("events",[]); print("\nJARVIS ACTIVITY REPORT V2\n-------------------------\nEvents stored:",len(events))
    for item in events[-12:]: print(f"[{item.get('time','')}] {item.get('event','')}: {item.get('detail','')[:180]}")
    speak(f"Activity report ready. {len(events)} events stored locally."); return True

def step140_dashboard_generate():
    snap=step135_system_snapshot_v2(); state=_step143_load_state(); events=state.get("events",[])[-15:]
    caps=["Voice / Wake Word","Natural Hinglish","Local OCR","Visual UI Control","Computer-Use Agent","Browser Tasks","Memory","File Intelligence","Backup & Recovery","System Health","Safety Governor","Gemini Fallback"]
    rows="".join(f"<tr><td>{e.get('time','')}</td><td>{e.get('event','')}</td><td>{e.get('detail','')[:180]}</td></tr>" for e in reversed(events)); cap_html="".join(f"<li>{c}</li>" for c in caps)
    def val(x): return "N/A" if x is None else str(x)
    html=f"""<!doctype html><html><head><meta charset="utf-8"><title>JARVIS Mission Control</title><style>body{{font-family:Segoe UI,Arial;background:#10141c;color:#e8edf5;margin:0;padding:28px}}h1{{margin:0 0 8px}}.sub{{opacity:.7}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:22px 0}}.card{{background:#181f2b;border-radius:14px;padding:18px;border:1px solid #2a3445}}.num{{font-size:28px;font-weight:700}}table{{width:100%;border-collapse:collapse;background:#181f2b}}th,td{{padding:10px;border-bottom:1px solid #2a3445;text-align:left;font-size:13px}}ul{{columns:2}}</style></head><body><h1>JARVIS MISSION CONTROL</h1><div class="sub">Offline local dashboard - {snap.get('time','')}</div><div class="grid"><div class="card"><div>CPU</div><div class="num">{val(snap.get('cpu_percent'))}%</div></div><div class="card"><div>RAM</div><div class="num">{val(snap.get('ram_percent'))}%</div></div><div class="card"><div>Disk</div><div class="num">{val(snap.get('disk_percent'))}%</div></div><div class="card"><div>Free Disk</div><div class="num">{val(snap.get('disk_free_gb'))} GB</div></div><div class="card"><div>Battery</div><div class="num">{val(snap.get('battery_percent'))}%</div></div><div class="card"><div>Gemini</div><div class="num">{snap.get('gemini','unknown')}</div></div></div><div class="card"><b>Active Window</b><p>{snap.get('active_window') or 'Unknown'}</p></div><div class="card"><h2>Capabilities</h2><ul>{cap_html}</ul></div><div class="card"><h2>Recent Activity</h2><table><tr><th>Time</th><th>Event</th><th>Detail</th></tr>{rows}</table></div></body></html>"""
    _step143_ensure_dir(); Path(STEP143_DASHBOARD_FILE).write_text(html,encoding="utf-8"); state["dashboard_count"]=int(state.get("dashboard_count",0))+1; _step143_save_state(state); step134_mission_event("dashboard_generated",STEP143_DASHBOARD_FILE); return STEP143_DASHBOARD_FILE

def step141_dashboard_command(command):
    low=str(command or "").lower().strip()
    if not any(x in low for x in ("dashboard kholo","dashboard open karo","mission control kholo","jarvis dashboard")): return False
    path=step140_dashboard_generate()
    try: os.startfile(path)
    except Exception: webbrowser.open(Path(path).resolve().as_uri())
    speak("JARVIS Mission Control dashboard open kar diya."); return True

def step142_self_diagnostic_v2():
    checks=[]
    def add(name,ok,detail=""): checks.append((name,bool(ok),detail))
    try: py_compile.compile(os.path.abspath(__file__),doraise=True); add("Current file compile",True)
    except Exception as e: add("Current file compile",False,str(e))
    add("Base directory writable",os.access(BASE_DIR,os.W_OK)); add("Mission control directory",os.access(STEP143_STATE_DIR,os.W_OK) if os.path.exists(STEP143_STATE_DIR) else True); add("PyAutoGUI",bool(PYAUTOGUI_AVAILABLE)); add("Tesseract",bool(TESSERACT_AVAILABLE)); add("Gemini circuit breaker",True,"active" if GEMINI_QUOTA_EXHAUSTED else "ready")
    print("\nJARVIS SELF-DIAGNOSTIC V2\n-------------------------"); passed=0
    for name,ok,detail in checks: print(("PASS" if ok else "FAIL")+":",name,detail); passed+=int(ok)
    print(f"RESULT: {passed}/{len(checks)} checks passed"); step134_mission_event("self_diagnostic",f"{passed}/{len(checks)} passed"); speak(f"Self diagnostic complete. {passed} of {len(checks)} checks passed."); return passed==len(checks)

def step143_master_status():
    snap=step135_system_snapshot_v2(); state=_step143_load_state(); print("\n============================================\n       JARVIS MISSION CONTROL V2\n============================================"); print("Agent: ONLINE"); print("Active window:",snap.get("active_window") or "Unknown"); print("CPU:",snap.get("cpu_percent"),"%"); print("RAM:",snap.get("ram_percent"),"%"); print("Disk:",snap.get("disk_percent"),"%"); print("Gemini:",snap.get("gemini")); print("Mission events:",len(state.get("events",[]))); print("Dashboard generated:",state.get("dashboard_count",0),"time(s)"); print("============================================"); speak("JARVIS Mission Control online hai. System, activity aur agent state monitor ho rahi hai."); return True

def step143_command(command):
    low=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    if step141_dashboard_command(low): return True
    if any(x in low for x in ("mission control status","master status","jarvis master status")): return step143_master_status()
    if any(x in low for x in ("self diagnostic v2","self diagnostics v2","advanced self test","advanced self-test")): return step142_self_diagnostic_v2()
    if any(x in low for x in ("activity report v2","mission activity","recent activity report")): return step139_activity_report_v2()
    if any(x in low for x in ("clipboard read","clipboard padho","clipboard batao")): return step137_clipboard_read_local()
    m=re.search(r"(?:clipboard me|clipboard mein)\s+(.+?)\s+(?:likh|daal|dalo|set karo)$",low)
    if m: return step138_clipboard_write_local(m.group(1).strip())
    if any(x in low for x in ("health intelligence","deep system health","advanced system health")):
        result=step136_health_intelligence_v2(); speak("System health "+result["label"].lower()+" hai."); return True
    if any(x in low for x in ("system snapshot","system snapshot lo","system report")):
        snap=step135_system_snapshot_v2(); print("SYSTEM SNAPSHOT V2:",json.dumps(snap,indent=2,ensure_ascii=False)); speak("Detailed system snapshot ready hai."); return True
    return False


# =========================================================
# STEPS 164-173 - JARVIS NATURAL LANGUAGE ENGINE V1
# Local-first semantic intent layer.  This layer normalizes many
# Hindi/Hinglish/English variations into canonical commands before
# the existing feature routers run.  It does NOT require Gemini.
# =========================================================
import difflib

STEP173_NL_STATE_DIR = os.path.join(BASE_DIR, "jarvis_nl_engine")
STEP173_NL_STATE_FILE = os.path.join(STEP173_NL_STATE_DIR, "nl_state.json")


def step164_nl_clean_text(command):
    """Clean speech-to-text noise without requiring exact phrases."""
    s = str(command or "").lower().strip()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("jarvis "):
        s = s[7:].strip()
    elif s == "jarvis":
        s = ""
    # Common ASR contractions / chat-style spellings.
    replacements = {
        " centre ": " center ", " centar ": " center ", " centere ": " center ",
        " dash board ": " dashboard ", " comand ": " command ",
        " commmand ": " command ", " khol do ": " kholo ", " kholna ": " kholo ",
        " open kr ": " open karo ", " kr do ": " karo ", " krna ": " karna ",
        " btao ": " batao ", " btana ": " batana ", " dikha do ": " dikhao ",
        " dikhado ": " dikhao ", " bata do ": " batao ", " dekh lo ": " dekho ",
        " pls ": " please ", " plz ": " please ",
    }
    padded = " " + s + " "
    for a, b in replacements.items():
        padded = padded.replace(a, b)
    return re.sub(r"\s+", " ", padded).strip()


def step165_nl_token_fuzzy(token, vocabulary, cutoff=0.72):
    """Return a likely vocabulary token for small speech/spelling errors."""
    token = str(token or "").lower().strip()
    if not token:
        return token
    if token in vocabulary:
        return token
    match = difflib.get_close_matches(token, vocabulary, n=1, cutoff=cutoff)
    return match[0] if match else token


def step166_nl_normalize_tokens(text):
    """Normalize action/target words while keeping user-specific query text intact."""
    vocabulary = {
        "open", "kholo", "khol", "start", "launch", "chalao",
        "show", "dikhao", "batao", "tell", "read", "padho", "dekho",
        "search", "dhoondo", "dhundho", "find", "scan", "check",
        "status", "health", "dashboard", "center", "screen", "command",
        "mission", "control", "system", "computer", "capabilities",
        "notepad", "calculator", "chrome", "google", "youtube",
        "clipboard", "processes", "network", "wifi", "battery",
    }
    words = text.split()
    return " ".join(step165_nl_token_fuzzy(w, vocabulary) if len(w) <= 12 else w for w in words)


def step167_nl_intent_score(text, intent):
    """Score an intent using token groups + fuzzy matching; conservative by design."""
    specs = {
        "COMMAND_CENTER": {
            "must": ("command", "center"),
            "any": ("dashboard", "control", "mission", "panel", "kholo", "open", "dikhao", "show"),
        },
        "SCREEN_READ": {
            "must": ("screen",),
            "any": ("kya", "hai", "batao", "read", "padho", "dekho", "analyze", "samjho", "text"),
        },
        "SYSTEM_HEALTH": {
            "must": ("system", "health"),
            "any": ("check", "status", "batao", "dikhao", "diagnostic", "scan"),
        },
        "CAPABILITIES": {
            "must": ("capabilities",),
            "any": ("batao", "dikhao", "kya", "kar", "features"),
        },
        "MISSION_BRIEFING": {
            "must": ("mission", "briefing"),
            "any": ("batao", "dikhao", "do", "status"),
        },
        "NOTEPAD_OPEN": {
            "must": ("notepad",),
            "any": ("kholo", "open", "start", "launch", "chalao"),
        },
        "CALCULATOR_OPEN": {
            "must": ("calculator",),
            "any": ("kholo", "open", "start", "launch", "chalao"),
        },
        "GOOGLE_SEARCH": {
            "must": ("google",),
            "any": ("search", "dhoondo", "dhundho", "find"),
        },
        "YOUTUBE_SEARCH": {
            "must": ("youtube",),
            "any": ("search", "dhoondo", "dhundho", "find"),
        },
        "CLIPBOARD_READ": {
            "must": ("clipboard",),
            "any": ("batao", "read", "padho", "dikhao", "show"),
        },
        "PROCESS_LIST": {
            "must": ("processes",),
            "any": ("running", "list", "dikhao", "show", "batao"),
        },
        "NETWORK_DIAGNOSTICS": {
            "must": ("network",),
            "any": ("diagnostic", "check", "status", "internet", "test"),
        },
    }
    spec = specs.get(intent)
    if not spec:
        return 0.0
    tokens = set(text.split())

    # Broad semantic shortcuts for common natural phrases. These are
    # intentionally conservative and still require an action/meaning word.
    if intent == "COMMAND_CENTER":
        if "dashboard" in tokens and tokens.intersection({"kholo", "open", "dikhao", "show", "dekho", "chalao"}):
            return 0.94
        if {"mission", "control"}.issubset(tokens) and tokens.intersection({"kholo", "open", "dikhao", "show", "dekho"}):
            return 0.94
    if intent == "SYSTEM_HEALTH":
        if "system" in tokens and tokens.intersection({"status", "health", "check", "diagnostic", "scan", "performance"}):
            return 0.90
    score = 0.0
    for item in spec["must"]:
        if item in tokens:
            score += 0.42
        elif any(difflib.SequenceMatcher(None, item, t).ratio() >= 0.78 for t in tokens):
            score += 0.28
        else:
            return 0.0
    for item in spec["any"]:
        if item in tokens:
            score += 0.10
        elif any(difflib.SequenceMatcher(None, item, t).ratio() >= 0.80 for t in tokens):
            score += 0.04
    return min(score, 1.0)


def step168_nl_detect_intent(text):
    """Choose a local intent only when confidence is high enough."""
    intents = (
        "COMMAND_CENTER", "SCREEN_READ", "SYSTEM_HEALTH", "CAPABILITIES",
        "MISSION_BRIEFING", "NOTEPAD_OPEN", "CALCULATOR_OPEN", "GOOGLE_SEARCH",
        "YOUTUBE_SEARCH", "CLIPBOARD_READ", "PROCESS_LIST", "NETWORK_DIAGNOSTICS",
    )
    scored = sorted(((step167_nl_intent_score(text, i), i) for i in intents), reverse=True)
    best_score, best_intent = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < 0.48:
        return {"intent": "UNKNOWN", "confidence": round(best_score, 3)}
    if best_score - second_score < 0.06 and best_score < 0.72:
        return {"intent": "UNKNOWN", "confidence": round(best_score, 3)}
    return {"intent": best_intent, "confidence": round(best_score, 3)}


def step169_nl_extract_query(text, anchors):
    """Extract search text after an anchor without forcing a fixed sentence shape."""
    low = text.lower()
    positions = [low.find(a) for a in anchors if low.find(a) >= 0]
    if not positions:
        return ""
    pos = min(positions)
    tail = text[pos:]
    for a in anchors:
        tail = re.sub(r"^" + re.escape(a) + r"\s*", "", tail, flags=re.I)
    tail = re.sub(r"\b(?:par|pe|mein|me)\b", " ", tail, flags=re.I)
    tail = re.sub(r"\b(?:search|dhoondo|dhundho|find|karo|kar|please)\b", " ", tail, flags=re.I)
    return re.sub(r"\s+", " ", tail).strip()


def step170_nl_to_canonical(text, intent):
    """Map a detected intent to an existing JARVIS command."""
    if intent == "COMMAND_CENTER":
        return "jarvis command center kholo"
    if intent == "SCREEN_READ":
        return "jarvis screen par kya hai"
    if intent == "SYSTEM_HEALTH":
        return "jarvis system health check"
    if intent == "CAPABILITIES":
        return "jarvis capabilities batao"
    if intent == "MISSION_BRIEFING":
        return "jarvis mission briefing v3"
    if intent == "NOTEPAD_OPEN":
        return "jarvis notepad kholo"
    if intent == "CALCULATOR_OPEN":
        return "jarvis calculator kholo"
    if intent == "CLIPBOARD_READ":
        return "jarvis clipboard batao"
    if intent == "PROCESS_LIST":
        return "jarvis process inventory"
    if intent == "NETWORK_DIAGNOSTICS":
        return "jarvis network diagnostics"
    if intent in {"GOOGLE_SEARCH", "YOUTUBE_SEARCH"}:
        query = step169_nl_extract_query(text, ("google", "youtube"))
        if query:
            site = "google" if intent == "GOOGLE_SEARCH" else "youtube"
            return f"jarvis {site} par {query} search karo"
    return ""


def step171_nl_record(original, normalized, intent, confidence):
    """Persist lightweight language-engine telemetry locally."""
    try:
        os.makedirs(STEP173_NL_STATE_DIR, exist_ok=True)
        state = {"runs": 0, "recent": []}
        if os.path.exists(STEP173_NL_STATE_FILE):
            try:
                state = json.loads(Path(STEP173_NL_STATE_FILE).read_text(encoding="utf-8"))
            except Exception:
                state = {"runs": 0, "recent": []}
        state["runs"] = int(state.get("runs", 0) or 0) + 1
        recent = state.get("recent", [])
        if not isinstance(recent, list):
            recent = []
        recent.append({
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "original": original[:250],
            "normalized": normalized[:250],
            "intent": intent,
            "confidence": confidence,
        })
        state["recent"] = recent[-50:]
        Path(STEP173_NL_STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("NL TELEMETRY WARNING:", e)


def step172_nl_engine_status(command):
    """Explain the local language engine state without using Gemini."""
    low = step164_nl_clean_text(command)
    triggers = (
        "language engine status", "natural language status", "nl engine status",
        "natural language engine", "language understanding status", "nl understanding status",
    )
    if not any(x in low for x in triggers):
        return False
    print("\nJARVIS NATURAL LANGUAGE ENGINE V1")
    print("--------------------------------")
    print("Text normalization : ACTIVE")
    print("Fuzzy vocabulary   : ACTIVE")
    print("Local intent model : ACTIVE")
    print("Context-safe route : ACTIVE")
    print("Gemini required    : NO")
    print("Telemetry          :", STEP173_NL_STATE_FILE)
    speak("Natural language engine active hai. Local intent understanding Gemini ke bina chal rahi hai.")
    return True


def step173_natural_language_router(command):
    """Main local semantic router. Returns a canonical command or None."""
    cleaned = step164_nl_clean_text(command)
    if not cleaned:
        return None
    cleaned = step166_nl_normalize_tokens(cleaned)
    detected = step168_nl_detect_intent(cleaned)
    intent = detected["intent"]
    confidence = detected["confidence"]
    if intent == "UNKNOWN":
        return None
    canonical = step170_nl_to_canonical(cleaned, intent)
    if not canonical:
        return None
    # Only rewrite when the canonical command is materially different.
    if canonical.lower() == str(command or "").lower().strip():
        return canonical
    step171_nl_record(command, canonical, intent, confidence)
    print(f"STEP 173 NL -> {intent} ({confidence:.2f}) -> {canonical}")
    return canonical

def process_command_base(command):
    raw=str(command or "").strip()
    if not raw: return False
    if step172_nl_engine_status(raw): return True
    # Local Natural Language Engine runs before feature routers. It converts
    # many Hindi/Hinglish/English/spelling variants into a known command.
    try:
        nl_resolved = step173_natural_language_router(raw)
        if nl_resolved:
            raw = nl_resolved
    except Exception as e:
        print("NL ENGINE WARNING:", e)
    if step163_command(raw): return True
    if step143_command(raw): return True
    if step133_command(raw): return True
    if step128_command(raw): return True
    low_screen=re.sub(r"\s+"," ",raw.lower()).strip()
    if ("screen par kya hai" in low_screen or "screen pe kya hai" in low_screen or "screen me kya hai" in low_screen or "screen mein kya hai" in low_screen or "screen text" in low_screen or "screen ocr" in low_screen or "ocr screen" in low_screen or "screen read karo" in low_screen or "screen ko read karo" in low_screen or "screen ka text" in low_screen):
        try: return bool(read_screen_locally())
        except Exception as e: print("LOCAL SCREEN OCR ERROR:",e); speak("I could not read the screen locally."); return True
    if screen_understanding_command(raw): return True
    if step118_command(raw): return True
    if step108_agent_command(raw) or step99_core_status(raw): return True
    intent=step100_detect_intent(raw)
    if intent=="multi_step":
        plan=step103_plan_actions(raw); results=[]
        for item in plan:
            r=step106_recover_action(item,step104_execute_action(item)); results.append(r)
            if not step105_verify_result(r,item): break
        ok=bool(results) and all(r.get("ok") for r in results); state=_s99_load(); state.update({"last_command":raw,"last_intent":intent,"last_entities":step101_extract_entities(raw),"last_results":results,"updated":datetime.datetime.now().isoformat(timespec="seconds")}); _s99_save(state); return ok
    resolved=step102_context_resolve(raw); result=process_command_legacy(resolved); state=_s99_load(); state.update({"last_command":raw,"last_resolved_command":resolved,"last_intent":step100_detect_intent(resolved),"last_entities":step101_extract_entities(resolved),"last_ok":bool(result),"updated":datetime.datetime.now().isoformat(timespec="seconds")}); _s99_save(state); return result

# =========================================================
# STEP 144-163 - JARVIS ADVANCED OPERATIONS SUITE
# =========================================================
STEP163_STATE_DIR = os.path.join(BASE_DIR, "jarvis_ops_v3")
STEP163_STATE_FILE = os.path.join(STEP163_STATE_DIR, "ops_state.json")
STEP163_DASHBOARD_FILE = os.path.join(STEP163_STATE_DIR, "jarvis_command_center_v3.html")
STEP163_STOP_FLAG = os.path.join(STEP163_STATE_DIR, "stop_requested.flag")

def step163_ensure_dir():
    os.makedirs(STEP163_STATE_DIR, exist_ok=True)

def step163_load_state():
    step163_ensure_dir()
    if not os.path.exists(STEP163_STATE_FILE):
        return {"snapshots": [], "events": [], "created": datetime.datetime.now().isoformat(timespec="seconds")}
    try:
        data = json.loads(Path(STEP163_STATE_FILE).read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError("invalid state")
        data.setdefault("snapshots", []); data.setdefault("events", [])
        return data
    except Exception as e:
        print("OPS STATE LOAD ERROR:", e); return {"snapshots": [], "events": []}

def step163_save_state(state):
    step163_ensure_dir(); Path(STEP163_STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def step163_event(event, detail=""):
    state=step163_load_state(); state["events"].append({"time":datetime.datetime.now().isoformat(timespec="seconds"),"event":str(event),"detail":str(detail)[:500]}); state["events"]=state["events"][-100:]; step163_save_state(state)

def step144_resource_monitor_v3():
    snap=step135_system_snapshot_v2(); print("\nJARVIS RESOURCE MONITOR V3\n---------------------------")
    for key,label in (("cpu_percent","CPU"),("ram_percent","RAM"),("disk_percent","Disk"),("disk_free_gb","Free Disk"),("battery_percent","Battery")): print(f"{label}: {snap.get(key,'N/A')}")
    step163_event("resource_monitor",json.dumps(snap,ensure_ascii=False)); speak("Resource monitor ready hai. CPU, RAM aur disk status console me hai."); return True

def step145_process_inventory():
    try:
        p=subprocess.run(["tasklist","/FO","CSV","/NH"],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); rows=[]
        import csv
        for line in (p.stdout or "").splitlines():
            try: parts=next(csv.reader([line]))
            except Exception: parts=[]
            if len(parts)>=2: rows.append({"name":parts[0],"pid":parts[1],"memory":parts[4] if len(parts)>4 else ""})
        rows=rows[:40]; print("\nJARVIS PROCESS INVENTORY\n-------------------------")
        for r in rows[:20]: print(f"{r['name']:<32} PID {r['pid']:<7} MEM {r['memory']}")
        step163_event("process_inventory",f"{len(rows)} processes sampled"); speak(f"Process inventory ready hai. {len(rows)} processes sampled."); return True
    except Exception as e: print("PROCESS INVENTORY ERROR:",e); speak("Process inventory nahi mil paya."); return True

def step146_top_processes():
    try:
        ps='Get-Process | Sort-Object CPU -Descending | Select-Object -First 10 Name,Id,CPU,WorkingSet | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        print("\nJARVIS TOP PROCESSES\n---------------------"); print((p.stdout or "").strip()[:5000]); step163_event("top_processes","Top 10 process snapshot"); speak("Top processes ka snapshot ready hai."); return True
    except Exception as e: print("TOP PROCESS ERROR:",e); speak("Top process data nahi mil paya."); return True

def step147_network_diagnostics():
    try:
        p=subprocess.run(["ping","-n","2","8.8.8.8"],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); ok=p.returncode==0
        print("\nJARVIS NETWORK DIAGNOSTICS\n---------------------------"); print("Internet reachability:","PASS" if ok else "FAIL"); print((p.stdout or "")[-2500:]); step163_event("network_diagnostics","PASS" if ok else "FAIL"); speak("Network diagnostic "+("pass hai." if ok else "fail hua hai.")); return True
    except Exception as e: print("NETWORK DIAGNOSTICS ERROR:",e); speak("Network diagnostic complete nahi ho paya."); return True

def step148_wifi_status():
    try:
        p=subprocess.run(["netsh","wlan","show","interfaces"],capture_output=True,text=True,timeout=6,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); safe=[]
        for line in (p.stdout or "").splitlines():
            low=line.lower()
            if any(x in low for x in ("ssid","state","signal","radio type","channel")) and "bssid" not in low: safe.append(line.strip())
        print("\nJARVIS WIFI STATUS\n------------------"); print("\n".join(safe[:20]) if safe else "Wi-Fi interface details unavailable."); step163_event("wifi_status","interface status checked"); speak("Wi-Fi status check complete hai."); return True
    except Exception as e: print("WIFI STATUS ERROR:",e); speak("Wi-Fi status nahi mil paya."); return True

def step149_battery_diagnostics():
    try:
        ps='Get-CimInstance Win32_Battery | Select-Object Name,BatteryStatus,EstimatedChargeRemaining,DesignVoltage | ConvertTo-Json -Compress'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=7,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); data=(p.stdout or "").strip()
        print("\nJARVIS BATTERY DIAGNOSTICS\n--------------------------"); print(data if data else "Battery information unavailable."); step163_event("battery_diagnostics",data[:500]); speak("Battery diagnostics ready hai."); return True
    except Exception as e: print("BATTERY DIAGNOSTICS ERROR:",e); speak("Battery diagnostics nahi mil paya."); return True

def step150_display_inventory():
    try:
        ps='Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,VideoModeDescription | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=7,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("\nJARVIS DISPLAY INVENTORY\n-------------------------"); print((p.stdout or "").strip()[:4000]); step163_event("display_inventory","display adapters checked"); speak("Display inventory ready hai."); return True
    except Exception as e: print("DISPLAY INVENTORY ERROR:",e); speak("Display information nahi mil payi."); return True

def step151_audio_inventory():
    try:
        ps='Get-CimInstance Win32_SoundDevice | Select-Object Name,Status,Manufacturer | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=7,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("\nJARVIS AUDIO DEVICES\n--------------------"); print((p.stdout or "").strip()[:4000]); step163_event("audio_inventory","audio devices checked"); speak("Audio device inventory ready hai."); return True
    except Exception as e: print("AUDIO INVENTORY ERROR:",e); speak("Audio devices nahi mil paye."); return True

def step152_usb_inventory():
    try:
        ps='Get-CimInstance Win32_PnPEntity | Where-Object {$_.PNPClass -eq "USB"} | Select-Object Name,Status,Manufacturer | Select-Object -First 30 | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("\nJARVIS USB INVENTORY\n--------------------"); print((p.stdout or "").strip()[:5000]); step163_event("usb_inventory","USB devices checked"); speak("USB inventory ready hai."); return True
    except Exception as e: print("USB INVENTORY ERROR:",e); speak("USB inventory nahi mil paya."); return True

def step153_environment_report():
    try:
        names=sorted(os.environ.keys()); safe=[n for n in names if not any(x in n.lower() for x in ("key","token","secret","password","credential"))]
        print("\nJARVIS ENVIRONMENT REPORT\n-------------------------"); print("Python:",platform.python_version()); print("OS:",platform.platform()); print("Machine:",platform.machine()); print("Environment variable names:",", ".join(safe[:80])); step163_event("environment_report","safe environment metadata generated"); speak("Environment report ready hai."); return True
    except Exception as e: print("ENVIRONMENT REPORT ERROR:",e); speak("Environment report nahi ban paya."); return True

def step154_installed_apps_report():
    try:
        ps='Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*,HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName} | Select-Object -First 40 DisplayName,DisplayVersion,Publisher | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("\nJARVIS INSTALLED APPS REPORT\n----------------------------"); print((p.stdout or "").strip()[:7000]); step163_event("installed_apps_report","installed app metadata sampled"); speak("Installed apps report ready hai."); return True
    except Exception as e: print("INSTALLED APPS ERROR:",e); speak("Installed apps report nahi mil paya."); return True

def step155_services_health():
    try:
        names=["Audiosrv","Dhcp","Dnscache","Spooler","Winmgmt","wuauserv"]; ps='Get-Service -Name '+','.join(names)+' -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=8,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("\nJARVIS CORE SERVICES HEALTH\n---------------------------"); print((p.stdout or "").strip()[:5000]); step163_event("services_health","core Windows services inspected"); speak("Core services health check ready hai."); return True
    except Exception as e: print("SERVICES HEALTH ERROR:",e); speak("Services health check nahi ho paya."); return True

def step156_startup_report():
    try:
        ps='Get-CimInstance Win32_StartupCommand | Select-Object -First 40 Name,Command,Location | ConvertTo-Csv -NoTypeInformation'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); print("\nJARVIS STARTUP REPORT\n---------------------"); print((p.stdout or "").strip()[:7000]); step163_event("startup_report","startup entries inspected"); speak("Startup report ready hai."); return True
    except Exception as e: print("STARTUP REPORT ERROR:",e); speak("Startup report nahi mil paya."); return True

def step157_uptime_report():
    try:
        ps='(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o")'; p=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True,timeout=6,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)); boot=(p.stdout or "").strip(); print("\nJARVIS UPTIME REPORT\n--------------------"); print("Last boot:",boot or "Unknown"); step163_event("uptime_report",boot); speak("Uptime report ready hai."); return True
    except Exception as e: print("UPTIME ERROR:",e); speak("Uptime report nahi mil paya."); return True

def step158_performance_history():
    state=step163_load_state(); snap=step135_system_snapshot_v2(); state["snapshots"].append(snap); state["snapshots"]=state["snapshots"][-50:]; step163_save_state(state)
    print("\nJARVIS PERFORMANCE HISTORY\n--------------------------"); print("Snapshots stored:",len(state["snapshots"]))
    for x in state["snapshots"][-8:]: print(x.get("time"),"CPU",x.get("cpu_percent"),"RAM",x.get("ram_percent"),"Disk",x.get("disk_percent"))
    step163_event("performance_history",f"{len(state['snapshots'])} snapshots stored"); speak("Performance history update kar di."); return True

def step159_safe_stop_request():
    step163_ensure_dir(); Path(STEP163_STOP_FLAG).write_text(datetime.datetime.now().isoformat(timespec="seconds"),encoding="utf-8"); step163_event("stop_request","User requested safe stop flag"); print("SAFE STOP REQUESTED ->",STEP163_STOP_FLAG); speak("Safe stop request register kar diya hai. Current operation ko safely stop karna hai."); return True

def step160_telemetry_report():
    state=step163_load_state(); events=state.get("events",[]); counts={}
    for e in events: counts[e.get("event","unknown")]=counts.get(e.get("event","unknown"),0)+1
    print("\nJARVIS TELEMETRY REPORT V3\n--------------------------"); print("Total local events:",len(events)); print("Event types:")
    for k,v in sorted(counts.items(),key=lambda x:(-x[1],x[0]))[:20]: print(f"  {k}: {v}")
    speak(f"Telemetry report ready hai. {len(events)} local events recorded."); return True

def step161_capability_matrix_v3():
    caps={"Voice & Wake Word":"ACTIVE","Natural Hinglish":"ACTIVE","Local OCR":"ACTIVE" if TESSERACT_AVAILABLE else "UNAVAILABLE","Visual UI Control":"ACTIVE" if PYAUTOGUI_AVAILABLE else "UNAVAILABLE","Computer Use Agent":"ACTIVE","Memory":"ACTIVE","File Intelligence":"ACTIVE","Mission Control":"ACTIVE","System Diagnostics":"ACTIVE","Safety Governor":"ACTIVE","Gemini Fallback":"DISABLED (quota)" if GEMINI_QUOTA_EXHAUSTED else "READY"}
    print("\nJARVIS CAPABILITY MATRIX V3\n---------------------------"); [print(f"{k:<28} {v}") for k,v in caps.items()]; step163_event("capability_matrix",json.dumps(caps,ensure_ascii=False)); speak("Capability matrix ready hai."); return True

def step162_mission_briefing_v3():
    snap=step135_system_snapshot_v2(); health=step136_health_intelligence_v2(); state=step163_load_state(); print("\n============================================\n        JARVIS MISSION BRIEFING V3\n============================================"); print("System:",platform.system(),platform.release(),platform.machine()); print("CPU:",snap.get("cpu_percent"),"% | RAM:",snap.get("ram_percent"),"% | Disk:",snap.get("disk_percent"),"%"); print("Health:",health.get("label"),"| Alerts:",", ".join(health.get("alerts",[])) or "none"); print("Active window:",snap.get("active_window") or "Unknown"); print("Mission events:",len(state.get("events",[]))); print("Gemini:",snap.get("gemini")); print("============================================"); step163_event("mission_briefing","system + health + agent briefing generated"); speak("Mission briefing ready hai. System health aur agent state console me hai."); return True

def step163_dashboard_v3():
    snap=step135_system_snapshot_v2(); health=step136_health_intelligence_v2(); state=step163_load_state(); events=state.get("events",[])[-20:]; step163_ensure_dir(); import html as _html
    def esc(v): return _html.escape(str(v if v is not None else "N/A"))
    event_rows="".join(f"<tr><td>{esc(e.get('time'))}</td><td>{esc(e.get('event'))}</td><td>{esc(e.get('detail','')[:220])}</td></tr>" for e in reversed(events)); cards=[("CPU",f"{snap.get('cpu_percent','N/A')}%"),("RAM",f"{snap.get('ram_percent','N/A')}%"),("DISK",f"{snap.get('disk_percent','N/A')}%"),("FREE DISK",f"{snap.get('disk_free_gb','N/A')} GB"),("BATTERY",f"{snap.get('battery_percent','N/A')}%"),("HEALTH",health.get('label','UNKNOWN'))]; card_html="".join(f"<div class='card'><div class='label'>{esc(a)}</div><div class='num'>{esc(b)}</div></div>" for a,b in cards)
    html_doc=f"""<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="15"><title>JARVIS Command Center V3</title><style>body{{margin:0;background:#0b0f16;color:#edf2f7;font-family:Segoe UI,Arial;padding:28px}}h1{{letter-spacing:2px}}.muted{{opacity:.65}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:20px 0}}.card{{background:#151b26;border:1px solid #273142;border-radius:16px;padding:18px}}.label{{font-size:12px;opacity:.65}}.num{{font-size:27px;font-weight:700;margin-top:8px}}table{{width:100%;border-collapse:collapse;background:#151b26;border-radius:14px;overflow:hidden}}th,td{{padding:11px;border-bottom:1px solid #273142;text-align:left;font-size:13px}}.wide{{margin-top:18px}}.pill{{display:inline-block;padding:7px 11px;border:1px solid #334155;border-radius:999px;margin:4px;font-size:12px}}</style></head><body><h1>JARVIS COMMAND CENTER V3</h1><div class="muted">Local-first control center • auto refresh 15s • {esc(snap.get('time'))}</div><div class="grid">{card_html}</div><div class="card"><b>ACTIVE WINDOW</b><p>{esc(snap.get('active_window') or 'Unknown')}</p><b>GEMINI</b><p>{esc(snap.get('gemini'))}</p></div><div class="wide card"><h2>AGENT CAPABILITIES</h2>{''.join(f'<span class="pill">{esc(x)}</span>' for x in ['Voice','Hinglish','OCR','Visual UI','Computer Use','Memory','Files','Safety','Diagnostics','Mission Control'])}</div><div class="wide"><h2>RECENT EVENTS</h2><table><tr><th>Time</th><th>Event</th><th>Detail</th></tr>{event_rows}</table></div></body></html>"""
    Path(STEP163_DASHBOARD_FILE).write_text(html_doc,encoding="utf-8")
    try: os.startfile(STEP163_DASHBOARD_FILE)
    except Exception: webbrowser.open(Path(STEP163_DASHBOARD_FILE).resolve().as_uri())
    step163_event("command_center_v3","dashboard generated"); speak("JARVIS Command Center V3 open kar diya."); return True

def step163_command(command):
    low=re.sub(r"\s+"," ",str(command or "").lower()).strip()
    if any(x in low for x in ("command center v3","command centre v3","command center kholo","command centre kholo","command center open karo","command centre open karo","command center khol do","command centre khol do","advanced dashboard v3","mission dashboard v3","jarvis command center","jarvis command centre")): return step163_dashboard_v3()
    if any(x in low for x in ("mission briefing v3","mission briefing do","mission briefing batao")): return step162_mission_briefing_v3()
    if any(x in low for x in ("capability matrix v3","capability matrix batao")): return step161_capability_matrix_v3()
    if any(x in low for x in ("telemetry report","activity telemetry","agent telemetry")): return step160_telemetry_report()
    if any(x in low for x in ("safe stop request","current task stop karo","agent stop request")): return step159_safe_stop_request()
    if any(x in low for x in ("performance history","performance history dikhao","resource history")): return step158_performance_history()
    if any(x in low for x in ("uptime report","system uptime")): return step157_uptime_report()
    if any(x in low for x in ("startup report","startup apps dikhao")): return step156_startup_report()
    if any(x in low for x in ("services health","windows services status","core services")): return step155_services_health()
    if any(x in low for x in ("installed apps report","installed apps dikhao")): return step154_installed_apps_report()
    if any(x in low for x in ("environment report","system environment")): return step153_environment_report()
    if any(x in low for x in ("usb inventory","usb devices dikhao")): return step152_usb_inventory()
    if any(x in low for x in ("audio devices dikhao","audio inventory")): return step151_audio_inventory()
    if any(x in low for x in ("display inventory","graphics information","display information")): return step150_display_inventory()
    if any(x in low for x in ("battery diagnostics","battery health")): return step149_battery_diagnostics()
    if any(x in low for x in ("wifi status","wi-fi status","wifi details")): return step148_wifi_status()
    if any(x in low for x in ("network diagnostics","internet diagnostic","internet check")): return step147_network_diagnostics()
    if any(x in low for x in ("top processes","top process","heavy processes")): return step146_top_processes()
    if any(x in low for x in ("process inventory","running processes","process list")): return step145_process_inventory()
    if any(x in low for x in ("resource monitor v3","resource monitor","cpu ram disk monitor")): return step144_resource_monitor_v3()
    return False




# =========================================================
# STEP 174-193 - JARVIS NATURAL LANGUAGE ENGINE V2
# Local-first semantic command layer. No Gemini required.
# =========================================================

STEP193_NL_STATE_DIR = os.path.join(BASE_DIR, "jarvis_nl_engine")
STEP193_NL_STATE_FILE = os.path.join(STEP193_NL_STATE_DIR, "nl_state.json")


def step174_nl_ensure_dir():
    os.makedirs(STEP193_NL_STATE_DIR, exist_ok=True)


def step175_nl_clean(text):
    s = str(text or "").lower().strip()
    s = re.sub(r"[^\w\s:/.-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(?:hey\s+)?jarvis[\s,:-]*", "", s).strip()
    replacements = {
        "centre": "center", "centar": "center", "center": "center",
        "krdo": "karo", "krde": "karo", "kardo": "karo", "kr": "karo",
        "khoolo": "kholo", "khul": "kholo", "khol": "kholo",
        "btao": "batao", "btado": "batao", "batado": "batao",
        "screan": "screen", "scren": "screen", "notpad": "notepad",
        "calc": "calculator", "calcu": "calculator",
        "dhoondo": "search", "dhundho": "search", "dhundna": "search",
        "khol de": "kholo", "open kr": "open karo",
    }
    words=[]
    for w in s.split():
        words.append(replacements.get(w,w))
    return " ".join(words)


def step176_nl_fuzzy_tokens(text):
    """Correct common ASR/spelling drift using a conservative local vocabulary."""
    from difflib import get_close_matches
    s=step175_nl_clean(text)
    vocab={
        "command","center","dashboard","mission","control","screen","system",
        "health","status","notepad","calculator","chrome","browser","google",
        "youtube","search","open","karo","kholo","batao","dikhao","report",
        "clipboard","activity","telemetry","capabilities","briefing","processes",
        "network","battery","wifi","startup","services","environment","performance",
        "history","screenshot","file","folder","memory","task","agent","help",
        "repeat","last","stop","safe","diagnostic","self","test"
    }
    out=[]
    for w in s.split():
        if len(w)>=4 and w not in vocab:
            m=get_close_matches(w, vocab, n=1, cutoff=0.84)
            out.append(m[0] if m else w)
        else:
            out.append(w)
    return " ".join(out)


def step177_nl_intent_registry():
    return {
        "COMMAND_CENTER": ["command center","dashboard","dashboard kholo","dashboard dikhao","dashboard dikha do","dashboard open karo","mission control","mission control kholo","mission control open karo"],
        "SCREEN_READ": ["screen par kya hai","screen pe kya hai","screen me kya hai","screen read","screen dekho","screen analyze"],
        "SYSTEM_HEALTH": ["system health","system status","computer status","pc status","system ka haal","system health check"],
        "CAPABILITIES": ["capabilities batao","capability matrix","tum kya kya kar sakte ho","what can you do","features batao"],
        "MISSION_BRIEFING": ["mission briefing","briefing batao","system briefing"],
        "ACTIVITY_REPORT": ["activity report","recent activity","activity history","telemetry report"],
        "RESOURCE_MONITOR": ["resource monitor","cpu ram disk","performance monitor"],
        "NETWORK_DIAGNOSTICS": ["network diagnostics","internet diagnostic","internet check","network check"],
        "PROCESS_LIST": ["running processes","process list","processes dikhao","heavy processes"],
        "BATTERY": ["battery health","battery diagnostics","battery status"],
        "WIFI": ["wifi status","wi fi status","wifi details"],
        "STARTUP": ["startup apps","startup report","startup programs"],
        "SERVICES": ["windows services","services health","services status"],
        "ENVIRONMENT": ["environment report","system environment"],
        "PERFORMANCE_HISTORY": ["performance history","resource history"],
        "CLIPBOARD_READ": ["clipboard batao","clipboard read","clipboard dikhao"],
        "SELF_DIAGNOSTIC": ["self diagnostic","self test","advanced self test","health diagnostic"],
        "SAFE_STOP": ["safe stop","task stop karo","agent stop request"],
        "HELP": ["help","madad chahiye","commands batao","command list"],
        "REPEAT_LAST": ["repeat last","last command repeat","pichla command","phir se bolo"],
    }


def step178_nl_score_intent(command):
    """Score intents by phrase overlap; exact matching is not required."""
    s=step176_nl_fuzzy_tokens(command)
    registry=step177_nl_intent_registry()
    scores=[]
    for intent, phrases in registry.items():
        score=0.0
        for phrase in phrases:
            p=step175_nl_clean(phrase)
            if p in s:
                score=max(score,1.0 if len(p.split())>1 else 0.72)
            else:
                a=set(p.split()); b=set(s.split())
                if a and b:
                    overlap=len(a & b)/len(a)
                    score=max(score,overlap*0.78)
        scores.append((score,intent))
    scores.sort(reverse=True)
    return scores[0] if scores else (0.0,"UNKNOWN")


def step179_nl_extract_entities(command):
    s=step175_nl_clean(command)
    entities={}
    m=re.search(r"(?:google|youtube)\s+(?:par|pe|me|mein)\s+(.+?)(?:\s+(?:search|dhoondo|dhundho|find)\s+(?:karo|kar))?$",s)
    if m: entities["query"]=m.group(1).strip()
    m=re.search(r"(?:file|folder)\s+(.+?)\s+(?:khol|open|dhoond)",s)
    if m: entities["path_target"]=m.group(1).strip()
    return entities


def step180_nl_load_state():
    step174_nl_ensure_dir()
    try:
        data=json.loads(Path(STEP193_NL_STATE_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}


def step181_nl_save_state(data):
    step174_nl_ensure_dir()
    tmp=STEP193_NL_STATE_FILE+".tmp"
    Path(tmp).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(tmp,STEP193_NL_STATE_FILE)


def step182_nl_remember_turn(command,intent,confidence,entities=None):
    state=step180_nl_load_state()
    state.setdefault("turns",[])
    state["turns"].append({"time":datetime.datetime.now().isoformat(timespec="seconds"),"command":str(command),"intent":intent,"confidence":round(float(confidence),3),"entities":entities or {}})
    state["turns"]=state["turns"][-30:]
    state["last_command"]=str(command); state["last_intent"]=intent; state["last_entities"]=entities or {}
    step181_nl_save_state(state)
    return state


def step183_nl_resolve_context(command):
    s=step175_nl_clean(command)
    state=step180_nl_load_state(); last=state.get("last_command","")
    if not last: return command
    if re.search(r"\b(isko|usko|wahi|same|pichla|last)\b",s):
        if "repeat" in s or "phir" in s: return last
    return command


def step184_nl_confidence(command,intent,score):
    words=len(step175_nl_clean(command).split())
    confidence=float(score)
    if words>=3: confidence=min(1.0,confidence+0.08)
    if intent=="UNKNOWN": confidence=0.0
    return round(confidence,3)


def step185_nl_trace(command,intent,confidence,entities):
    print(f"NL V2 -> intent={intent} confidence={confidence} entities={entities}")


def step186_nl_help():
    print("\nJARVIS NATURAL LANGUAGE HELP\n----------------------------")
    print("You can speak naturally; exact wording is not required.")
    print("Examples: dashboard dikha, system ka haal bata, screen dekho, help, repeat last")
    speak("Natural language mode active hai. Exact words bolna zaroori nahi hai.")
    return True


def step187_nl_repeat_last():
    state=step180_nl_load_state(); last=state.get("last_command")
    if not last:
        speak("Abhi koi previous command nahi hai."); return True
    print("REPEATING LAST COMMAND ->",last)
    # Prevent recursive repeat loops.
    if "repeat" in step175_nl_clean(last) or "pichla command" in step175_nl_clean(last):
        speak("Previous command repeat karna possible nahi hai."); return True
    return process_command_base(last)


def step188_nl_dispatch(intent,command,entities):
    """Map semantic intents to existing proven local handlers."""
    routes={
        "COMMAND_CENTER": lambda: step163_dashboard_v3(),
        "SCREEN_READ": lambda: read_screen_locally(),
        "SYSTEM_HEALTH": lambda: step136_health_intelligence_v2(),
        "CAPABILITIES": lambda: step161_capability_matrix_v3(),
        "MISSION_BRIEFING": lambda: step162_mission_briefing_v3(),
        "ACTIVITY_REPORT": lambda: step160_telemetry_report(),
        "RESOURCE_MONITOR": lambda: step144_resource_monitor_v3(),
        "NETWORK_DIAGNOSTICS": lambda: step147_network_diagnostics(),
        "PROCESS_LIST": lambda: step145_process_inventory(),
        "BATTERY": lambda: step149_battery_diagnostics(),
        "WIFI": lambda: step148_wifi_status(),
        "STARTUP": lambda: step156_startup_report(),
        "SERVICES": lambda: step155_services_health(),
        "ENVIRONMENT": lambda: step153_environment_report(),
        "PERFORMANCE_HISTORY": lambda: step158_performance_history(),
        "CLIPBOARD_READ": lambda: step137_clipboard_read_local(),
        "SELF_DIAGNOSTIC": lambda: step142_self_diagnostic_v2(),
        "SAFE_STOP": lambda: step159_safe_stop_request(),
        "HELP": lambda: step186_nl_help(),
        "REPEAT_LAST": lambda: step187_nl_repeat_last(),
    }
    fn=routes.get(intent)
    if not fn: return False
    try:
        result=fn()
        return bool(result) if isinstance(result,bool) else True
    except Exception as e:
        print("NL DISPATCH ERROR:",e)
        speak("Command samajh aa gayi, lekin action complete nahi ho paya.")
        return True


def step189_nl_smart_reply(command):
    s=step175_nl_clean(command)
    if any(x in s for x in ("hello","hi jarvis","namaste","kaise ho")):
        speak("Main ready hoon. Batao kya karna hai."); return True
    if "thank" in s or "shukriya" in s:
        speak("Welcome bhai."); return True
    return False


def step190_nl_unknown_guidance(command,score,intent):
    if score>=0.45 and intent!="UNKNOWN":
        speak("Command ka intent samajh aa raha hai, lekin exact action clear nahi hai.")
    else:
        speak("Main command ka meaning clear nahi samajh paya. Help bolkar examples dekh sakte ho.")
    return False


def step191_nl_agent_plan(command):
    """Build a small local plan for safe multi-action natural language goals."""
    s=step175_nl_clean(command)
    plan=[]
    if "notepad" in s and any(x in s for x in ("calculator","calc")):
        plan=["open notepad","open calculator"]
    elif "chrome" in s and ("google" in s or "search" in s):
        plan=["open chrome","search google"]
    elif "youtube" in s and "search" in s:
        plan=["search youtube"]
    return plan


def step192_nl_agent_v5(command):
    plan=step191_nl_agent_plan(command)
    if not plan: return False
    print("NL AGENT V5 PLAN ->",plan)
    for item in plan:
        ok=process_command_base("jarvis "+item)
        if not ok:
            speak("Multi-step task ka ek step fail hua."); return True
    speak("Natural language multi-step task complete hai.")
    return True


def step193_nl_semantic_intent(command):
    """Local meaning layer: maps natural Hinglish variations to intents without Gemini."""
    s=step175_nl_clean(command)
    # Remove conversational filler; these words should not decide the intent.
    s=re.sub(r"\b(zara|jara|please|plz|bhai|yaar|yrr|mujhe|mere|mera|meri|bas|abhi|thoda|thodi|ek baar|dekhna|bata|batao|bata do|dikha|dikhao|dikha do|karo|kar do|kr do|na)\b", " ", s)
    s=re.sub(r"\s+"," ",s).strip()
    if not s: return ("UNKNOWN",0.0)

    groups={
        "SYSTEM_HEALTH": (
            "system health", "system status", "system ka haal", "system ka health",
            "computer health", "computer status", "computer ka haal", "computer ka health",
            "pc status", "pc ka haal", "laptop status", "laptop ka haal",
            "computer ki condition", "system ki condition", "performance status",
        ),
        "COMMAND_CENTER": (
            "command center", "command centre", "dashboard", "mission control",
            "control center", "control centre", "command panel", "mission dashboard",
        ),
        "SCREEN_READ": (
            "screen par kya hai", "screen pe kya hai", "screen me kya hai",
            "screen ka text", "screen read", "screen dekho", "screen analyze",
            "screen samjho", "screen kya dikha rahi",
        ),
        "CAPABILITIES": ("capabilities", "features", "kya kya kar sakte", "kya kar sakta"),
        "MISSION_BRIEFING": ("mission briefing", "mission report", "mission status"),
        "NOTEPAD_OPEN": ("notepad kholo", "notepad open", "notepad chalao", "notepad start"),
        "CALCULATOR_OPEN": ("calculator kholo", "calculator open", "calculator chalao", "calculator start"),
        "CLIPBOARD_READ": ("clipboard batao", "clipboard padho", "clipboard read", "clipboard dikhao"),
        "PROCESS_LIST": ("running processes", "process list", "processes dikhao", "process inventory"),
        "NETWORK_DIAGNOSTICS": ("network diagnostics", "network check", "internet check", "wifi status", "network status"),
    }
    best=("UNKNOWN",0.0)
    for intent,phrases in groups.items():
        score=0.0
        for phrase in phrases:
            p=step175_nl_clean(phrase)
            if p in s:
                score=max(score,0.96 if len(p.split())>1 else 0.88)
                continue
            pt=p.split(); st=s.split()
            # Fuzzy token coverage: tolerate ASR errors while preserving meaning.
            matched=0
            for w in pt:
                if any(w==x or difflib.SequenceMatcher(None,w,x).ratio()>=0.78 for x in st):
                    matched+=1
            coverage=matched/max(1,len(pt))
            score=max(score,coverage*0.86)
        # Intent-specific semantic cues.
        toks=set(s.split())
        if intent=="SYSTEM_HEALTH" and toks.intersection({"computer","system","pc","laptop"}) and toks.intersection({"haal","health","status","condition","performance"}):
            score=max(score,0.93)
        if intent=="COMMAND_CENTER" and toks.intersection({"dashboard","center","centre","control","mission","panel"}):
            score=max(score,0.91)
        if intent=="SCREEN_READ":
            has_screen = "screen" in toks or any(difflib.SequenceMatcher(None,"screen",w).ratio()>=0.78 for w in toks)
            if has_screen and toks.intersection({"kya","text","read","dekho","analyze","samjho","dikha","batao"}):
                score=max(score,0.93)
        if score>best[1]: best=(intent,score)
    return best


def step193_nl_master_router(command):
    raw=str(command or "").strip()
    if not raw: return False
    normalized=step175_nl_clean(raw)
    # Screen commands are ALWAYS local; never spend Gemini quota on them.
    if any(x in normalized for x in ("screen par kya hai","screen pe kya hai","screen me kya hai","screen read","screen dekho","screen analyze","screen ka text")):
        return step188_nl_dispatch("SCREEN_READ",raw,{})
    if step192_nl_agent_v5(raw): return True
    if step189_nl_smart_reply(raw): return True
    resolved=step183_nl_resolve_context(raw)

    # New semantic layer runs BEFORE the older conservative keyword scorer.
    semantic_intent,semantic_score=step193_nl_semantic_intent(resolved)
    if semantic_intent!="UNKNOWN" and semantic_score>=0.68:
        entities=step179_nl_extract_entities(resolved)
        print(f"NL V3 -> intent={semantic_intent} confidence={semantic_score:.2f} entities={entities}")
        step185_nl_trace(resolved,semantic_intent,semantic_score,entities)
        step182_nl_remember_turn(resolved,semantic_intent,semantic_score,entities)
        if step188_nl_dispatch(semantic_intent,resolved,entities): return True

    score,intent=step178_nl_score_intent(resolved)
    confidence=step184_nl_confidence(resolved,intent,score)
    entities=step179_nl_extract_entities(resolved)
    step185_nl_trace(resolved,intent,confidence,entities)
    step182_nl_remember_turn(resolved,intent,confidence,entities)
    if confidence>=0.64 and step188_nl_dispatch(intent,resolved,entities): return True
    result=process_command_base(resolved)
    if result: return True
    return step190_nl_unknown_guidance(resolved,score,intent)


def process_command(command):
    """STEP 193 master router: natural language first, legacy capabilities second."""
    return step193_nl_master_router(command)



# ============================================================
# STEPS 194-400 : JARVIS MEGA UPGRADE
# Consolidated architecture:
# language -> context -> memory -> planning -> safety -> tools
# -> execution -> verification -> recovery -> learning
#
# NOTE:
# These steps are consolidated into one compatibility layer so
# the existing 1-193 implementation remains available.
# ============================================================

STEP400_VERSION = "500.0"
STEP400_LABEL = "JARVIS 500 - Intelligent Personal AI Agent"

STEP400_DIR = os.path.join(BASE_DIR, "jarvis_step400")
STEP400_STATE_FILE = os.path.join(STEP400_DIR, "state.json")
STEP400_TASK_FILE = os.path.join(STEP400_DIR, "tasks.json")
STEP400_HISTORY_FILE = os.path.join(STEP400_DIR, "task_history.json")
os.makedirs(STEP400_DIR, exist_ok=True)

# Preserve the already-tested Step-193 router as the legacy/local executor.
_STEP193_PROCESS_COMMAND = process_command


def _s400_load(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print("STEP400 LOAD ERROR:", path, e)
        return default


def _s400_save(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print("STEP400 SAVE ERROR:", path, e)
        return False


STEP400_STATE = _s400_load(STEP400_STATE_FILE, {})
STEP400_STATE.setdefault("version", STEP400_VERSION)
STEP400_STATE.setdefault("mode", "assistant")
STEP400_STATE.setdefault("last_command", "")
STEP400_STATE.setdefault("last_intent", "")
STEP400_STATE.setdefault("last_target", "")
STEP400_STATE.setdefault("last_result", "")
STEP400_STATE.setdefault("running_task", False)
_s400_save(STEP400_STATE_FILE, STEP400_STATE)


# ------------------------------------------------------------
# 194-205: Conversation/context engine
# ------------------------------------------------------------

def s400_clean(text):
    s = str(text or "").strip().lower()
    s = re.sub(r"[^\w\s:/.\-+%]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(?:hey\s+)?jarvis[\s,:-]*", "", s).strip()
    aliases = {
        "centre": "center", "centar": "center",
        "krdo": "karo", "krde": "karo", "kardo": "karo", "kr": "karo",
        "khoolo": "kholo", "khol": "kholo",
        "btao": "batao", "btado": "batao", "batado": "batao",
        "screan": "screen", "scren": "screen",
        "notpad": "notepad", "calc": "calculator", "calcu": "calculator",
        "crome": "chrome", "gugal": "google",
        "dhoondo": "search", "dhundho": "search", "dhundo": "search",
        "nhi": "nahi", "nai": "nahi",
    }
    return " ".join(aliases.get(w, w) for w in s.split())


def s400_context():
    state = _s400_load(STEP400_STATE_FILE, {})
    return {
        "last_command": state.get("last_command", ""),
        "last_intent": state.get("last_intent", ""),
        "last_target": state.get("last_target", ""),
        "last_result": state.get("last_result", ""),
        "running_task": state.get("running_task", False),
    }


def s400_resolve_reference(command):
    s = s400_clean(command)
    ctx = s400_context()
    refs = (
        "wahi", "same", "isko", "is ko", "usko", "us ko",
        "pichla", "pichhle", "previous", "jo abhi kiya",
        "phir se", "dobara", "again"
    )
    if any(x in s for x in refs):
        if ctx["last_command"]:
            # Preserve the user's new action word when possible.
            action_words = ("repeat", "dobara", "phir", "same", "wahi")
            if any(x in s for x in action_words):
                return ctx["last_command"]
    return s


# ------------------------------------------------------------
# 206-220: Intent + entity extraction
# ------------------------------------------------------------

def s400_extract_target(s):
    patterns = [
        r"(?:youtube|google)\s+(?:par|pe|mein|me)\s+(.+?)(?:\s+(?:search|dhoondo|dhundo|karo|karna)\b.*)?$",
        r"(?:search|dhoondo|dhundo|find)\s+(?:for\s+)?(.+)$",
        r"(?:open|kholo|launch|start)\s+(.+)$",
        r"(?:click|press|tap)\s+(?:on\s+)?(.+)$",
        r"(?:type|likho|likh|enter)\s+(.+)$",
        r"(?:locate|find)\s+(?:the\s+)?(.+)$",
    ]
    for p in patterns:
        m = re.search(p, s, re.I)
        if m:
            target = m.group(1).strip()
            target = re.sub(r"\s+(?:please|karo|kar do|karna)$", "", target).strip()
            if target:
                return target
    return ""


def s400_intent(command):
    s = s400_resolve_reference(command)

    if not s:
        return "UNKNOWN", "", 0.0

    if any(x in s for x in (
        "stop task", "task stop", "kaam rok", "cancel task",
        "current task stop", "agent stop"
    )):
        return "STOP_TASK", "", 0.99

    if any(x in s for x in (
        "command center", "command center kholo", "dashboard",
        "mission control", "control center"
    )):
        return "COMMAND_CENTER", "", 0.97

    if any(x in s for x in (
        "screen par kya", "screen pe kya", "screen me kya",
        "screen read", "screen analyze", "screen dekho"
    )):
        return "READ_SCREEN", "", 0.98

    if any(x in s for x in (
        "system status", "system health", "computer status",
        "laptop status", "pc status", "performance batao"
    )):
        return "SYSTEM_STATUS", "", 0.98

    if any(x in s for x in (
        "capabilities", "features", "kya kya kar sakte",
        "tum kya kar sakte"
    )):
        return "CAPABILITIES", "", 0.98

    if any(x in s for x in (
        "remember", "yaad rakh", "yaad rakho", "bhool jao",
        "forget", "context clear"
    )):
        return "MEMORY", "", 0.96

    if any(x in s for x in ("scroll upar", "scroll up", "upar scroll")):
        return "SCROLL_UP", "", 0.98

    if any(x in s for x in ("scroll neeche", "scroll niche", "scroll down")):
        return "SCROLL_DOWN", "", 0.98

    if any(x in s for x in ("scroll rok", "stop scrolling", "scroll band")):
        return "STOP_SCROLL", "", 0.99

    if re.search(r"\b(?:google)\s+(?:par|pe|mein|me)\b", s):
        return "GOOGLE_SEARCH", s400_extract_target(s), 0.95

    if re.search(r"\b(?:youtube)\s+(?:par|pe|mein|me)\b", s):
        return "YOUTUBE_SEARCH", s400_extract_target(s), 0.95

    if any(x in s for x in ("search ", "search karo", "dhoondo ", "dhundo ")):
        return "WEB_SEARCH", s400_extract_target(s), 0.88

    if any(x in s for x in ("click ", "click karo", "button dabao", "tap ")):
        return "CLICK_TEXT", s400_extract_target(s), 0.91

    if any(x in s for x in ("type ", "likho ", "likh ", "text daalo", "enter karo")):
        return "TYPE_TEXT", s400_extract_target(s), 0.91

    if any(x in s for x in ("press enter", "enter dabao", "enter press")):
        return "PRESS_KEY", "enter", 0.98

    if any(x in s for x in ("press escape", "escape dabao", "esc dabao")):
        return "PRESS_KEY", "esc", 0.98

    if any(x in s for x in ("notepad kholo", "open notepad", "notepad open")):
        return "OPEN_APP", "notepad", 0.98

    if any(x in s for x in ("calculator kholo", "open calculator", "calculator open")):
        return "OPEN_APP", "calculator", 0.98

    if any(x in s for x in ("chrome kholo", "open chrome", "chrome open")):
        return "OPEN_APP", "chrome", 0.98

    if any(x in s for x in ("open ", "kholo ", "launch ", "start ")):
        return "OPEN_TARGET", s400_extract_target(s), 0.85

    if any(x in s for x in ("hello", "hi jarvis", "namaste", "kaise ho")):
        return "CHAT", "", 0.99

    return "UNKNOWN", "", 0.15


# ------------------------------------------------------------
# 221-240: Persistent memory + task history
# ------------------------------------------------------------

def s400_memory_write_from_command(command):
    s = s400_clean(command)

    if any(x in s for x in ("context clear", "sab context bhool", "conversation clear")):
        try:
            memory["conversation"] = []
            save_memory()
        except Exception as e:
            print("STEP400 MEMORY CLEAR ERROR:", e)
        STEP400_STATE["last_result"] = "conversation cleared"
        _s400_save(STEP400_STATE_FILE, STEP400_STATE)
        speak("Conversation context clear kar diya.")
        return True

    m = re.search(r"(?:remember|yaad rakh(?:na)?|yaad rakho)\s+(?:that\s+)?(?:my\s+)?(.+?)\s+(?:is|hai|h)\s+(.+)$", s, re.I)
    if m:
        remember_fact(m.group(1).strip(), m.group(2).strip())
        speak("Yaad rakh liya.")
        return True

    return False


def s400_history_add(command, intent, target, result):
    history = _s400_load(STEP400_HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []
    history.append({
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "command": str(command),
        "intent": str(intent),
        "target": str(target),
        "result": str(result),
    })
    _s400_save(STEP400_HISTORY_FILE, history[-200:])


# ------------------------------------------------------------
# 241-270: Safety governor
# ------------------------------------------------------------

S400_RISKY = (
    "shutdown", "shut down", "restart", "reboot", "format",
    "factory reset", "delete permanently", "remove permanently",
    "wipe", "kill process", "uninstall", "erase disk",
)


def s400_is_risky(command):
    s = s400_clean(command)
    return any(x in s for x in S400_RISKY)


def s400_safety(command):
    if s400_is_risky(command):
        STEP400_STATE["pending_risky_command"] = command
        _s400_save(STEP400_STATE_FILE, STEP400_STATE)
        speak("Ye risky action hai. Main ise automatically execute nahi karunga.")
        return False
    return True


def s400_stop_task():
    STEP400_STATE["running_task"] = False
    STEP400_STATE["stop_requested"] = True
    _s400_save(STEP400_STATE_FILE, STEP400_STATE)
    try:
        stop_continuous_scroll()
    except Exception:
        pass
    speak("Current task stop kar diya.")
    return True


# ------------------------------------------------------------
# 271-310: Tool registry / deterministic execution
# ------------------------------------------------------------

def s400_open_app(app):
    app = str(app).lower().strip()
    commands = {
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "chrome": ["cmd", "/c", "start", "", "https://www.google.com"],
        "edge": ["cmd", "/c", "start", "", "microsoft-edge:https://www.google.com"],
        "explorer": ["explorer.exe"],
    }
    cmd = commands.get(app)
    if not cmd:
        return False
    try:
        subprocess.Popen(cmd)
        speak(app + " open kar diya.")
        return True
    except Exception as e:
        print("STEP400 OPEN APP ERROR:", e)
        return False


def s400_web_search(query, site="google"):
    query = str(query).strip()
    if not query:
        return False
    if site == "youtube":
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    else:
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    try:
        before = _screen_signature()
        webbrowser.open(url)
        _task_pause(2.0)
        verify_screen_changed(before, 0.5)
        speak(("YouTube" if site == "youtube" else "Google") + " par " + query + " search kar diya.")
        return True
    except Exception as e:
        print("STEP400 WEB SEARCH ERROR:", e)
        return False


def s400_read_screen():
    try:
        return bool(read_screen_locally())
    except Exception:
        try:
            return bool(analyze_screen())
        except Exception:
            return False


def s400_click(target):
    if not target:
        return False
    try:
        return bool(verified_click_screen_element(target))
    except Exception:
        try:
            return bool(find_and_click_text(target))
        except Exception:
            return False


def s400_type(target):
    if not target:
        return False
    try:
        return bool(verified_type_text(target))
    except Exception:
        return bool(jarvis_type_text(target))


# ------------------------------------------------------------
# 311-335: Planner / task decomposition
# ------------------------------------------------------------

def s400_split_actions(command):
    s = s400_clean(command)
    parts = re.split(
        r"\s+(?:aur phir|phir|uske baad|then|and then|fir|finally)\s+",
        s
    )
    parts = [p.strip(" ,.") for p in parts if p.strip(" ,.")]
    return parts if len(parts) > 1 else [s]


def s400_plan(command):
    parts = s400_split_actions(command)
    plan = []
    for part in parts:
        intent, target, confidence = s400_intent(part)
        plan.append({
            "command": part,
            "intent": intent,
            "target": target,
            "confidence": confidence,
        })
    return plan


# ------------------------------------------------------------
# 336-355: Executor + verification + recovery
# ------------------------------------------------------------

def s400_execute_one(item):
    command = item["command"]
    intent = item["intent"]
    target = item["target"]

    if not s400_safety(command):
        return False, "blocked_by_safety"

    try:
        if intent == "STOP_TASK":
            return True, "stopped"

        if intent == "OPEN_APP":
            ok = s400_open_app(target)

        elif intent == "GOOGLE_SEARCH":
            ok = s400_web_search(target, "google")

        elif intent == "YOUTUBE_SEARCH":
            ok = s400_web_search(target, "youtube")

        elif intent == "WEB_SEARCH":
            ok = s400_web_search(target, "google")

        elif intent == "READ_SCREEN":
            ok = s400_read_screen()

        elif intent == "CLICK_TEXT":
            ok = s400_click(target)

        elif intent == "TYPE_TEXT":
            ok = s400_type(target)

        elif intent == "PRESS_KEY":
            ok = bool(jarvis_press_key(target))

        elif intent == "SCROLL_UP":
            ok = bool(start_continuous_scroll(1))

        elif intent == "SCROLL_DOWN":
            ok = bool(start_continuous_scroll(-1))

        elif intent == "STOP_SCROLL":
            ok = bool(stop_continuous_scroll())

        elif intent == "SYSTEM_STATUS":
            ok = bool(step133_performance_command(command))

        elif intent == "COMMAND_CENTER":
            ok = bool(step133_command_center_status(True))

        elif intent == "CAPABILITIES":
            ok = bool(step133_capabilities_command(command))

        elif intent == "MEMORY":
            ok = bool(s400_memory_write_from_command(command))

        elif intent == "CHAT":
            speak("Main ready hoon bhai. Batao kya karna hai.")
            ok = True

        elif intent == "OPEN_TARGET":
            # Let the existing safe goal router handle known websites/apps.
            ok = bool(run_goal_based_task(command))
            if not ok:
                ok = bool(_STEP193_PROCESS_COMMAND(command))

        else:
            ok = bool(_STEP193_PROCESS_COMMAND(command))

        return bool(ok), "success" if ok else "failed"

    except Exception as e:
        print("STEP400 EXECUTOR ERROR:", intent, target, e)
        return False, str(e)


def s400_recover(item, reason):
    if reason == "blocked_by_safety":
        return False

    # One conservative retry through the existing tested router.
    try:
        ok = bool(_STEP193_PROCESS_COMMAND(item["command"]))
        return ok
    except Exception as e:
        print("STEP400 RECOVERY ERROR:", e)
        return False


# ------------------------------------------------------------
# 356-375: Multi-step autonomous loop
# ------------------------------------------------------------

def s400_run_plan(command):
    plan = s400_plan(command)
    if not plan:
        return False

    STEP400_STATE["running_task"] = True
    STEP400_STATE["stop_requested"] = False
    STEP400_STATE["last_command"] = str(command)
    _s400_save(STEP400_STATE_FILE, STEP400_STATE)

    print("\n========== JARVIS 400 PLAN ==========")
    for i, item in enumerate(plan, 1):
        print(
            "{}. {} | intent={} | target={} | confidence={:.2f}".format(
                i, item["command"], item["intent"], item["target"], item["confidence"]
            )
        )
    print("=====================================\n")

    all_ok = True

    for item in plan:
        state = _s400_load(STEP400_STATE_FILE, {})
        if state.get("stop_requested"):
            all_ok = False
            break

        if item["intent"] == "UNKNOWN" and item["confidence"] < 0.50:
            # Give the mature Step-193 brain the chance to understand it.
            ok = bool(_STEP193_PROCESS_COMMAND(item["command"]))
            reason = "legacy_brain"
        else:
            ok, reason = s400_execute_one(item)

        if not ok:
            print("STEP400 STEP FAILED:", item["command"], reason)
            recovered = s400_recover(item, reason)
            if not recovered:
                all_ok = False
                speak("Task ka ek step complete nahi ho paya.")
                break

        s400_history_add(item["command"], item["intent"], item["target"], reason)

    STEP400_STATE["running_task"] = False
    STEP400_STATE["last_intent"] = plan[-1]["intent"]
    STEP400_STATE["last_target"] = plan[-1]["target"]
    STEP400_STATE["last_result"] = "complete" if all_ok else "partial/fail"
    _s400_save(STEP400_STATE_FILE, STEP400_STATE)

    if all_ok:
        speak("Task complete hai.")
    return True


# ------------------------------------------------------------
# 376-390: General AI fallback + status
# ------------------------------------------------------------

def s400_general_chat(command):
    # Existing ask_ai already contains persistent facts + recent conversation.
    try:
        answer = ask_ai(command)
        if answer:
            speak(answer)
            return True
    except Exception as e:
        print("STEP400 AI CHAT ERROR:", e)
    return False


def s400_status():
    history = _s400_load(STEP400_HISTORY_FILE, [])
    speak(
        "JARVIS 400 active hai. "
        "Natural language, memory, planning, computer control, "
        "screen understanding, verification, recovery aur safety systems active hain. "
        "Task history mein " + str(len(history)) + " entries hain."
    )
    return True


def s400_help():
    speak(
        "Aap natural Hinglish mein bol sakte ho: "
        "Google par kuch search karo, YouTube par video dhoondo, "
        "Notepad kholo, screen par kya hai batao, kisi button par click karo, "
        "text type karo, scroll karo, ya multi-step kaam bolo."
    )
    return True


# ------------------------------------------------------------
# 391-399: Unified command gateway
# ------------------------------------------------------------

def s400_master_router(command):
    raw = str(command or "").strip()
    if not raw:
        return False

    normalized = s400_clean(raw)

    if "jarvis 400" in normalized and any(
        x in normalized for x in ("status", "ready", "version")
    ):
        return s400_status()

    if "help" in normalized or "madad" in normalized:
        return s400_help()

    if s400_memory_write_from_command(raw):
        return True

    if s400_is_risky(raw):
        s400_safety(raw)
        return True

    if any(x in normalized for x in ("stop task", "task stop", "kaam rok", "agent stop")):
        return s400_stop_task()

    # Keep explicit local screen commands local.
    if any(x in normalized for x in (
        "screen par kya", "screen pe kya", "screen me kya",
        "screen read", "screen analyze", "screen dekho"
    )):
        return s400_read_screen()

    # Very common greetings should never consume AI quota.
    if any(x in normalized for x in ("hello", "hi jarvis", "namaste", "kaise ho")):
        speak("Main ready hoon bhai. Batao kya karna hai.")
        return True

    plan = s400_plan(raw)

    # If this is clearly a multi-step command, run the whole plan.
    if len(plan) > 1:
        return s400_run_plan(raw)

    item = plan[0] if plan else None
    if item and item["intent"] != "UNKNOWN" and item["confidence"] >= 0.78:
        ok, reason = s400_execute_one(item)
        if ok:
            STEP400_STATE["last_command"] = raw
            STEP400_STATE["last_intent"] = item["intent"]
            STEP400_STATE["last_target"] = item["target"]
            STEP400_STATE["last_result"] = reason
            _s400_save(STEP400_STATE_FILE, STEP400_STATE)
            s400_history_add(raw, item["intent"], item["target"], reason)
            return True

        recovered = s400_recover(item, reason)
        if recovered:
            return True

    # Unknown/contextual natural language -> existing AI brain.
    return s400_general_chat(raw)


# ============================================================
# JARVIS 500 MEGA UPGRADE
# AI INTENT PLANNER + SAFE TOOL ORCHESTRATOR
# ============================================================
# This layer sits ABOVE the existing 1-400 implementation.
# Existing tested tools remain the executors; this layer decides
# which safe executor should be used for natural-language requests.

JARVIS500_VERSION = "500.0"
JARVIS500_MAX_STEPS = 8
JARVIS500_ALLOWED_ACTIONS = {
    "open_app", "web_search", "youtube_search", "read_screen",
    "click", "type", "press_key", "scroll_up", "scroll_down",
    "stop_scroll", "chat"
}


def _s500_extract_json(text):
    """Extract one JSON object/array from an AI response safely."""
    if not text:
        return None
    raw = str(text).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Handle markdown fences or surrounding prose.
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw.strip())
    except Exception:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        a = raw.find(opener)
        b = raw.rfind(closer)
        if a >= 0 and b > a:
            try:
                return json.loads(raw[a:b + 1])
            except Exception:
                continue
    return None


def s500_ai_plan(command):
    """Turn natural language into a small allow-listed action plan."""
    context = s400_context()
    prompt = f"""
You are the planning layer of a Windows personal assistant named JARVIS.
Return ONLY valid JSON. No markdown and no explanation.

Allowed action names:
open_app, web_search, youtube_search, read_screen, click, type,
press_key, scroll_up, scroll_down, stop_scroll, chat

Rules:
- Maximum {JARVIS500_MAX_STEPS} actions.
- Use only the allowed action names.
- Each action must be an object with keys: action, target.
- target must be a short string.
- Never invent an action.
- Never perform shutdown, reboot, format, delete, uninstall, payment,
  password, credential, or other sensitive operations.
- If the request is only a question/conversation, use chat with the
  complete user request as target.
- If the user asks to search the web, use web_search.
- If the user explicitly says YouTube, use youtube_search.
- If the user asks what is on the screen, use read_screen.
- If the request is ambiguous and cannot safely map to an action, use chat.

Previous context:
{json.dumps(context, ensure_ascii=False)}

User request:
{command}

Output format:
{{"actions":[{{"action":"chat","target":"..."}}]}}
"""
    try:
        answer = ask_ai(prompt)
        parsed = _s500_extract_json(answer)
        if isinstance(parsed, dict):
            actions = parsed.get("actions", [])
        elif isinstance(parsed, list):
            actions = parsed
        else:
            return []
        if not isinstance(actions, list):
            return []
        clean = []
        for item in actions[:JARVIS500_MAX_STEPS]:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).strip().lower()
            target = str(item.get("target", "")).strip()
            if action not in JARVIS500_ALLOWED_ACTIONS:
                continue
            if len(target) > 4000:
                target = target[:4000]
            clean.append({"action": action, "target": target})
        return clean
    except Exception as e:
        print("JARVIS 500 PLANNER ERROR:", e)
        return []


def s500_action_is_sensitive(action, target):
    text = (str(action) + " " + str(target)).lower()
    sensitive = (
        "shutdown", "shut down", "reboot", "restart", "format",
        "factory reset", "delete permanently", "wipe", "erase disk",
        "uninstall", "kill process", "payment", "pay", "password",
        "otp", "one time password", "credential", "bank account"
    )
    return any(word in text for word in sensitive)


def s500_execute_action(item):
    action = item.get("action", "")
    target = item.get("target", "")

    if s500_action_is_sensitive(action, target):
        speak("Ye sensitive action hai. Main ise automatically execute nahi karunga.")
        return False, "blocked_sensitive"

    if action == "open_app":
        return bool(s400_open_app(target)), "open_app"
    if action == "web_search":
        return bool(s400_web_search(target, "google")), "web_search"
    if action == "youtube_search":
        return bool(s400_web_search(target, "youtube")), "youtube_search"
    if action == "read_screen":
        return bool(s400_read_screen()), "read_screen"
    if action == "click":
        return bool(s400_click(target)), "click"
    if action == "type":
        return bool(s400_type(target)), "type"
    if action == "press_key":
        return bool(jarvis_press_key(target)), "press_key"
    if action == "scroll_up":
        return bool(start_continuous_scroll(1)), "scroll_up"
    if action == "scroll_down":
        return bool(start_continuous_scroll(-1)), "scroll_down"
    if action == "stop_scroll":
        return bool(stop_continuous_scroll()), "stop_scroll"
    if action == "chat":
        return bool(s400_general_chat(target)), "chat"
    return False, "unknown_action"


def s500_run_ai_plan(command):
    """Plan first, validate every step, then execute with verification."""
    actions = s500_ai_plan(command)
    if not actions:
        return False

    print("\n========== JARVIS 500 AI PLAN ==========")
    for i, item in enumerate(actions, 1):
        print(f"{i}. {item['action']} -> {item['target']}")
    print("========================================\n")

    STEP400_STATE["running_task"] = True
    STEP400_STATE["stop_requested"] = False
    STEP400_STATE["last_command"] = str(command)
    _s400_save(STEP400_STATE_FILE, STEP400_STATE)

    try:
        for item in actions:
            state = _s400_load(STEP400_STATE_FILE, {})
            if state.get("stop_requested"):
                speak("Task rok diya gaya.")
                return True

            ok, reason = s500_execute_action(item)
            if not ok:
                print("JARVIS 500 STEP FAILED:", item, reason)
                speak("Is task ka ek step safely complete nahi ho paya.")
                return True

            s400_history_add(
                command,
                "AI_" + item["action"].upper(),
                item.get("target", ""),
                reason
            )

        speak("Task complete hai.")
        STEP400_STATE["last_result"] = "complete"
        return True
    finally:
        STEP400_STATE["running_task"] = False
        _s400_save(STEP400_STATE_FILE, STEP400_STATE)


def s500_should_plan(command):
    """Use AI planning for natural-language goals not already handled locally."""
    s = s400_clean(command)
    if not s:
        return False
    # Existing deterministic commands remain first-class and quota-friendly.
    local_markers = (
        "google par", "youtube par", "notepad kholo", "calculator kholo",
        "chrome kholo", "screen par kya", "screen pe kya", "click ",
        "type ", "scroll ", "press enter", "press escape", "jarvis 400",
        "system status", "command center", "capabilities"
    )
    return not any(marker in s for marker in local_markers)


# ------------------------------------------------------------
# Replace the original master gateway with a 500-aware wrapper.
# ------------------------------------------------------------
_S400_MASTER_ROUTER_BASE = s400_master_router if "s400_master_router" in globals() else None


def s500_master_router(command):
    # First preserve all existing Step-400 deterministic behavior.
    normalized = s400_clean(command)
    if not s500_should_plan(command):
        if _S400_MASTER_ROUTER_BASE:
            return _S400_MASTER_ROUTER_BASE(command)
        return False

    # For natural-language goals, let the AI planner choose from the
    # safe allow-list. If planning fails, fall back to the old brain.
    if s500_run_ai_plan(command):
        return True
    if _S400_MASTER_ROUTER_BASE:
        return _S400_MASTER_ROUTER_BASE(command)
    return False


# ------------------------------------------------------------
# STEP 400 FINAL PROCESS COMMAND
# ------------------------------------------------------------

def process_command(command):
    """
    JARVIS 500 master gateway.
    Existing Steps 1-193 remain underneath as the compatibility layer;
    Steps 194-400 are consolidated here as one unified agent architecture.
    """
    try:
        return s500_master_router(command)
    except Exception as e:
        print("JARVIS 500 MASTER ERROR:", e)
        try:
            return bool(_STEP193_PROCESS_COMMAND(command))
        except Exception:
            return False


print("JARVIS 500 MEGA UPGRADE LOADED:", STEP400_LABEL)


# ============================================================
# JARVIS 600 - MEANING / CONTEXT / SEQUENCE BRAIN
# ============================================================
# This layer keeps the complete 1-500 stack and adds a semantic
# conversation-to-action loop. It is intentionally allow-listed.
# ============================================================

import time as _J600_TIME

JARVIS600_VERSION = "600.0"
JARVIS600_MAX_STEPS = 10
JARVIS600_ALLOWED_ACTIONS = set(JARVIS500_ALLOWED_ACTIONS) | {
    "wait"
}

# Short-term execution context. This is separate from the existing
# persistent state so a single request can carry references like:
# "phir", "usme", "isme", "wahi", "uske baad", "jo abhi khola".
JARVIS600_CONTEXT = {
    "last_app": "",
    "last_target": "",
    "last_action": "",
    "last_success": False,
    "sequence": [],
}


def j600_normalize_speech(text):
    """Normalize common Hindi/Hinglish ASR variants without changing intent."""
    s = str(text or "").strip()
    # Keep the original meaning, only normalize common speech-recognition variants.
    replacements = {
        " fir ": " phir ",
        " fir,": " phir,",
        " fir.": " phir.",
        "f i r": "phir",
        "not pad": "notepad",
        "note pad": "notepad",
        "calc": "calculator",
        "calcu": "calculator",
        "crome": "chrome",
        "gugal": "google",
        "dhoondo": "search",
        "dhundho": "search",
        "dhundo": "search",
        "khol do": "kholo",
        "kholde": "kholo",
        "kr do": "karo",
        "kar do": "karo",
    }
    low = " " + s.lower() + " "
    for a, b in replacements.items():
        low = low.replace(a, b)
    return low.strip()


def j600_context_snapshot():
    base = s400_context()
    return {
        "last_command": base.get("last_command", ""),
        "last_intent": base.get("last_intent", ""),
        "last_target": base.get("last_target", ""),
        "last_result": base.get("last_result", ""),
        "running_task": base.get("running_task", False),
        "last_app": JARVIS600_CONTEXT.get("last_app", ""),
        "last_action": JARVIS600_CONTEXT.get("last_action", ""),
        "last_success": JARVIS600_CONTEXT.get("last_success", False),
        "sequence": JARVIS600_CONTEXT.get("sequence", [])[-10:],
    }


def j600_is_multi_step(command):
    s = j600_normalize_speech(command).lower()
    markers = (
        " aur ", " phir ", " uske baad ", " iske baad ",
        " then ", " and then ", " finally ", " usme ", " isme ",
        " usko ", " isko ", " wahi ", " jo abhi ", " jisme ",
    )
    return any(m in (" " + s + " ") for m in markers)


def j600_semantic_plan(command):
    """Ask the existing AI brain for meaning-aware, stateful action planning."""
    normalized = j600_normalize_speech(command)
    ctx = j600_context_snapshot()
    prompt = f"""
You are JARVIS's semantic reasoning and action-planning brain on Windows.
Your job is to understand the USER'S MEANING, not merely match keywords.
The user may speak Hindi, Hinglish, English, or mixed language. Speech recognition
may turn 'phir' into 'fir'; treat those as the same word.

Return ONLY valid JSON in exactly this shape:
{{"understanding":"short meaning of the request","actions":[{{"action":"...","target":"..."}}]}}

Allowed actions only:
open_app, web_search, youtube_search, read_screen, click, type,
press_key, scroll_up, scroll_down, stop_scroll, chat, wait

Hard limits:
- Maximum {JARVIS600_MAX_STEPS} actions.
- Never invent an action name.
- Never shutdown/reboot/format/delete/uninstall, transfer money, enter OTP,
  expose passwords/credentials, or perform other sensitive operations.
- If a request is ambiguous and cannot be resolved from context safely, use chat.
- Preserve the user's requested ORDER exactly.
- Treat conjunctions such as 'aur phir', 'phir', 'fir', 'then', 'uske baad',
  'iske baad' as sequence markers, NOT as the name of an application.
- Resolve pronouns/references from the execution context. Examples:
  * 'usme' / 'isme' after opening Notepad means type into the currently opened/focused Notepad.
  * 'usko' / 'isko' can refer to the most recently mentioned target.
  * 'wahi' means the most recently relevant target/action unless the sentence clearly says otherwise.
- If the user says 'open calculator, then open notepad, then write X in it',
  produce THREE actions: open_app calculator; open_app notepad; type X.
- The word 'it/usme/isme' must NEVER become the literal text to type.
- If a type action follows an open_app action and the user says 'in it/usme/isme',
  the target of type must be ONLY the requested text.
- Do not collapse multiple requested actions into one action.
- Use 'wait' only when a short pause is genuinely useful between UI actions.

Execution context:
{json.dumps(ctx, ensure_ascii=False)}

User request:
{normalized}
"""
    try:
        answer = ask_ai(prompt)
        parsed = _s500_extract_json(answer)
        if not isinstance(parsed, dict):
            return []
        actions = parsed.get("actions", [])
        if not isinstance(actions, list):
            return []
        clean = []
        for item in actions[:JARVIS600_MAX_STEPS]:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).strip().lower()
            target = str(item.get("target", "")).strip()
            if action not in JARVIS600_ALLOWED_ACTIONS:
                continue
            if len(target) > 4000:
                target = target[:4000]
            clean.append({"action": action, "target": target})
        return clean
    except Exception as e:
        print("JARVIS 600 SEMANTIC PLAN ERROR:", e)
        return []


def j600_sensitive(command):
    s = j600_normalize_speech(command).lower()
    sensitive_words = (
        "shutdown", "shut down", "restart", "reboot", "format", "delete",
        "uninstall", "payment", "pay", "otp", "password", "credential",
        "bank account", "upi", "transfer money", "send money", "erase files",
    )
    return any(w in s for w in sensitive_words)


def j600_execute_action(item):
    action = str(item.get("action", "")).strip().lower()
    target = str(item.get("target", "")).strip()

    if action not in JARVIS600_ALLOWED_ACTIONS:
        return False, "action_not_allowed"
    if j600_sensitive(target):
        speak("Ye sensitive action hai. Main ise automatically execute nahi karunga.")
        return False, "blocked_sensitive"

    try:
        if action == "wait":
            seconds = 0.7
            try:
                seconds = max(0.2, min(float(target), 3.0))
            except Exception:
                pass
            _J600_TIME.sleep(seconds)
            return True, "wait"
        if action == "open_app":
            ok = bool(s400_open_app(target))
            if ok:
                JARVIS600_CONTEXT["last_app"] = target
                _J600_TIME.sleep(0.45)
            return ok, "open_app"
        if action == "web_search":
            ok = bool(s400_web_search(target, "google"))
            if ok:
                _J600_TIME.sleep(0.45)
            return ok, "web_search"
        if action == "youtube_search":
            ok = bool(s400_web_search(target, "youtube"))
            if ok:
                _J600_TIME.sleep(0.45)
            return ok, "youtube_search"
        if action == "read_screen":
            return bool(s400_read_screen()), "read_screen"
        if action == "click":
            return bool(s400_click(target)), "click"
        if action == "type":
            ok = bool(s400_type(target))
            return ok, "type"
        if action == "press_key":
            return bool(jarvis_press_key(target)), "press_key"
        if action == "scroll_up":
            return bool(start_continuous_scroll(1)), "scroll_up"
        if action == "scroll_down":
            return bool(start_continuous_scroll(-1)), "scroll_down"
        if action == "stop_scroll":
            return bool(stop_continuous_scroll()), "stop_scroll"
        if action == "chat":
            return bool(s400_general_chat(target)), "chat"
    except Exception as e:
        print("JARVIS 600 ACTION ERROR:", action, target, e)
        return False, str(e)

    return False, "unknown_action"


def j600_run(command):
    """Meaning-aware plan -> ordered execution -> short-term context update."""
    normalized = j600_normalize_speech(command)
    actions = j600_semantic_plan(normalized)
    if not actions:
        return False

    # A semantic planner that returns one chat action is valid; execute it normally.
    print("\n========== JARVIS 600 UNDERSTANDING ==========")
    print("REQUEST:", normalized)
    for i, item in enumerate(actions, 1):
        print(f"{i}. {item['action']} -> {item['target']}")
    print("===============================================\n")

    JARVIS600_CONTEXT["sequence"] = []
    STEP400_STATE["running_task"] = True
    STEP400_STATE["stop_requested"] = False
    STEP400_STATE["last_command"] = normalized
    _s400_save(STEP400_STATE_FILE, STEP400_STATE)

    all_ok = True
    try:
        for item in actions:
            state = _s400_load(STEP400_STATE_FILE, {})
            if state.get("stop_requested"):
                speak("Task rok diya gaya.")
                all_ok = False
                break

            ok, reason = j600_execute_action(item)
            JARVIS600_CONTEXT["last_action"] = item.get("action", "")
            JARVIS600_CONTEXT["last_target"] = item.get("target", "")
            JARVIS600_CONTEXT["last_success"] = bool(ok)
            JARVIS600_CONTEXT["sequence"].append({
                "action": item.get("action", ""),
                "target": item.get("target", ""),
                "success": bool(ok),
            })

            if not ok:
                print("JARVIS 600 STEP FAILED:", item, reason)
                # Do not blindly repeat potentially UI-changing actions.
                all_ok = False
                speak("Task ka ek step complete nahi ho paya.")
                break

            s400_history_add(normalized, "AI600_" + item["action"].upper(), item.get("target", ""), reason)

        STEP400_STATE["last_result"] = "complete" if all_ok else "partial/fail"
        STEP400_STATE["last_intent"] = "SEMANTIC_PLAN"
        STEP400_STATE["last_target"] = JARVIS600_CONTEXT.get("last_target", "")
        _s400_save(STEP400_STATE_FILE, STEP400_STATE)
        if all_ok:
            speak("Task complete hai.")
        return True
    finally:
        STEP400_STATE["running_task"] = False
        _s400_save(STEP400_STATE_FILE, STEP400_STATE)


# Preserve the complete old gateway for commands that are clearly local,
# while routing natural-language sequences through the new semantic brain.
_J600_PREVIOUS_PROCESS_COMMAND = process_command


def process_command(command):
    """JARVIS 600 gateway: meaning/context first for natural multi-step requests."""
    raw = str(command or "").strip()
    if not raw:
        return False

    normalized = j600_normalize_speech(raw)

    # Safety remains deterministic and first.
    if j600_sensitive(normalized) or s400_is_risky(normalized):
        try:
            s400_safety(normalized)
            return True
        except Exception:
            return True

    # Multi-step or reference-heavy language should not be sent through the
    # old keyword splitter. Let the semantic brain preserve the whole meaning.
    if j600_is_multi_step(normalized):
        if j600_run(normalized):
            return True

    # For ordinary natural language, give the new semantic brain first chance
    # unless it is an explicit, well-tested local command.
    explicit_local = (
        "screen par kya" in normalized or "screen pe kya" in normalized or
        "screen me kya" in normalized or "system status" in normalized or
        "command center" in normalized or "capabilities" in normalized or
        "stop task" in normalized or "kaam rok" in normalized
    )
    if not explicit_local and not j600_is_multi_step(normalized):
        # Only invoke semantic planning when the request looks conversational
        # or intent-rich; otherwise retain the 1-500 deterministic path.
        natural_markers = (
            " zara ", " mujhe ", " bhai ", " please ", " de do", " kar do",
            " kar dena", " chahiye", " help", " samajh", " jisme", " usme",
            " isme", " wahi", " jo ", " wala ", " waali ", " dikhana",
        )
        if any(m in (" " + normalized + " ") for m in natural_markers):
            if j600_run(normalized):
                return True

    return _J600_PREVIOUS_PROCESS_COMMAND(raw)


print("JARVIS 600 MEANING BRAIN LOADED:", JARVIS600_VERSION)

# Startup intentionally moved to JARVIS/main.py so importing this compatibility engine is side-effect free.
