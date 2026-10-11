import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1].parent))
from JARVIS.ai.intent_parser import parse
from JARVIS.input.normalizer import normalize
def test_normalize(): assert normalize('note pad kholo')=='notepad kholo'
def test_web(): assert parse('aaj ka weather batao').needs_web
def test_ai(): assert parse('code ko deeply analyze karo').needs_ai
