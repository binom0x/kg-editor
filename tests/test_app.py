"""Smoke-тесты для UI-пакета (без запуска сервера)."""
import os


def test_package_imports():
    import kg_editor
    assert kg_editor.__version__
    assert hasattr(kg_editor, "build_ui")
    assert hasattr(kg_editor, "launch")
    assert hasattr(kg_editor, "KnowledgeGraph")


def test_favicon_exists():
    """favicon должен приехать вместе с пакетом."""
    import kg_editor
    pkg_dir = os.path.dirname(os.path.abspath(kg_editor.__file__))
    icon = os.path.join(pkg_dir, "assets", "favicon.png")
    assert os.path.isfile(icon), (
        f"favicon.png not found at {icon} — check MANIFEST.in / "
        f"pyproject.toml package-data"
    )


def test_build_ui_smoke():
    """build_ui() не должен падать при построении."""
    from kg_editor import build_ui
    ui = build_ui()
    assert ui is not None