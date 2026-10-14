"""Compatibility entry point; use benchmark.py broker for approved capture sessions."""
from benchmark import main
if __name__=='__main__':raise SystemExit(main(['broker']))
