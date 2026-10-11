import sys
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from JARVIS.core.app import JarvisApp
from JARVIS.legacy_engine import process_command as legacy_process, listen, speak, s400_web_search
from JARVIS.input.normalizer import normalize




def _local_sequence(command: str):
    """Execute deterministic multi-step Notepad sequences locally.
    This route is deliberately checked BEFORE standalone save so a sentence
    such as "Notepad kholo, usme Hello World likho, phir usko sev karo"
    cannot be reduced to only Ctrl+S. Gemini is never used here.
    """
    corrected = normalize(command)
    low = re.sub(r"\s+", " ", corrected.lower()).strip()

    # ASR may produce save variants; normalize them here as a second safety net.
    for bad in (" sev ", " seve ", " sve ", " saev ", " savee "):
        low = low.replace(bad, " save ")

    has_notepad = "notepad" in low or "note pad" in low
    has_type = bool(re.search(r"\b(likho|likh|type|write)\b", low))
    has_save = bool(re.search(r"\b(save|save as)\b", low))
    has_sequence = bool(re.search(r"\b(phir|fir|then|aur|ab)\b", low))
    if not (has_notepad and has_type and has_save and has_sequence):
        return None

    try:
        import subprocess, time, pyautogui
        subprocess.Popen(["notepad.exe"])
        time.sleep(1.0)

        # Capture only the payload after the typing verb and before the next step.
        m = re.search(
            r"\b(?:likho|likh|type|write)\b\s+(.*?)(?=\s+\b(?:phir|fir|then|aur|ab)\b|\s+\b(?:save|save as)\b|$)",
            low,
            re.I,
        )
        text_to_type = (m.group(1) if m else "").strip(" ,.!?")
        if text_to_type:
            pyautogui.write(text_to_type, interval=0.02)

        if re.search(r"\bsave\s+as\b", low):
            pyautogui.hotkey("ctrl", "shift", "s")
        else:
            pyautogui.hotkey("ctrl", "s")

        print("JARVIS LOCAL: multi-step Notepad sequence completed. Save shortcut sent. Gemini NOT used.")
        return True
    except Exception as e:
        print("JARVIS LOCAL SEQUENCE ERROR:", e)
        return False

def _local_save(command: str):
    """Handle a standalone save intent locally; never send it to Gemini."""
    corrected = normalize(command)
    low = corrected.lower()
    if any(x in low for x in ('notepad', 'calculator', 'chrome', 'browser')) or any(x in low for x in (' kholo', ' open', ' likho', ' type ')):
        return None
    save_intent = bool(re.search(r'\b(save|save\s+as|save\s+this|save\s+it)\b', low))
    if not save_intent:
        return None
    try:
        import pyautogui
        pyautogui.hotkey('ctrl', 'shift', 's') if 'save as' in low else pyautogui.hotkey('ctrl', 's')
        print('JARVIS LOCAL: save command executed with keyboard shortcut. Gemini NOT used.')
        return True
    except Exception as e:
        print('JARVIS LOCAL SAVE ERROR:', e)
        return False

def _web_first_legacy(command: str):
    """Handle simple current-information searches without invoking Gemini."""
    corrected = normalize(command)
    low = corrected.lower()

    # Deterministic multi-step computer sequences stay local and never call Gemini.
    seq_result = _local_sequence(corrected)
    if seq_result is not None:
        return seq_result

    # Standalone save is also deterministic and local.
    save_result = _local_save(corrected)
    if save_result is not None:
        return save_result

    weather_words = ('weather', 'mausam', 'temperature', 'taapman')
    current_words = ('aaj', 'abhi', 'today', 'current', 'live', 'now')
    if any(w in low for w in weather_words):
        query = re.sub(r'\bjarvis\b', ' ', corrected, flags=re.I)
        query = re.sub(r'\b(batao|bata|batana|kya|hai|hain|ka|ke|ki)\b', ' ', query, flags=re.I)
        query = ' '.join(query.split()) or 'weather today'
        print(f'JARVIS LOCAL-FIRST WEB: searching Google for {query!r}')
        ok = bool(s400_web_search(query, 'google'))
        if ok:
            print('JARVIS: Google par weather search kar diya. Task complete hai.')
        else:
            print('JARVIS: Weather search open nahi ho paya.')
        return ok
    return legacy_process(corrected)


def main():
    print('JARVIS TRUE MEGA ARCHITECTURE 1.4')
    print('Local-first | ASR correction | Save intent | Context | Memory | Router | Safety | Planner | Verifier | Recovery-ready')
    print('Legacy capability engine loaded without auto-startup.')
    app = JarvisApp(_web_first_legacy)
    try:
        speak('Hello Shailendra. I am ready.')
    except Exception as e:
        print('Speech startup warning:', e)

    print('\n======================================')
    print('          JARVIS IS READY')
    print('======================================')
    print('Say: Jarvis')
    print('Text fallback: type a command and press Enter. Type exit to stop.')

    while True:
        try:
            command = listen()
            if not command:
                continue
            print('You:', command)
            normalized = normalize(command)
            print('Normalized:', normalized)
            if normalized in {'exit', 'quit', 'band ho ja', 'jarvis stop'}:
                break
            if 'jarvis' in normalized:
                app.handle(normalized)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print('VOICE ERROR:', e)
            try:
                text = input('You (text fallback): ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in {'exit', 'quit', 'band ho ja', 'jarvis stop'}:
                break
            if text:
                app.handle(text)

    print('JARVIS stopped.')


if __name__ == '__main__':
    main()
