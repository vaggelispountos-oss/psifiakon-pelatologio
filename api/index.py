import sys
from pathlib import Path

# Add backend to path so we can import the Flask app
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app import create_app

app = create_app()
