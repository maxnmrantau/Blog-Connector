import sys
import os

# Pastikan root project masuk ke sys.path agar modul 'app' bisa diimpor di Vercel
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)

from app.main import app  # noqa: E402, F401
