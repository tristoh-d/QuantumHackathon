from pathlib import Path


def test_classical_module_exists() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "src" / "classical.py").is_file()
