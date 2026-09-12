"""Compatibility wrapper for the installed Freebox authorization command."""

from ohana_agent.plugins.wireguard.authorize_freebox import main

if __name__ == "__main__":
    raise SystemExit(main())
