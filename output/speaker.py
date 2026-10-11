import queue,threading
class Speaker:
    def __init__(self): self.q=queue.Queue(); self.thread=threading.Thread(target=self._worker,daemon=True); self.thread.start()
    def say(self,text): self.q.put(str(text))
    def _worker(self):
        while True:
            text=self.q.get()
            try:
                import pyttsx3; e=pyttsx3.init(); e.say(text); e.runAndWait()
            except Exception: print('JARVIS:',text)
