from pathlib import Path


def test_quantum_module_exists() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "src" / "quantum.py").is_file()
