import subprocess,time
APPS={"calculator":"calc.exe","notepad":"notepad.exe","chrome":"chrome.exe","explorer":"explorer.exe"}
def open_app(name):
 subprocess.Popen(APPS.get(str(name).lower(),str(name)),shell=True);time.sleep(.8);return True
def press_key(key):
 import pyautogui
 k=str(key).lower().replace("control","ctrl").replace("return","enter")
 pyautogui.hotkey(*k.split("+")) if "+" in k else pyautogui.press(k)
 return True
def type_text(text):
 import pyautogui
 pyautogui.write(str(text),interval=.02);return True
def save_document():return press_key("ctrl+s")
def save_as_document():return press_key("ctrl+shift+s")
