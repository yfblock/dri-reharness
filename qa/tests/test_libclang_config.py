from __future__ import annotations


if __package__:
    from . import _bootstrap as _paths  # noqa: F401
else:
    import _bootstrap as _paths  # noqa: F401


def test_configure_does_not_replace_an_already_loaded_libclang(monkeypatch):
    import clang.cindex as cx
    from ast_analyzer import tu

    calls = []
    monkeypatch.setattr(cx.Config, "loaded", True)
    monkeypatch.setattr(
        cx.Config, "set_library_file",
        lambda path: calls.append(path))
    monkeypatch.setattr(tu, "_CONFIGURED", False)

    tu._configure()

    assert calls == []
    assert tu._CONFIGURED is True
