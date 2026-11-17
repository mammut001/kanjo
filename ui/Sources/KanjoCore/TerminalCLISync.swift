import Foundation

/// Synchronizes a terminal `kanjo` CLI installation created by `install.sh`
/// to match the bundled CLI shipped inside `Kanjo.app`.
public enum TerminalCLISync {
    public enum Result: Equatable, Sendable {
        case updated(from: String, to: String)
        case upToDate
        case notInstalled
        case notOurs
        case failed(String)
    }

    private static let launcherMarker = "written by install.sh"
    private static let supplementaryFiles = ["pricing.json", "pricing_overrides.json", "README.md"]

    public static func sync(
        bundledCLI: URL,
        installDir: URL,
        launcher: URL,
        fileManager: FileManager = .default
    ) -> Result {
        let installedInit = installDir.appendingPathComponent("kanjo/__init__.py")
        guard fileManager.fileExists(atPath: installedInit.path),
              fileManager.fileExists(atPath: launcher.path) else {
            return .notInstalled
        }

        guard isManagedLauncher(launcher, installDir: installDir) else {
            return .notOurs
        }

        let bundledInit = bundledCLI.appendingPathComponent("kanjo/__init__.py")
        guard fileManager.fileExists(atPath: bundledInit.path),
              let bundled = readBundledVersion(bundledCLI: bundledCLI, bundledInit: bundledInit) else {
            return .failed("Invalid or unreadable bundled CLI")
        }

        let installed = readInstalledVersion(initFile: installedInit)
        if let installedNums = installed.components,
           !isVersion(installedNums, lessThan: bundled.components) {
            return .upToDate
        }

        do {
            try replaceInstallAtomically(
                from: bundledCLI,
                to: installDir.standardizedFileURL,
                fileManager: fileManager
            )
            return .updated(from: installed.raw ?? "unknown", to: bundled.raw)
        } catch {
            return .failed(error.localizedDescription)
        }
    }

    private static func isManagedLauncher(_ launcher: URL, installDir: URL) -> Bool {
        guard let text = try? String(contentsOf: launcher, encoding: .utf8),
              text.contains(launcherMarker) else {
            return false
        }
        let candidatePaths = Set([
            installDir.path,
            installDir.standardizedFileURL.path,
            installDir.resolvingSymlinksInPath().path,
        ])
        return candidatePaths.contains { Self.text(text, referencesPath: $0) }
    }

    private static func text(_ text: String, referencesPath path: String) -> Bool {
        guard !path.isEmpty else { return false }
        var searchStart = text.startIndex
        while let range = text.range(of: path, range: searchStart..<text.endIndex) {
            let validBefore: Bool
            if range.lowerBound == text.startIndex {
                validBefore = true
            } else {
                let prev = text[text.index(before: range.lowerBound)]
                validBefore = prev == "=" || prev == "\"" || prev == "'" || prev == ":" || prev.isWhitespace
            }
            let validAfter: Bool
            if range.upperBound == text.endIndex {
                validAfter = true
            } else {
                let next = text[range.upperBound]
                validAfter = next == "\"" || next == "'" || next == ":" || next == "/" || next == "$" || next == ";" || next.isWhitespace
            }
            if validBefore && validAfter {
                return true
            }
            searchStart = range.upperBound
        }
        return false
    }

    private static func readBundledVersion(
        bundledCLI: URL,
        bundledInit: URL
    ) -> (raw: String, components: [Int])? {
        let versionFile = bundledCLI.appendingPathComponent("VERSION")
        if let raw = try? String(contentsOf: versionFile, encoding: .utf8) {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if let components = parseVersionComponents(trimmed) {
                return (trimmed, components)
            }
        }
        if let contents = try? String(contentsOf: bundledInit, encoding: .utf8),
           let raw = extractPythonVersion(from: contents),
           let components = parseVersionComponents(raw) {
            return (raw, components)
        }
        return nil
    }

    private static func readInstalledVersion(initFile: URL) -> (raw: String?, components: [Int]?) {
        guard let contents = try? String(contentsOf: initFile, encoding: .utf8) else {
            return (nil, nil)
        }
        let raw = extractPythonVersion(from: contents)
        let components = raw.flatMap(parseVersionComponents)
        return (raw, components)
    }

    static func extractPythonVersion(from contents: String) -> String? {
        let pattern = #"(?m)^\s*__version__\s*=\s*["']([^"']+)["']"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(contents.startIndex..<contents.endIndex, in: contents)
        guard let match = regex.firstMatch(in: contents, range: range),
              let valueRange = Range(match.range(at: 1), in: contents) else {
            return nil
        }
        let value = String(contents[valueRange]).trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    static func parseVersionComponents(_ raw: String) -> [Int]? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let parts = trimmed.split(separator: ".", omittingEmptySubsequences: false)
        guard !parts.isEmpty else { return nil }
        var numbers: [Int] = []
        numbers.reserveCapacity(parts.count)
        for part in parts {
            guard !part.isEmpty,
                  part.allSatisfy({ $0.isASCII && $0.isNumber }),
                  let number = Int(part) else {
                return nil
            }
            numbers.append(number)
        }
        return numbers
    }

    static func isVersion(_ lhs: [Int], lessThan rhs: [Int]) -> Bool {
        let count = max(lhs.count, rhs.count)
        for i in 0..<count {
            let a = i < lhs.count ? lhs[i] : 0
            let b = i < rhs.count ? rhs[i] : 0
            if a != b { return a < b }
        }
        return false
    }

    private static func replaceInstallAtomically(
        from bundledCLI: URL,
        to installDir: URL,
        fileManager: FileManager
    ) throws {
        let parent = installDir.deletingLastPathComponent()
        let token = UUID().uuidString
        let stage = parent.appendingPathComponent(".cli.stage.\(token)")
        let backup = parent.appendingPathComponent(".cli.old.\(token)")

        defer {
            if fileManager.fileExists(atPath: stage.path) {
                try? fileManager.removeItem(at: stage)
            }
        }

        try fileManager.createDirectory(at: stage, withIntermediateDirectories: true)
        try copyDirectorySkippingPycache(
            from: bundledCLI.appendingPathComponent("kanjo"),
            to: stage.appendingPathComponent("kanjo"),
            fileManager: fileManager
        )
        for filename in supplementaryFiles {
            let source = bundledCLI.appendingPathComponent(filename)
            var isDir: ObjCBool = false
            if fileManager.fileExists(atPath: source.path, isDirectory: &isDir), !isDir.boolValue {
                try fileManager.copyItem(at: source, to: stage.appendingPathComponent(filename))
            }
        }

        try fileManager.moveItem(at: installDir, to: backup)
        do {
            try fileManager.moveItem(at: stage, to: installDir)
        } catch {
            try? fileManager.moveItem(at: backup, to: installDir)
            throw error
        }
        try? fileManager.removeItem(at: backup)
    }

    private static func copyDirectorySkippingPycache(
        from source: URL,
        to destination: URL,
        fileManager: FileManager
    ) throws {
        try fileManager.createDirectory(at: destination, withIntermediateDirectories: true)
        let entries = try fileManager.contentsOfDirectory(
            at: source,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
            options: []
        )
        for entry in entries {
            let name = entry.lastPathComponent
            if name == "__pycache__" { continue }
            let destEntry = destination.appendingPathComponent(name)
            let values = try entry.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            if values.isDirectory == true && values.isSymbolicLink != true {
                try copyDirectorySkippingPycache(from: entry, to: destEntry, fileManager: fileManager)
            } else {
                try fileManager.copyItem(at: entry, to: destEntry)
            }
        }
    }
}
