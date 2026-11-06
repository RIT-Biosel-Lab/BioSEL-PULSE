import sys
from pathlib import Path

# pam_metric_analysis uses bare imports (from compute_derived_metrics import ...)
# that only resolve when core/ is on sys.path.  This conftest is loaded by
# pytest before any test module in tests/, regardless of the working directory.
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
