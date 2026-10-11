from .router import Router
from .context import Context
from .memory import Memory
from .verifier import Verifier
from .executor import Executor
from .logger import log
from JARVIS.config import DB_PATH
from JARVIS.ai.intent_parser import parse
from JARVIS.ai.gemini_client import GeminiClient
from JARVIS.tools.registry import build_registry
class JarvisApp:
    def __init__(self,legacy):
        self.context=Context(); self.memory=Memory(DB_PATH); self.verifier=Verifier(); self.executor=Executor(build_registry(),self.verifier); self.router=Router(legacy,parse,GeminiClient())
        self.router.app_state=self
    def handle(self,text):
        self.context.add(text); self.memory.put('conversation','turn',{'user':text}); return self.router.route(text)
