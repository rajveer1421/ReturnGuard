import os
import sys
import tempfile
from pathlib import Path

# isolate every test run from the real data/ folder, before returnguard.config is imported
os.environ["RG_DATA_DIR"] = tempfile.mkdtemp(prefix="rg-test-")
os.environ["RG_CACHE_DIR"] = tempfile.mkdtemp(prefix="rg-cache-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
