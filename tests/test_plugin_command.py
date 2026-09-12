import pytest

from ohana_agent.plugins.runtime.plugin_command import PluginCommand


def test_plugin_command_contains_execution_context() -> None:
    command = PluginCommand(
        plugin_name="dns",
        operation="resolve",
        target_name="dns",
        arguments={
            "hostname": "example.com",
        },
    )

    assert command.plugin_name == "dns"
    assert command.operation == "resolve"
    assert command.target_name == "dns"
    assert command.arguments == {
        "hostname": "example.com",
    }


def test_plugin_command_builds_canonical_source() -> None:
    command = PluginCommand(
        plugin_name="dns",
        operation="resolve",
        target_name="dns",
    )

    assert command.source == "dns.resolve"


def test_plugin_command_has_empty_arguments_by_default() -> None:
    command = PluginCommand(
        plugin_name="dns",
        operation="resolve",
        target_name="dns",
    )

    assert command.arguments == {}


@pytest.mark.parametrize(
    ("field_name", "values"),
    [
        ("plugin_name", ("", "   ")),
        ("operation", ("", "   ")),
        ("target_name", ("", "   ")),
    ],
)
def test_plugin_command_rejects_empty_required_fields(
    field_name: str,
    values: tuple[str, str],
) -> None:
    for value in values:
        arguments = {
            "plugin_name": "dns",
            "operation": "resolve",
            "target_name": "dns",
        }
        arguments[field_name] = value

        with pytest.raises(ValueError):
            PluginCommand(**arguments)
