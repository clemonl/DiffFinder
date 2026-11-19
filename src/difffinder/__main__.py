from .selfcheck import selfcheck

raise SystemExit(0 if selfcheck() else 1)
