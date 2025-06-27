import os
from fastapi.templating import Jinja2Templates
from markdown import markdown as md_lib

def markdown_filter(text):
    return md_lib(text or "")

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters['markdown'] = markdown_filter
