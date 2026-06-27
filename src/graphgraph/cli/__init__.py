from .parser import build_parser
from .commands import *

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

__all__ = ["build_parser", "main"]
