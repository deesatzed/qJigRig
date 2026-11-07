"""T001: importing qjig must not read config, open sockets, or create data."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

PROBE = textwrap.dedent(
    """
    import json, sys
    events = []
    def hook(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
            events.append([event, repr(args)])
        elif event == "open":
            path, mode = args[0], args[1] or "r"
            path = str(path)
            writing = any(c in mode for c in "wax+")
            code = path.endswith((".py", ".pyc", ".so", ".pyd"))
            if writing or not code:
                events.append([event, path, mode])
        elif event in ("os.mkdir", "os.remove", "os.rename", "os.rmdir"):
            events.append([event, repr(args)])
    sys.addaudithook(hook)
    sys.dont_write_bytecode = True
    import qjig
    sys.stdout.write(json.dumps({"events": events, "name": qjig.__name__}))
    """
)


def test_import_has_no_io(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=tmp_path,
        env={"PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["name"] == "qjig"
    assert report["events"] == []
    assert list(tmp_path.iterdir()) == []
