# Mac / Windows calculation parity

The tests read only `ui/fixtures/sample.json`. Each scenario overrides the report
zone and clock. Money and multipliers are integer hundredths; timestamps are UTC.
The tests compare their generated data to their own golden. Compare the two
independent goldens with `python3 parity/compare.py`.

To regenerate after an intentional calculation change, run from the repository
root (use absolute output paths), then run the comparison and investigate every
change before accepting the files:

```sh
(cd ui && KANJO_PARITY_DUMP="$PWD/../parity/mac.json" swift test --filter ParityDumpTests)
KANJO_PARITY_DUMP="$PWD/parity/windows.json" dotnet test windows/tests/Kanjo.Core.Tests/Kanjo.Core.Tests.csproj --filter FullyQualifiedName~ParityDumpTests
(cd cli && KANJO_PARITY_DUMP="$PWD/../parity/tui.json" python3 -m unittest tests.test_parity_dump.ParityDumpTests.test_dump)
python3 parity/compare.py
```

The environment variable switches the test to write mode; normal test runs
never update the baselines. JSON key ordering and whitespace do not affect the
comparison.
