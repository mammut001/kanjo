import Foundation
import KanjoCore
import os
import SwiftUI

@MainActor
final class FamilyReportStore: ObservableObject {
    static let shared = FamilyReportStore()
    static let logger = Logger(subsystem: "com.lanshuagent.kanjo", category: "family-report")

    @Published private(set) var isReporting: Bool = false
    @Published private(set) var lastAttemptAt: Date?
    @Published private(set) var lastSuccessAt: Date?
    @Published private(set) var lastResult: String?
    @Published private(set) var lastError: String?
    @Published private(set) var hasToken: Bool = false

    private let defaults: UserDefaults
    private let tokenStorage: FamilyTokenStorage

    init(defaults: UserDefaults = AppDefaults.store, tokenStorage: FamilyTokenStorage = KeychainFamilyTokenStorage.shared) {
        self.defaults = defaults
        self.tokenStorage = tokenStorage
        self.lastAttemptAt = defaults.object(forKey: SettingsKeys.familyReportLastAttemptAt) as? Date
        self.lastSuccessAt = defaults.object(forKey: SettingsKeys.familyReportLastSuccessAt) as? Date
        self.hasToken = tokenStorage.hasToken()
        let res = defaults.string(forKey: SettingsKeys.familyReportLastResult)
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
        defaults.bool(forKey: SettingsKeys.familyReportEnabled)
    }

    var serverURL: String {
        let val = defaults.string(forKey: SettingsKeys.familyReportURL) ?? ""
        return val.isEmpty ? "https://usage.paytonpei.top" : val
    }

    var memberLabel: String {
        defaults.string(forKey: SettingsKeys.familyReportMemberLabel) ?? ""
    }

    func setToken(_ token: String) -> Bool {
        let ok = tokenStorage.saveToken(token)
        refreshTokenState()
        return ok
    }

    func clearToken() -> Bool {
        let ok = tokenStorage.deleteToken()
        refreshTokenState()
        return ok
    }

    func refreshTokenState() {
        hasToken = tokenStorage.hasToken()
    }

    func reportDidRefresh(_ report: UsageReport) {
        guard isEnabled else { return }
        refreshTokenState()
        guard hasToken else { return }

        // Check if network is disabled via environment or config
        let isNoNetwork = ProcessInfo.processInfo.environment["KANJO_NO_NETWORK"] == "1" || report.config.noNetwork == true
        if isNoNetwork {
            Self.logger.info("family report skipped: network disabled")
            return
        }

        guard FamilyReportSchedule.shouldReport(
            enabled: isEnabled,
            hasToken: hasToken,
            url: serverURL,
            lastSuccessAt: lastSuccessAt,
            lastAttemptAt: lastAttemptAt,
            now: Date(),
            noNetwork: isNoNetwork
        ) else {
            return
        }

        Task {
            await performReport(qualityOfService: .background)
        }
    }

    func reportNow(cliCommand: String? = nil, cwd: URL? = nil) async {
        await performReport(cliCommandOverride: cliCommand, cwdOverride: cwd, qualityOfService: .userInitiated)
    }

    private func performReport(
        cliCommandOverride: String? = nil,
        cwdOverride: URL? = nil,
        qualityOfService: QualityOfService
    ) async {
        guard !isReporting else { return }
        refreshTokenState()
        guard hasToken, let token = tokenStorage.loadToken(), !token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            recordFailure(at: Date(), message: "Token not configured")
            return
        }

        let cleanToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        let currentURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard FamilyReportSchedule.isValidURL(currentURL) else {
            recordFailure(at: Date(), message: "Invalid server URL")
            return
        }

        isReporting = true
        defer { isReporting = false }

        let now = Date()
        let baseCli = cliCommandOverride ?? CLILaunch.command(defaults: defaults)
        let workingDir = cwdOverride ?? CLILaunch.workingDirectory(defaults: defaults)
        let command = FamilyReportCommand.command(from: baseCli, url: currentURL, memberLabel: memberLabel)
        Self.logger.info("running family report: \(command)")

        do {
            let (status, outData, errData, timedOut) = try await Task.detached(priority: .utility) {
                try CLIDataSource.run(
                    command: command,
                    cwd: workingDir,
                    timeout: 45,
                    qualityOfService: qualityOfService,
                    extraEnvironment: ["KANJO_FAMILY_TOKEN": cleanToken]
                )
            }.value

            if timedOut {
                let errText = "Command timed out after 45s"
                recordFailure(at: now, message: errText)
                return
            }

            let outStr = String(decoding: outData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            let errStr = String(decoding: errData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)

            if status == 0 {
                if let data = outStr.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let st = json["status"] as? String {
                    if st == "sent" {
                        recordSuccess(at: now, result: outStr)
                        return
                    } else if st == "error" {
                        let msg = (json["message"] as? String) ?? outStr
                        recordFailure(at: now, message: msg)
                        return
                    }
                }
                recordSuccess(at: now, result: outStr.isEmpty ? "{\"status\":\"sent\"}" : outStr)
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
        defaults.set(date, forKey: SettingsKeys.familyReportLastSuccessAt)
        defaults.set(date, forKey: SettingsKeys.familyReportLastAttemptAt)
        defaults.set(result, forKey: SettingsKeys.familyReportLastResult)
        Self.logger.info("family report succeeded: \(result)")
    }

    private func recordFailure(at date: Date, message: String) {
        lastAttemptAt = date
        lastError = message
        let failureJson = "{\"status\": \"error\", \"message\": \(escapeJsonString(message))}"
        lastResult = failureJson
        defaults.set(date, forKey: SettingsKeys.familyReportLastAttemptAt)
        defaults.set(failureJson, forKey: SettingsKeys.familyReportLastResult)
        Self.logger.error("family report failed: \(message)")
    }

    private func escapeJsonString(_ str: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: [str]),
              let json = String(data: data, encoding: .utf8) else {
            return "\"\(str)\""
        }
        return String(json.dropFirst().dropLast())
    }
}
