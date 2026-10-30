"""Atomic IPC for one Codal sync worker.

Files are scoped to a server-generated job directory. This module never reads
browser profiles or emits cookies, URLs, or page HTML to the API client.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
import time
from pathlib import Path


class CodalChallengeError(RuntimeError):
    pass


class JobChannel:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "commands").mkdir(exist_ok=True)
        self.revision = 0
        self.challenge_id: str | None = None
        self.answer: str | None = None
        self.cancelled = False
        self.started = time.time()
        self.captcha_timeout = max(30, int(os.getenv("CODAL_CAPTCHA_TIMEOUT_SECONDS", "600")))
        # A rejected code may be retyped, but the worker never loops on its own:
        # three submitted codes per challenge maximum, then the job stops.
        self.max_captcha_attempts = max(1, int(os.getenv("CODAL_CAPTCHA_MAX_ATTEMPTS", "3")))
        try:
            self.source = os.getenv("CODAL_JOB_SOURCE", "manual")
            self.parameters = json.loads(os.getenv("CODAL_JOB_PARAMETERS", "{}"))
        except json.JSONDecodeError:
            self.source, self.parameters = "manual", {}

    def write_json(self, name: str, value: dict) -> None:
        target = self.root / name
        fd, temp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(value, out, ensure_ascii=False)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def update(self, **values) -> None:
        self.revision += 1
        snap = {"job_id": self.root.name, "source": self.source, "parameters": self.parameters,
                "revision": self.revision, "heartbeat": time.time(), **values}
        self.write_json("status.json", snap)

    def wait_rate_limit(self, retry_at: float, message: str | None = None) -> None:
        status_message = message or "دریافت گزارش‌ها موقتاً محدود شده؛ پس از مهلت دوباره تلاش می‌شود."
        self.update(state="rate_limited", stage="browser", retry_at=retry_at,
                    message=status_message)
        while time.time() < retry_at:
            if self.cancelled:
                raise InterruptedError("Codal sync cancelled")
            for cmd in self.check_commands():
                if cmd.get("type") == "cancel":
                    self.cancelled = True
                    raise InterruptedError("Codal sync cancelled")
            time.sleep(min(0.5, max(0.05, retry_at-time.time())))
            self.update(state="rate_limited", stage="browser", retry_at=retry_at,
                        message=status_message)

    def check_commands(self) -> list[dict]:
        commands_dir = self.root / "commands"
        result = []
        for path in sorted(commands_dir.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            try:
                path.unlink()
            except OSError:
                continue
            if value.get("job_id") == self.root.name:
                result.append(value)
        return result

    @staticmethod
    def _write_image(path: Path, image: bytes) -> str:
        """Publish a challenge picture: element shots are PNG, page shots JPEG."""
        if image.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "png"
        elif image.startswith(b"\xff\xd8"):
            mime = "jpeg"
        else:
            raise ValueError("Challenge screenshot must be PNG or JPEG")
        if len(image) > 2_000_000:
            raise ValueError("Challenge screenshot must stay under 2 MB")
        path.write_bytes(image)
        return f"data:image/{mime};base64," + base64.b64encode(image).decode("ascii")

    @staticmethod
    def _valid_captcha_image(value: str | None) -> str | None:
        """Accept Codal's own captcha image (it is served as JPEG, not PNG)."""
        if not isinstance(value, str) or not value.startswith("data:image/"):
            return None
        if ";base64," not in value or len(value) > 2_000_000:
            return None
        return value

    def wait_for_challenge(self, page, image_locator=None, *, kind="unsupported", message=None,
                           refresh_locator=None, is_resolved=None, image_data_url=None,
                           verify_answer=None, refresh_image=None) -> None:
        """Show the challenge panel and wait for the operator.

        Two answer paths exist:

        * ``verify_answer`` (preferred): the code is submitted through Codal's own
          captcha API in the page context, so the operator types it **in the app**
          instead of hunting for the field in Chromium.
        * otherwise the challenge form controls are discovered from the live DOM.

        ``image_data_url`` lets the caller publish Codal's real captcha image
        (a small JPEG) instead of a screenshot of the whole page.

        ``is_resolved`` is polled roughly once a second. When it returns True
        (for example the operator solved Codal's own security modal in the
        opened page), the wait ends without needing the «ادامه» button.
        """
        attempts = 0
        last_resolution_check = 0.0
        current_image = self._valid_captcha_image(image_data_url)
        while attempts < self.max_captcha_attempts:
            if self.cancelled:
                raise InterruptedError("Codal sync cancelled")
            if current_image is None:
                if image_locator is not None:
                    image = image_locator.screenshot(type="png", timeout=3000)
                else:
                    # A page shot only needs to be readable by the operator; JPEG
                    # keeps the polling payload small while the panel is open.
                    image = page.screenshot(type="jpeg", quality=55, full_page=False, timeout=5000)
                current_image = self._write_image(self.root / "challenge.img", image)
            challenge_id = secrets.token_urlsafe(18)
            now = time.time()
            self.challenge_id = challenge_id
            self.answer = None
            expires = now + self.captcha_timeout
            payload = {
                "challenge_id": challenge_id,
                "kind": kind,
                "image_data_url": current_image,
                "created_at": now,
                "expires_at": expires,
                "attempt": attempts + 1,
                "message": message or "کدال برای ادامه کد امنیتی می‌خواهد. کد تصویر را وارد کنید.",
                "can_refresh": refresh_image is not None or refresh_locator is not None,
                "can_manual_resume": kind == "inspection" or os.getenv("CODAL_BROWSER_HEADLESS", "0") == "0",
            }
            self.write_json("challenge.json", payload)
            self.update(state="waiting_captcha", stage="captcha", message=payload["message"],
                        challenge=payload)

            refresh = False
            resume = False
            while time.time() < expires:
                for cmd in self.check_commands():
                    if cmd.get("type") == "cancel":
                        self.cancelled = True
                        raise InterruptedError("Codal sync cancelled")
                    if cmd.get("challenge_id") != challenge_id:
                        continue
                    if cmd.get("type") == "refresh":
                        if refresh_image is not None:
                            fresh = self._valid_captcha_image(refresh_image())
                            if fresh:
                                current_image = fresh
                                refresh = True
                            break
                        if refresh_locator is not None:
                            refresh_locator.click(timeout=3000)
                            page.wait_for_timeout(500)
                            current_image = None
                            refresh = True
                        break
                    if cmd.get("type") == "resume" and payload["can_manual_resume"]:
                        resume = True
                        break
                    if cmd.get("type") == "answer" and self.answer is None:
                        value = str(cmd.get("answer") or "").strip()
                        if value:
                            self.answer = value
                if refresh or resume or self.answer is not None:
                    break
                if is_resolved is not None and time.time() - last_resolution_check >= 1.0:
                    last_resolution_check = time.time()
                    try:
                        if is_resolved():
                            return
                    except Exception:
                        pass
                time.sleep(0.25)

            if time.time() >= expires:
                self.update(state="expired", stage="captcha", error={"code": "captcha_timeout",
                            "message": "زمان واردکردن کد امنیتی به پایان رسید."})
                raise TimeoutError("Codal captcha expired")
            if refresh:
                continue
            if resume:
                return

            if verify_answer is not None:
                # One submitted code per challenge; a rejected code publishes a
                # fresh image and waits again instead of retrying the feed.
                try:
                    accepted = bool(verify_answer(self.answer))
                except Exception:
                    accepted = False
                attempts += 1
                if accepted:
                    return
                if attempts >= self.max_captcha_attempts:
                    break
                if refresh_image is not None:
                    fresh = self._valid_captcha_image(refresh_image())
                    if fresh:
                        current_image = fresh
                continue

            # Challenge form controls are discovered from the live DOM. Only
            # exactly one visible text input is accepted; no Codal selector is guessed.
            fields = page.locator("input:visible")
            text_fields = []
            for i in range(min(fields.count(), 12)):
                field = fields.nth(i)
                typ = (field.get_attribute("type") or "text").lower()
                if typ in ("text", "tel", "number") and field.is_enabled():
                    text_fields.append(field)
            if len(text_fields) != 1:
                self.update(state="failed", stage="captcha", error={"code": "unsupported_challenge",
                            "message": "ساختار فرم کدال برای ارسال خودکار از UI شناخته نشد."})
                raise CodalChallengeError("unsupported Codal challenge form")
            text_fields[0].fill(self.answer)
            submit_candidates = page.locator("button:visible:not([type=button]), input[type=submit]:visible")
            buttons = [submit_candidates.nth(i) for i in range(min(submit_candidates.count(), 12))]
            buttons = [b for b in buttons if b.is_enabled()]
            if len(buttons) != 1:
                self.update(state="failed", stage="captcha", error={"code": "unsupported_challenge",
                            "message": "دکمهٔ ارسال کد در صفحهٔ کدال به‌طور یکتا شناسایی نشد."})
                raise CodalChallengeError("unsupported Codal challenge submit")
            buttons[0].click()
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            page.wait_for_timeout(500)
            # A still-visible challenge means the submitted answer was rejected.
            try:
                still_present = page.locator("input:visible").count() > 0 and page.locator("img:visible,canvas:visible").count() > 0
            except Exception:
                still_present = False
            if still_present:
                attempts += 1
                continue
            # The transport rechecks the original target after this returns.
            return
        raise CodalChallengeError("maximum Codal captcha attempts reached")


_channel: JobChannel | None = None


def current_channel() -> JobChannel | None:
    global _channel
    path = os.getenv("CODAL_JOB_DIR")
    if not path:
        _channel = None
        return None
    if _channel is None or _channel.root != Path(path).resolve():
        _channel = JobChannel(path)
    return _channel
