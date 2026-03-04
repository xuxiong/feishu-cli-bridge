from app.command_router import ParsedCommand, parse_command


def test_logs_command_accepts_slash_prefix() -> None:
    assert parse_command("/logs job-abc123") == ParsedCommand(
        action="logs", job_id="job-abc123"
    )


def test_logs_command_accepts_plain_text() -> None:
    assert parse_command("logs job-abc123") == ParsedCommand(
        action="logs", job_id="job-abc123"
    )


def test_cancel_command_accepts_plain_text() -> None:
    assert parse_command("cancel job-abc123") == ParsedCommand(
        action="cancel", job_id="job-abc123"
    )
