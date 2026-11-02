"""Alyx E2E Test Suite Runner.

Supports running full suite or filtering by tier:
  .venv\\Scripts\\python.exe tests/e2e/runner.py
  .venv\\Scripts\\python.exe tests/e2e/runner.py --tier 1
  .venv\\Scripts\\python.exe tests/e2e/runner.py --tier 2
  .venv\\Scripts\\python.exe tests/e2e/runner.py --tier 3,4
"""
import argparse
import os
import sys
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def build_suite(tiers):
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    tier_map = {
        1: 'tests.e2e.test_tier1_features',
        2: 'tests.e2e.test_tier2_boundaries',
        3: 'tests.e2e.test_tier3_combinations',
        4: 'tests.e2e.test_tier4_scenarios',
    }

    for t in tiers:
        module_name = tier_map.get(t)
        if module_name:
            try:
                mod_suite = loader.loadTestsFromName(module_name)
                suite.addTest(mod_suite)
            except Exception as e:
                print(f"Error loading {module_name}: {e}", file=sys.stderr)

    return suite


def main():
    parser = argparse.ArgumentParser(description="Alyx E2E Test Suite Runner")
    parser.add_argument(
        '--tier',
        type=str,
        default='1,2,3,4',
        help="Comma-separated list of tiers to run (e.g. '1', '2', '3,4', default: '1,2,3,4')"
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        default=True,
        help="Verbose output (default: True)"
    )

    args = parser.parse_args()
    try:
        tiers = [int(t.strip()) for t in args.tier.split(',') if t.strip()]
    except ValueError:
        print(f"Invalid tier argument: '{args.tier}'. Must be comma-separated integers.", file=sys.stderr)
        sys.exit(2)

    print("=" * 70)
    print(" ALYX SWE E2E OPAQUE-BOX TEST SUITE")
    print(f" Tiers to execute: {tiers}")
    print(f" Air-Gap Mode: STRICT LOCAL / OFFLINE (B.8)")
    print("=" * 70)

    suite = build_suite(tiers)
    total_tests = suite.countTestCases()
    print(f"Discovered {total_tests} test cases across specified tiers.\n")

    start_time = time.time()
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    duration = time.time() - start_time

    print("\n" + "=" * 70)
    print(" E2E EXECUTION SUMMARY")
    print(f" Total Tests Run : {result.testsRun}")
    print(f" Passed          : {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f" Failures        : {len(result.failures)}")
    print(f" Errors          : {len(result.errors)}")
    print(f" Total Duration  : {duration:.2f}s")
    print(f" Final Verdict   : {'PASSED (100%)' if result.wasSuccessful() else 'FAILED'}")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
