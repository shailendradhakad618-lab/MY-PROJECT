from JARVIS.input.normalizer import normalize
from JARVIS.core.models import Intent

WEB = ('weather','latest','today','aaj','abhi','current','live','news','price','stock','score','online','internet','search online')
AI = ('gemini','deep analysis','deeply analyse','deeply analyze','complex reasoning','architecture analyze','architecture analysis','code analyze','code analysis','reason deeply')
LOCAL = ('calculator','calc','notepad','chrome','browser','explorer','file explorer','settings','terminal','command prompt','downloads','desktop','volume','mute','unmute','screenshot','screen','clipboard','scroll','stop','band karo','band ho ja','open','kholo','karo','type','press')
CONVERSATION = ('hello','hi','hey','namaste','kaise ho','how are you','good morning','good night','thanks','thank you','shukriya','who are you','tum kaun ho','your name','naam kya')

def parse(text):
    s=normalize(text)
    needs_ai=any(x in s for x in AI)
    needs_web=any(x in s for x in WEB)
    is_local=any(x in s for x in LOCAL)
    is_chat=any(x in s for x in CONVERSATION)
    # Explicit/complex AI wins. Otherwise, a current-information request is web.
    # Local commands remain local even if a generic word like "search" appears.
    if needs_ai:
        name='natural_language'
    elif is_local and not needs_ai:
        name='local'
        needs_web=False if not any(x in s for x in ('weather','news','price','stock','score','latest','today','current','live')) else needs_web
    elif is_chat and not needs_web:
        name='conversation'
    else:
        name='natural_language'
    return Intent(name=name, confidence=.95 if (is_local or is_chat) else .82,
                  needs_web=needs_web, needs_ai=needs_ai)
