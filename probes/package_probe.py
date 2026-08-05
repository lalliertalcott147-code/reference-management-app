from __future__ import annotations

import json
import sys


def main() -> int:
    print(json.dumps({"app": "Catalyst Literature", "probe": "ok"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
