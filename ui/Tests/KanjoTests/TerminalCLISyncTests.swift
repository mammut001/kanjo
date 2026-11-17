import XCTest
@testable import KanjoCore

final class TerminalCLISyncTests: XCTestCase {
    private var root: URL!
    private var bundledCLI: URL!
    private var installDir: URL!
    private var launcher: URL!
    private let fm = FileManager.default

    override func setUpWithError() throws {
        try super.setUpWithError()
        root = fm.temporaryDirectory.appendingPathComponent("kanjo-cli-sync-\(UUID().uuidString)")
        bundledCLI = root.appendingPathComponent("bundled/cli")
        installDir = root.appendingPathComponent("share/kanjo/cli")
        launcher = root.appendingPathComponent("bin/kanjo")
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        if let root, fm.fileExists(atPath: root.path) {
            try? fm.removeItem(at: root)
        }
        try super.tearDownWithError()
    }

    // MARK: - Helpers

    private func writeFile(_ url: URL, contents: String) throws {
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(contents.utf8).write(to: url)
    }

    private func makeBundledCLI(
        versionFile: String? = "0.6.4\n",
        initVersion: String = "0.6.4",
        extraFiles: [String: String] = [:],
        includePricing: Bool = true
    ) throws {
        try writeFile(
            bundledCLI.appendingPathComponent("kanjo/__init__.py"),
            contents: "__version__ = \"\(initVersion)\"\n"
        )
        try writeFile(
            bundledCLI.appendingPathComponent("kanjo/cli.py"),
            contents: "def main():\n    return 'new'\n"
        )
        if let versionFile {
            try writeFile(bundledCLI.appendingPathComponent("VERSION"), contents: versionFile)
        }
        if includePricing {
            try writeFile(bundledCLI.appendingPathComponent("pricing.json"), contents: "{\"v\":2}\n")
            try writeFile(bundledCLI.appendingPathComponent("pricing_overrides.json"), contents: "{}\n")
            try writeFile(bundledCLI.appendingPathComponent("README.md"), contents: "# Kanjo\n")
        }
        for (relPath, contents) in extraFiles {
            try writeFile(bundledCLI.appendingPathComponent(relPath), contents: contents)
        }
    }

    private func makeInstalledCLI(
        versionLine: String = "__version__ = \"0.1.0\"\n",
        extraFiles: [String: String] = [:]
    ) throws {
        try writeFile(
            installDir.appendingPathComponent("kanjo/__init__.py"),
            contents: versionLine
        )
        try writeFile(
            installDir.appendingPathComponent("kanjo/cli.py"),
            contents: "def main():\n    return 'old'\n"
        )
        try writeFile(installDir.appendingPathComponent("pricing.json"), contents: "{\"v\":1}\n")
        for (relPath, contents) in extraFiles {
            try writeFile(installDir.appendingPathComponent(relPath), contents: contents)
        }
    }

    private func makeLauncher(target: String? = nil, includeMarker: Bool = true) throws {
        let cliPath = target ?? installDir.path
        var lines = ["#!/bin/sh"]
        if includeMarker {
            lines.append("# kanjo launcher, written by install.sh")
        }
        lines.append("PYTHONPATH=\"\(cliPath)${PYTHONPATH:+:$PYTHONPATH}\" exec python3 -m kanjo \"$@\"")
        try writeFile(launcher, contents: lines.joined(separator: "\n") + "\n")
    }

    private func setMtime(_ date: Date, at url: URL) throws {
        try fm.setAttributes([.modificationDate: date], ofItemAtPath: url.path)
    }

    private func mtime(of url: URL) throws -> Date {
        let attrs = try fm.attributesOfItem(atPath: url.path)
        return try XCTUnwrap(attrs[.modificationDate] as? Date)
    }

    // MARK: - Tests

