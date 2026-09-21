"""Regression tests for Tsunade evidence redaction."""

from ohana_agent.tsunade.evidence_privacy import (
    REDACTED,
    redact_sensitive_text,
    redact_sensitive_value,
)


def test_sensitive_text_keeps_context_without_credentials() -> None:
    value = (
        "Backup failed on "
        "https://operator:fictional-password@example.test/path"
        "?access_token=fake-access&mode=check "
        "Authorization: Bearer fake-bearer-token "
        "password=fake-password "
        "/stok=fake-session/"
    )

    redacted = redact_sensitive_text(value)

    for secret in (
        "fictional-password",
        "fake-access",
        "fake-bearer-token",
        "fake-password",
        "fake-session",
    ):
        assert secret not in redacted

    assert "example.test/path" in redacted
    assert "mode=check" in redacted
    assert REDACTED in redacted


def test_structured_evidence_redacts_sensitive_keys_recursively() -> None:
    value = {
        "status": "FAILED",
        "worker_token": "fake-worker-token",
        "nested": {
            "password": "fake-password",
            "url": (
                "mqtt://operator:fake-mqtt-password@broker.test:1883"
                "?api_key=fake-api-key"
            ),
        },
        "token_file": "/etc/ohana-agent/worker.token",
    }

    redacted = redact_sensitive_value(value)

    assert redacted["status"] == "FAILED"
    assert redacted["worker_token"] == REDACTED
    assert redacted["nested"]["password"] == REDACTED

    rendered = str(redacted)

    for secret in (
        "fake-worker-token",
        "fake-password",
        "fake-mqtt-password",
        "fake-api-key",
    ):
        assert secret not in rendered

    # A path to a token file is not itself the token.
    assert redacted["token_file"] == "/etc/ohana-agent/worker.token"
