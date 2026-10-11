import os
class GeminiClient:
    def __init__(self): self.api_key=os.getenv('GEMINI_API_KEY','')
    def available(self): return bool(self.api_key)
    def ask(self,prompt):
        if not self.api_key: return None
        try:
            from google import genai
            client=genai.Client(api_key=self.api_key)
            r=client.models.generate_content(model=os.getenv('GEMINI_MODEL','gemini-2.5-flash'),contents=prompt)
            return getattr(r,'text',None)
        except Exception: return None
