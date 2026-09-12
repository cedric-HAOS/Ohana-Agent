"""Dependency-free entry point for the restricted DHCP reload helper.

The package initializers stay free of application imports, so systemd can
load this helper without Pydantic while the Agent environment is replaced.
"""

from ohana_agent.host.dhcp_reload_helper import main

if __name__ == "__main__":
    raise SystemExit(main())
