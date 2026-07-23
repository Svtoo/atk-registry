"""Shared runner for the self-contained test scripts in this directory."""
import sys


def run_module_tests(module_globals: dict) -> None:
    """Run every test_* callable, print one FAIL line per failure and an
    aggregate count, and exit non-zero if anything failed."""
    tests = [v for k, v in sorted(module_globals.items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print(f"{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