    func testUpdatesOldInstallPreservesLauncherAndRemovesStaleFiles() throws {
        try makeBundledCLI(
            versionFile: "0.6.4\n",
            initVersion: "0.6.4",
            extraFiles: ["kanjo/tui/app.py": "print('usage')\n"]
        )
        try makeInstalledCLI(
            versionLine: "__version__ = \"0.1.0\"\n",
            extraFiles: ["kanjo/stale_old.py": "stale\n"]
        )
        try makeLauncher()

        let past = Date(timeIntervalSince1970: 1_700_000_000)
        try setMtime(past, at: launcher)
        let originalLauncherText = try String(contentsOf: launcher, encoding: .utf8)

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(result, .updated(from: "0.1.0", to: "0.6.4"))

        // New files copied, old stale file gone.
        let newInit = try String(contentsOf: installDir.appendingPathComponent("kanjo/__init__.py"), encoding: .utf8)
        XCTAssertTrue(newInit.contains("0.6.4"))
        XCTAssertTrue(fm.fileExists(atPath: installDir.appendingPathComponent("kanjo/tui/app.py").path))
        XCTAssertFalse(fm.fileExists(atPath: installDir.appendingPathComponent("kanjo/stale_old.py").path))
        XCTAssertEqual(try String(contentsOf: installDir.appendingPathComponent("pricing.json"), encoding: .utf8), "{\"v\":2}\n")
        XCTAssertEqual(try String(contentsOf: installDir.appendingPathComponent("pricing_overrides.json"), encoding: .utf8), "{}\n")
        XCTAssertEqual(try String(contentsOf: installDir.appendingPathComponent("README.md"), encoding: .utf8), "# Kanjo\n")

        // Launcher untouched.
        XCTAssertEqual(try String(contentsOf: launcher, encoding: .utf8), originalLauncherText)
        XCTAssertEqual(try mtime(of: launcher), past)

        // No staging/backup directories left behind.
        let siblings = try fm.contentsOfDirectory(atPath: installDir.deletingLastPathComponent().path)
        XCTAssertEqual(siblings, ["cli"])
    }

    func testSameVersionReturnsUpToDateWithoutWriting() throws {
        try makeBundledCLI(versionFile: "0.6.4\n", initVersion: "0.6.4")
        try makeInstalledCLI(versionLine: "__version__ = \"0.6.4\"\n")
        try makeLauncher()

        let past = Date(timeIntervalSince1970: 1_700_000_000)
        let initURL = installDir.appendingPathComponent("kanjo/__init__.py")
        let cliURL = installDir.appendingPathComponent("kanjo/cli.py")
        try setMtime(past, at: initURL)
        try setMtime(past, at: cliURL)

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(result, .upToDate)
        XCTAssertEqual(try mtime(of: initURL), past)
        XCTAssertEqual(try mtime(of: cliURL), past)
        XCTAssertEqual(try String(contentsOf: cliURL, encoding: .utf8), "def main():\n    return 'old'\n")
    }

    func testInstalledNewerDoesNotDowngrade() throws {
        try makeBundledCLI(versionFile: "0.6.4\n", initVersion: "0.6.4")
        try makeInstalledCLI(versionLine: "__version__ = \"0.7.0\"\n")
        try makeLauncher()

        let past = Date(timeIntervalSince1970: 1_700_000_000)
        let initURL = installDir.appendingPathComponent("kanjo/__init__.py")
        try setMtime(past, at: initURL)

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(result, .upToDate)
        XCTAssertEqual(try mtime(of: initURL), past)
        XCTAssertTrue(try String(contentsOf: initURL, encoding: .utf8).contains("0.7.0"))
    }

    func testNumericVersionComparisonAndBundledInitFallback() throws {
        // Without VERSION file, falls back to bundled kanjo/__init__.py; 0.10.0 > 0.2.0 numerically.
        try makeBundledCLI(versionFile: nil, initVersion: "0.10.0")
        try makeInstalledCLI(versionLine: "__version__ = '0.2.0'\n")
        try makeLauncher()

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(result, .updated(from: "0.2.0", to: "0.10.0"))

        // Missing patch part equals 0: 0.10 == 0.10.0 -> upToDate.
        try writeFile(installDir.appendingPathComponent("kanjo/__init__.py"), contents: "__version__ = \"0.10\"\n")
        let second = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(second, .upToDate)
    }

    func testUnparseableInstalledVersionUpdates() throws {
        try makeBundledCLI(versionFile: "0.6.4\n", initVersion: "0.6.4")
        try makeInstalledCLI(versionLine: "__version__ = \"dev\"\n")
        try makeLauncher()

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(result, .updated(from: "dev", to: "0.6.4"))
        XCTAssertTrue(try String(contentsOf: installDir.appendingPathComponent("kanjo/__init__.py"), encoding: .utf8).contains("0.6.4"))
    }

    func testNoInstallReturnsNotInstalledAndCreatesNothing() throws {
        try makeBundledCLI()

        // Neither installDir nor launcher exists.
        XCTAssertEqual(
            TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm),
            .notInstalled
        )
        XCTAssertFalse(fm.fileExists(atPath: installDir.path))
        XCTAssertFalse(fm.fileExists(atPath: launcher.path))

