from .system import open_app,press_key,type_text,save_document,save_as_document
from .browser import web_search,open_url
from .files import list_files
def build_registry():
 return {"open_app":open_app,"press_key":press_key,"type_text":type_text,"save":save_document,"save_as":save_as_document,"web_search":web_search,"open_url":open_url,"list_files":list_files}
