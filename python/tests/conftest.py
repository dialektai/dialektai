"""pytest configuration for dialekt smoke tests."""
import sys
from pathlib import Path

# Ensure server.py is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
