from security import protect_secret, redact, reveal_secret

def test_secret_round_trip():
    original = "example-password"
    protected = protect_secret(original)
    assert reveal_secret(protected) == original
    if protected != original:
        assert original not in protected

def test_redact_nested_secrets():
    value = {"access_token": "abcdefghijklmnopqrstuvwxyz", "nested": {"password": "secret"}, "ok": 3}
    redacted = redact(value)
    assert redacted["access_token"] != value["access_token"]
    assert redacted["nested"]["password"] == "***"
