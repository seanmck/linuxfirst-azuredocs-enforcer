import sys
import os
# Allow running as a script from project root or webui/
if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    try:
        from db import init_db
    except ImportError:
        # If run from project root
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from webui.db import init_db
    init_db()
