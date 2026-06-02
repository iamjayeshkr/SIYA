from vani.services.wake import is_wake_command


def test_wake_command_accepts_common_phrases():
    assert is_wake_command("wake up vani")
    assert is_wake_command("Wake up, Vani!")
    assert is_wake_command("vani ko activate kar do")
    assert is_wake_command("hey vani")
    assert is_wake_command("vani sun")
    assert is_wake_command("utho vani")


def test_wake_command_rejects_normal_messages():
    assert not is_wake_command("vani kal ka weather bata")
    assert not is_wake_command("activate bluetooth")
