import Foundation
import KanjoCore
import os
import SwiftUI

@MainActor
final class PublishStore: ObservableObject {
    static let shared = PublishStore()
    static let logger = Logger(subsystem: "com.lanshuagent.kanjo", category: "publish")

    @Published private(set) var isPublishing: Bool = false
    @Published private(set) var lastAttemptAt: Date?
    @Published private(set) var lastSuccessAt: Date?
    @Published private(set) var lastResult: String?
    @Published private(set) var lastError: String?

    private let defaults: UserDefaults

    init(defaults: UserDefaults = AppDefaults.store) {
        self.defaults = defaults
        self.lastAttemptAt = defaults.object(forKey: SettingsKeys.publishLastAttemptAt) as? Date
        self.lastSuccessAt = defaults.object(forKey: SettingsKeys.publishLastSuccessAt) as? Date
        let res = defaults.string(forKey: SettingsKeys.publishLastResult)
        self.lastResult = res
        if let res = res, res.contains("\"status\": \"error\"") || res.contains("\"status\":\"error\"") {
            if let data = res.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let msg = json["message"] as? String {
                self.lastError = msg
            } else {
                self.lastError = res
            }
        }
    }

    var isEnabled: Bool {
        defaults.bool(forKey: SettingsKeys.publishEnabled)
    }

    var frequency: PublishFrequency {
        let raw = defaults.string(forKey: SettingsKeys.publishFrequency) ?? "weekly"
        return PublishFrequency(rawValue: raw) ?? .weekly
    }

    var repoPath: String {
        defaults.string(forKey: SettingsKeys.publishRepoPath) ?? ""
    }

    var filePath: String {
        let val = defaults.string(forKey: SettingsKeys.publishFilePath) ?? ""
        return val.isEmpty ? "src/data/token-usage.json" : val
    }

    var branch: String {
        let val = defaults.string(forKey: SettingsKeys.publishBranch) ?? ""
        return val.isEmpty ? "main" : val
    }

    func reportDidRefresh(_ report: UsageReport) {
        guard isEnabled else { return }
        guard !repoPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        // Check if network is disabled via environment or config
        let isNoNetwork = ProcessInfo.processInfo.environment["KANJO_NO_NETWORK"] == "1" || report.config.noNetwork == true
        if isNoNetwork {
            Self.logger.info("publish skipped: network disabled")
            return
        }

        let tz = report.timezone.flatMap { TimeZone(identifier: $0) } ?? .current
        guard PublishSchedule.shouldPublish(
            enabled: isEnabled,
            repoPath: repoPath,
            frequency: frequency,
            lastSuccessAt: lastSuccessAt,
            lastAttemptAt: lastAttemptAt,
            timeZone: tz
        ) else {
            return
        }

        Task {
            await performPublish(qualityOfService: .background)
        }
    }

    func publishNow(cliCommand: String? = nil, cwd: URL? = nil) async {
        await performPublish(cliCommandOverride: cliCommand, cwdOverride: cwd, qualityOfService: .userInitiated)
    }

    private func performPublish(
        cliCommandOverride: String? = nil,
        cwdOverride: URL? = nil,
        qualityOfService: QualityOfService
    ) async {
        guard !isPublishing else { return }
        let currentRepo = repoPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !currentRepo.isEmpty else { return }

        isPublishing = true
        defer { isPublishing = false }

        let now = Date()
        let baseCli = cliCommandOverride ?? CLILaunch.command(defaults: defaults)
        let workingDir = cwdOverride ?? CLILaunch.workingDirectory(defaults: defaults)
        let command = PublishCommand.command(from: baseCli, repo: currentRepo, file: filePath, branch: branch)
        Self.logger.info("running publish: \(command)")

        do {
            let (status, outData, errData, timedOut) = try await Task.detached(priority: .utility) {
                try CLIDataSource.run(command: command, cwd: workingDir, timeout: 120, qualityOfService: qualityOfService)
            }.value

            if timedOut {
                let errText = "Command timed out after 120s"
                recordFailure(at: now, message: errText)
                return
            }

            let outStr = String(decoding: outData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            let errStr = String(decoding: errData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)

            if status == 0 {
                // Parse stdout for {"status": "pushed"} or {"status": "unchanged"}
                if let data = outStr.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let st = json["status"] as? String {
                    if st == "pushed" || st == "unchanged" {
                        recordSuccess(at: now, result: outStr)
                        return
                    } else if st == "error" {
                        let msg = (json["message"] as? String) ?? outStr
                        recordFailure(at: now, message: msg)
                        return
                    }
                }
                recordSuccess(at: now, result: outStr.isEmpty ? "{\"status\":\"pushed\"}" : outStr)
            } else {
                let msg: String
                if let data = outStr.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let errJsonMsg = json["message"] as? String {
                    msg = errJsonMsg
                } else if !errStr.isEmpty {
                    msg = errStr
                } else if !outStr.isEmpty {
                    msg = outStr
                } else {
                    msg = "Process failed with exit code \(status)"
                }
                recordFailure(at: now, message: msg)
            }
        } catch {
            recordFailure(at: now, message: error.localizedDescription)
        }
    }

    private func recordSuccess(at date: Date, result: String) {
        lastSuccessAt = date
        lastAttemptAt = date
        lastResult = result
        lastError = nil
        defaults.set(date, forKey: SettingsKeys.publishLastSuccessAt)
        defaults.set(date, forKey: SettingsKeys.publishLastAttemptAt)
        defaults.set(result, forKey: SettingsKeys.publishLastResult)
        Self.logger.info("publish succeeded: \(result)")
    }

    private func recordFailure(at date: Date, message: String) {
        lastAttemptAt = date
        lastError = message
        let failureJson = "{\"status\": \"error\", \"message\": \(escapeJsonString(message))}"
        lastResult = failureJson
        defaults.set(date, forKey: SettingsKeys.publishLastAttemptAt)
        defaults.set(failureJson, forKey: SettingsKeys.publishLastResult)
        Self.logger.error("publish failed: \(message)")
    }

    private func escapeJsonString(_ str: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: [str]),
              let json = String(data: data, encoding: .utf8) else {
            return "\"\(str)\""
        }
        return String(json.dropFirst().dropLast())
    }
}
