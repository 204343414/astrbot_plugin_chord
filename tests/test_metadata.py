"""Plugin metadata must agree with itself.

The version lives in two places -- metadata.yaml and the @register call -- and
nothing enforced that they matched. They drifted three feature releases apart
(0.1.0 in the manifest, a plugin with three sub-pages in reality), which makes
"which version is the user running?" unanswerable exactly when it matters.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _manifest_version():
    text = (ROOT / "metadata.yaml").read_text("utf-8")
    match = re.search(r'^version:\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "metadata.yaml 缺少 version"
    return match.group(1)


def _register_version():
    """Pulled out of the source with a regex: importing main.py needs the
    whole AstrBot runtime, which is not available to a unit test."""
    import ast

    tree = ast.parse((ROOT / "main.py").read_text("utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name != "register":
            continue
        strings = [a.value for a in node.args if isinstance(a, ast.Constant)
                   and isinstance(a.value, str)]
        for value in strings:
            if re.fullmatch(r"\d+\.\d+\.\d+", value):
                return value
    raise AssertionError("main.py 的 @register 里找不到版本号")


def test_the_manifest_and_the_register_call_agree():
    assert _manifest_version() == _register_version()


def test_the_version_looks_like_a_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _manifest_version())


def test_the_manifest_points_at_the_right_repo():
    text = (ROOT / "metadata.yaml").read_text("utf-8")
    assert "astrbot_plugin_chord" in text
