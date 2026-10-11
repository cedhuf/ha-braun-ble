import sys
import types
from pathlib import Path

# Load the protocol modules without running __init__.py, which needs Home Assistant.
package = types.ModuleType("ha_braun_ble")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "ha_braun_ble")]
sys.modules["ha_braun_ble"] = package
