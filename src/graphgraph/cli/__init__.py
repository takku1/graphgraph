from .commands import *
from .parser import build_parser


def _configure_stdio() -> None:
    """Keep CLI packet output from crashing on narrow Windows code pages."""
    import sys

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


def main() -> None:
    import sys

    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

__all__ = ["build_parser", "main", "_configure_stdio"]
