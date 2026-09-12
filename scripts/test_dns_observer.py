from ohana_agent.observation import Observer
from ohana_agent.observation.checks import DNSCheck


def main() -> None:
    observer = Observer()

    checks = [
        DNSCheck(hostname="google.fr", server="192.168.1.11"),
        DNSCheck(hostname="google.fr", server="192.168.1.12"),
    ]

    for check in checks:
        print(f"Running check: {check.description}")

        result = observer.observe(check)

        print(f"  check       : {result.check}")
        print(f"  success     : {result.success}")
        print(f"  latency     : {result.latency} ms")
        print(f"  message     : {result.message}")
        print(f"  metadata    : {result.metadata}")
        print()


if __name__ == "__main__":
    main()
