"""In-site captcha answer path: Codal's own image + verification, no browser clicking."""
import json
import threading
import time

import pytest

import codal_challenge


def _submit_when_published(root, answers, stop_after):
    """Operator stand-in: answer each newly published challenge from the UI."""
    last = None
    index = 0
    deadline = time.time() + 15
    while time.time() < deadline and index < len(answers):
        path = root / "challenge.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["challenge_id"] != last:
                last = payload["challenge_id"]
                command = {
                    "type": "answer",
                    "job_id": root.name,
                    "challenge_id": last,
                    "command_id": f"ui-{index}",
                    "answer": answers[index],
                }
                (root / "commands" / f"ui-{index}.json").write_text(
                    json.dumps(command), encoding="utf-8")
                index += 1
                if index >= stop_after:
                    return
        time.sleep(0.05)


@pytest.fixture
def channel(tmp_path, monkeypatch):
    root = tmp_path / ("b" * 32)
    root.mkdir()
    monkeypatch.setenv("CODAL_JOB_DIR", str(root))
    monkeypatch.setenv("CODAL_CAPTCHA_TIMEOUT_SECONDS", "20")
    monkeypatch.delenv("CODAL_CAPTCHA_MAX_ATTEMPTS", raising=False)
    return codal_challenge.JobChannel(root), root


def test_codal_jpeg_captcha_image_is_published_as_is(channel):
    ch, root = channel
    image = "data:image/jpeg;base64," + "QUJD" * 20
    threading.Thread(target=_submit_when_published, args=(root, ["ABCD"], 1), daemon=True).start()
    ch.wait_for_challenge(None, kind="text", image_data_url=image, verify_answer=lambda code: True)
    payload = json.loads((root / "challenge.json").read_text(encoding="utf-8"))
    assert payload["image_data_url"] == image
    assert payload["kind"] == "text"


def test_rejected_code_republishes_and_second_code_is_accepted(channel):
    ch, root = channel
    seen = []

    def verify(code):
        seen.append(code)
        return code == "ABCD"

    threading.Thread(target=_submit_when_published, args=(root, ["WRONG", "ABCD"], 2), daemon=True).start()
    ch.wait_for_challenge(None, kind="text",
                          image_data_url="data:image/jpeg;base64,QUJD",
                          verify_answer=verify)
    assert seen == ["WRONG", "ABCD"]


def test_three_rejected_codes_stop_instead_of_looping(channel):
    ch, root = channel
    calls = []

    def verify(code):
        calls.append(code)
        return False

    threading.Thread(
        target=_submit_when_published,
        args=(root, ["AAA", "BBB", "CCC", "DDD"], 4),
        daemon=True,
    ).start()
    with pytest.raises(codal_challenge.CodalChallengeError):
        ch.wait_for_challenge(None, kind="text",
                              image_data_url="data:image/jpeg;base64,QUJD",
                              verify_answer=verify)
    assert calls == ["AAA", "BBB", "CCC"]
