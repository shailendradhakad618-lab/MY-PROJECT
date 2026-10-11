import re
from difflib import SequenceMatcher

# Common ASR/phonetic variants. The correction is intentionally conservative:
# only words that are close to known command vocabulary are changed.
ALIASES = {
    'veder': 'weather', 'vedar': 'weather', 'vedea': 'weather', 'vederh': 'weather', 'weder': 'weather', 'wether': 'weather', 'weater': 'weather', 'weader': 'weather', 'weathar': 'weather', 'wather': 'weather', 'whether': 'weather',
    'crome': 'chrome', 'gugal': 'google', 'not pad': 'notepad', 'note pad': 'notepad',
    'calcu': 'calculator', 'calc': 'calculator', 'calcutor': 'calculator',
    'calculater': 'calculator', 'calclator': 'calculator',
    'yutube': 'youtube', 'utube': 'youtube', 'you tube': 'youtube',
    'exporer': 'explorer', 'explorrer': 'explorer', 'file exporer': 'file explorer',
    'seting': 'settings', 'setting': 'settings', 'dowloads': 'downloads',
    'desk top': 'desktop', 'scren': 'screen', 'scrren': 'screen',
    'volum': 'volume', 'mut': 'mute', 'unmut': 'unmute',
    'searh': 'search', 'serch': 'search', 'sarch': 'search',
    'kolo': 'kholo', 'khol': 'kholo', 'khul': 'kholo',
    'btao': 'batao', 'bata': 'batao', 'bta': 'batao',
    'krdo': 'karo', 'kardo': 'karo', 'kar do': 'karo',
    'sev': 'save', 'seve': 'save', 'sve': 'save', 'saev': 'save', 'savee': 'save', 'saver': 'save',
    'sew': 'save', 'saye': 'save', 'sayv': 'save', 'seve kar': 'save karo', 'sev kar': 'save karo',
}

VOCAB = {
    'weather','chrome','google','notepad','calculator','youtube','explorer','settings',
    'downloads','desktop','screen','volume','mute','unmute','save','search','browser','open',
    'kholo','karo','batao','news','price','stock','score','today','latest','current','live'
}

def _token_fix(token):
    if token in ALIASES:
        return ALIASES[token]
    if len(token) < 4:
        return token
    best, score = None, 0.0
    for word in VOCAB:
        ratio = SequenceMatcher(None, token, word).ratio()
        if ratio > score:
            best, score = word, ratio
    # Conservative fuzzy correction. Short words require a stronger match.
    threshold = 0.82 if len(token) <= 5 else 0.76
    return best if best and score >= threshold else token

def normalize(text):
    s = ' '.join(str(text or '').strip().lower().split())
    # Phrase aliases first.
    for a, b in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(r'(?<!\w)' + re.escape(a) + r'(?!\w)', b, s)
    # Then conservative word-level fuzzy correction.
    s = ' '.join(_token_fix(tok) for tok in s.split())
    return s
