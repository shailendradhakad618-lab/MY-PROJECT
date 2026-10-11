from collections import deque
class Context:
    def __init__(self, limit=20): self.turns=deque(maxlen=limit); self.state={}
    def add(self, user, assistant="", **meta): self.turns.append({"user":user,"assistant":assistant,**meta})
    def snapshot(self): return {"turns":list(self.turns),"state":dict(self.state)}
    def set(self,k,v): self.state[k]=v
    def get(self,k,d=None): return self.state.get(k,d)