        // Only launcher exists, no installDir.
        try makeLauncher()
        XCTAssertEqual(
            TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm),
            .notInstalled
        )
        XCTAssertFalse(fm.fileExists(atPath: installDir.path))

        // Only installDir exists, no launcher.
        try fm.removeItem(at: launcher)
        try makeInstalledCLI()
        XCTAssertEqual(
            TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm),
            .notInstalled
        )
        XCTAssertFalse(fm.fileExists(atPath: launcher.path))
        XCTAssertTrue(try String(contentsOf: installDir.appendingPathComponent("kanjo/__init__.py"), encoding: .utf8).contains("0.1.0"))
    }

    func testLauncherWithoutMarkerOrPointingElsewhereReturnsNotOurs() throws {
        try makeBundledCLI()
        try makeInstalledCLI()

        let past = Date(timeIntervalSince1970: 1_700_000_000)
        let initURL = installDir.appendingPathComponent("kanjo/__init__.py")
        try setMtime(past, at: initURL)

        // Launcher without marker.
        try makeLauncher(target: installDir.path, includeMarker: false)
        XCTAssertEqual(
            TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm),
            .notOurs
        )
        XCTAssertEqual(try mtime(of: initURL), past)
        XCTAssertTrue(try String(contentsOf: initURL, encoding: .utf8).contains("0.1.0"))

        // Launcher with marker but pointing elsewhere (including prefix-similar path).
        try makeLauncher(target: "\(installDir.path)-custom", includeMarker: true)
        XCTAssertEqual(
            TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm),
            .notOurs
        )
        XCTAssertEqual(try mtime(of: initURL), past)
        XCTAssertTrue(try String(contentsOf: initURL, encoding: .utf8).contains("0.1.0"))
    }

    func testPycacheIsNotCopied() throws {
        try makeBundledCLI(extraFiles: [
            "kanjo/__pycache__/cli.cpython-311.pyc": "bytecode",
            "kanjo/tui/__pycache__/app.cpython-311.pyc": "bytecode",
            "kanjo/tui/app.py": "print('ok')\n",
        ])
        try makeInstalledCLI()
        try makeLauncher()

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        XCTAssertEqual(result, .updated(from: "0.1.0", to: "0.6.4"))
        XCTAssertFalse(fm.fileExists(atPath: installDir.appendingPathComponent("kanjo/__pycache__").path))
        XCTAssertFalse(fm.fileExists(atPath: installDir.appendingPathComponent("kanjo/tui/__pycache__").path))
        XCTAssertTrue(fm.fileExists(atPath: installDir.appendingPathComponent("kanjo/tui/app.py").path))
    }

    func testFailureMidWayLeavesOldInstallIntact() throws {
        try XCTSkipIf(geteuid() == 0, "chmod 000 does not restrict root")

        try makeBundledCLI(extraFiles: ["kanjo/blocked/secret.py": "x = 1\n"])
        try makeInstalledCLI(extraFiles: ["kanjo/keep.py": "keep = True\n"])
        try makeLauncher()

        let blockedDir = bundledCLI.appendingPathComponent("kanjo/blocked")
        try fm.setAttributes([.posixPermissions: 0o000], ofItemAtPath: blockedDir.path)
        defer {
            try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: blockedDir.path)
        }

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        guard case .failed = result else {
            return XCTFail("Expected .failed, got \(result)")
        }

        // Old install and its files remain completely intact.
        let installedInit = try String(contentsOf: installDir.appendingPathComponent("kanjo/__init__.py"), encoding: .utf8)
        XCTAssertTrue(installedInit.contains("0.1.0"))
        XCTAssertEqual(try String(contentsOf: installDir.appendingPathComponent("kanjo/keep.py"), encoding: .utf8), "keep = True\n")

        // No leftover staging or backup directories.
        let siblings = try fm.contentsOfDirectory(atPath: installDir.deletingLastPathComponent().path)
        XCTAssertEqual(siblings, ["cli"])
    }

    func testUnreadableBundledDirLeavesOldInstallIntact() throws {
        try XCTSkipIf(geteuid() == 0, "chmod 000 does not restrict root")

        try makeBundledCLI()
        try makeInstalledCLI()
        try makeLauncher()

        try fm.setAttributes([.posixPermissions: 0o000], ofItemAtPath: bundledCLI.path)
        defer {
            try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: bundledCLI.path)
        }

        let result = TerminalCLISync.sync(bundledCLI: bundledCLI, installDir: installDir, launcher: launcher, fileManager: fm)
        guard case .failed = result else {
            return XCTFail("Expected .failed, got \(result)")
        }
        let installedInit = try String(contentsOf: installDir.appendingPathComponent("kanjo/__init__.py"), encoding: .utf8)
        XCTAssertTrue(installedInit.contains("0.1.0"))
    }
}
