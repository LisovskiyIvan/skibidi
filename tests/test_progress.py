"""Tests for progress formatting."""

from video_processor.progress import Step, default_message


class TestDefaultMessage:
    def test_done_message(self) -> None:
        assert default_message(Step.DONE, 5, 5, "anything") == "Done. Total segments: 5."

    def test_step_message_is_one_indexed(self) -> None:
        msg = default_message(Step.BURN, 0, 4, "burning clip_00.mp4")
        assert msg == "[1/4] burn: burning clip_00.mp4"

    def test_includes_step_value(self) -> None:
        msg = default_message(Step.TRANSCRIBE, 2, 3, "words")
        assert "transcribe" in msg
        assert "[3/3]" in msg
