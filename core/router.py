from .safety import is_risky
from .planner import Planner
from JARVIS.input.normalizer import normalize
class Router:
 def __init__(self,legacy,parser,gemini=None):
  self.legacy=legacy;self.parser=parser;self.gemini=gemini;self.planner=Planner();self.app_state=None
 def route(self,text):
  c=normalize(text); intent=self.parser(c)
  plan=self.planner.plan(c,intent)
  if plan.actions and self.app_state:
   print("JARVIS 1.5 PLAN:",[(a.tool,a.args) for a in plan.actions])
   ok,res=self.app_state.executor.run(plan)
   if ok:
    print("JARVIS 1.5: MULTI-TASK COMPLETE — Gemini NOT used.");return True
   print("JARVIS 1.5: local plan failed; compatibility recovery.")
  if intent.needs_ai and self.gemini and self.gemini.available():
   ans=self.gemini.ask(c)
   if ans:print("JARVIS:",ans);return True
  return bool(self.legacy(c))
