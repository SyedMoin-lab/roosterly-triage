import subprocess
import sys

CHECKS = (
    ("format", ["ruff", "format", "--check", "."]),
    ("lint", ["ruff", "check", "."]),
    ("types", ["mypy"]),
    ("tests", ["pytest"]),
)


def main() -> int:
    for name, arguments in CHECKS:
        print(f"==> {name}: {' '.join(arguments)}", flush=True)
        if subprocess.run([sys.executable, "-m", *arguments], check=False).returncode != 0:
            print(f"FAILED: {name}", file=sys.stderr)
            return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
