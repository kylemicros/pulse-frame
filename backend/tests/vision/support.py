from pulse_frame.vision.errors import VisionError, VisionErrorCode


def assert_coded(error: VisionError, code: VisionErrorCode) -> None:
    assert error.code == code
    assert error.message
    assert error.action
