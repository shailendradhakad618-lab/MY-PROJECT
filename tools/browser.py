import webbrowser
def web_search(query): webbrowser.open('https://www.google.com/search?q='+webbrowser.quote(query) if hasattr(webbrowser,'quote') else 'https://www.google.com/search?q='+str(query).replace(' ','+')); return True
def open_url(url): webbrowser.open(url); return True
