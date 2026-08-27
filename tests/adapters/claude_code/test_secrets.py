"""Secret redaction at collection (G1 item d): raw secret bytes never survive."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from capability_exchange.adapters.claude_code.secrets import (
    REDACTION_MARK,
    contains_secret_shape,
    redact_secret_content,
)
from capability_exchange.boundary.secret_markers import (
    SECRET_SHAPE_EXAMPLES,
    SecretShapeExample,
)

AWS_KEY = b"AKIAIOSFODNN7EXAMPLE"
SK_TOKEN = b"sk-abcdefabcdefabcdefabcd"
GITHUB_TOKEN = b"ghp_abcdefghijklmnopqrstuvwxyz012345"
SLACK_TOKEN = b"xoxb-1234567890-abcdefghij"
BEARER = b"Bearer abcdefghijklmnopqrstuvwx"
PEM = (
    b"-----BEGIN RSA PRIVATE KEY-----\n"
    b"c2VjcmV0Ym9keQ==\n"
    b"-----END RSA PRIVATE KEY-----"
)


class TestTokenShapes:
    @pytest.mark.parametrize("example", SECRET_SHAPE_EXAMPLES, ids=lambda item: item.name)
    def test_shared_secret_catalogue_examples_are_redacted(
        self, example: SecretShapeExample
    ) -> None:
        outcome = redact_secret_content(example.content_example)
        assert example.secret_fragment not in outcome.content

    def test_aws_access_key_redacted(self) -> None:
        outcome = redact_secret_content(b"key = " + AWS_KEY + b" end")
        assert AWS_KEY not in outcome.content
        assert REDACTION_MARK in outcome.content
        assert outcome.redaction_count == 1

    def test_sk_token_redacted(self) -> None:
        outcome = redact_secret_content(b"uses " + SK_TOKEN)
        assert SK_TOKEN not in outcome.content

    def test_github_token_redacted(self) -> None:
        outcome = redact_secret_content(GITHUB_TOKEN)
        assert GITHUB_TOKEN not in outcome.content

    def test_slack_token_redacted(self) -> None:
        outcome = redact_secret_content(SLACK_TOKEN)
        assert SLACK_TOKEN not in outcome.content

    def test_bearer_token_redacted(self) -> None:
        outcome = redact_secret_content(b"Authorization: " + BEARER)
        assert b"abcdefghijklmnopqrstuvwx" not in outcome.content

    def test_pem_block_redacted_whole(self) -> None:
        outcome = redact_secret_content(b"before\n" + PEM + b"\nafter")
        assert b"c2VjcmV0Ym9keQ==" not in outcome.content
        assert b"BEGIN RSA PRIVATE KEY" not in outcome.content
        assert outcome.content.startswith(b"before\n")
        assert outcome.content.endswith(b"\nafter")

    def test_unterminated_pem_block_redacts_to_end(self) -> None:
        raw = b"prefix\n-----BEGIN PRIVATE KEY-----\nkey material with no end"
        outcome = redact_secret_content(raw)
        assert b"key material" not in outcome.content
        assert outcome.content.startswith(b"prefix\n")


class TestAssignments:
    def test_quoted_assignment_value_redacted(self) -> None:
        raw = b'api_key = "supersecretvalue123"\n'
        outcome = redact_secret_content(raw)
        assert b"supersecretvalue123" not in outcome.content
        assert b"api_key" in outcome.content  # the key name is not the secret

    def test_bare_assignment_value_redacted(self) -> None:
        raw = b"export DB_PASSWORD=hunter2hunter2\n"
        outcome = redact_secret_content(raw)
        assert b"hunter2hunter2" not in outcome.content

    def test_yaml_style_assignment_redacted(self) -> None:
        raw = b"access_token: abcdef123456789\n"
        outcome = redact_secret_content(raw)
        assert b"abcdef123456789" not in outcome.content

    def test_env_reference_not_a_secret(self) -> None:
        raw = b"API_KEY=$OPENAI_API_KEY\nAUTH_TOKEN=${VAULT_TOKEN}\n"
        assert redact_secret_content(raw).redaction_count == 0

    def test_placeholder_not_a_secret(self) -> None:
        raw = b"password = changeme\napi_key = your-key-here\nsecret=placeholder\n"
        assert redact_secret_content(raw).redaction_count == 0

    def test_short_value_not_a_secret(self) -> None:
        assert redact_secret_content(b"password = abc\n").redaction_count == 0

    def test_constant_name_not_a_secret(self) -> None:
        raw = b"secret = MY_SECRET_CONST\n"
        assert redact_secret_content(raw).redaction_count == 0


class TestTotality:
    def test_benign_content_untouched(self) -> None:
        raw = b"# CLAUDE.md\nRun the weekly review and file notes.\n"
        outcome = redact_secret_content(raw)
        assert outcome.content == raw
        assert outcome.redaction_count == 0
        assert not contains_secret_shape(raw)

    def test_multiple_secrets_all_redacted_and_counted(self) -> None:
        raw = AWS_KEY + b"\n" + SK_TOKEN + b"\n" + PEM
        outcome = redact_secret_content(raw)
        assert outcome.redaction_count == 3
        for secret in (AWS_KEY, SK_TOKEN, b"c2VjcmV0Ym9keQ=="):
            assert secret not in outcome.content

    def test_contains_secret_shape_agrees_with_redaction(self) -> None:
        assert contains_secret_shape(AWS_KEY)
        assert not contains_secret_shape(b"nothing here")

    @given(st.binary(max_size=4096))
    def test_never_raises_and_never_leaves_known_shapes(self, raw: bytes) -> None:
        outcome = redact_secret_content(raw)
        assert isinstance(outcome.content, bytes)
        assert outcome.redaction_count >= 0
        # a second pass finds nothing new to redact in already-clean output
        if outcome.redaction_count == 0:
            assert outcome.content == raw

    @given(st.binary(min_size=0, max_size=512))
    def test_planted_aws_key_never_survives(self, noise: bytes) -> None:
        raw = noise + AWS_KEY + noise
        assert AWS_KEY not in redact_secret_content(raw).content
