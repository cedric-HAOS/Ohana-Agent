from ohana_agent.core import Executor


class StringExecutor:
    def execute(self, item: str) -> str:
        return item.upper()


def test_executor_protocol_accepts_matching_class() -> None:
    executor: Executor[str, str] = StringExecutor()

    assert executor.execute("ohana") == "OHANA"
