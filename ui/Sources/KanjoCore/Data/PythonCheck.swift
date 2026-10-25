import Foundation

public enum PythonCheck {
    public static func needsCommandLineTools(status: Int32, stderr: String) -> Bool {
        let text = stderr.lowercased()
        return status != 0 && (text.contains("xcode-select") || text.contains("command line tools"))
    }

    public static func check() async -> Bool {
        let result = try? await Task.detached(priority: .utility) {
            try CLIDataSource.run(command: "/usr/bin/env python3 -c 'import sys; print(sys.version_info[:2])'",
                                  cwd: nil, timeout: 15)
        }.value
        guard let (status, _, stderr, _) = result else { return false }
        return needsCommandLineTools(status: status, stderr: String(decoding: stderr, as: UTF8.self))
    }

    public static func installCommandLineTools() async throws {
        let (status, _, stderr, _) = try await Task.detached(priority: .utility) {
            try CLIDataSource.run(command: "/usr/bin/xcode-select --install", cwd: nil, timeout: 15)
        }.value
        guard status == 0 else {
            throw DataSourceError.commandFailed(command: "xcode-select --install", status: status,
                                                stderr: String(decoding: stderr, as: UTF8.self))
        }
    }
}
