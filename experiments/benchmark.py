from src.classical import run_classical
from src.quantum import run_quantum


if __name__ == "__main__":
    print(f"classical={run_classical()}")
    print(f"quantum={run_quantum()}")
