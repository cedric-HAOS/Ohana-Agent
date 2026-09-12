from ohana_agent.infrastructure import Endpoint, EndpointType


def test_endpoint_can_be_created() -> None:
    endpoint = Endpoint(type=EndpointType.IP, address="192.168.1.10", port=53)

    assert endpoint.type is EndpointType.IP
    assert endpoint.address == "192.168.1.10"
    assert endpoint.port == 53
    assert endpoint.enabled is True


def test_endpoint_can_be_disabled() -> None:
    endpoint = Endpoint(type=EndpointType.HOSTNAME, address="dns.local", enabled=False)

    assert endpoint.is_enabled() is False


def test_endpoint_has_empty_metadata_by_default() -> None:
    endpoint = Endpoint(type=EndpointType.URL, address="https://ha.local")

    assert endpoint.metadata == {}
