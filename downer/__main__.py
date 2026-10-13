"""Allow running as `python -m downer`."""
import sys

from downer.main import main

if __name__ == "__main__":
    sys.exit(main())