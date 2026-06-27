"""Put the backend dir on sys.path so `import app` resolves when pytest runs
from the repo root (mirrors how uvicorn is launched from backend/)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
