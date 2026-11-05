"""Environment for child processes in offline tests; no real credentials."""
import os


def fixture_environment():
    allowed = ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "HOME",
               "PATHEXT", "COMSPEC", "APPDATA", "LOCALAPPDATA")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment
