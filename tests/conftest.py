"""Make the tests/ directory importable so test modules can import sibling helpers
(``verifier_check``, ``itsm_oracle``) regardless of pytest's import mode."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
