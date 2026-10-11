from .safety import allowed_action

class Executor:
    def __init__(self, registry, verifier):
        self.registry = registry
        self.verifier = verifier

    def run(self, plan):
        out = []
        for a in plan.actions:
            if not allowed_action(a.tool):
                return False, out
            fn = self.registry.get(a.tool)
            if not fn:
                return False, out
            try:
                r = fn(**a.args)
            except Exception as e:
                r = {"success": False, "error": str(e)}
            out.append(r)
            vr = self.verifier.verify(action=a, result=r)
            if not vr.success:
                return False, out
        return True, out
