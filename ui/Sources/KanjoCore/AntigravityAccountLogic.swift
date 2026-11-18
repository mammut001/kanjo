import Foundation

public enum AntigravityAccountButtonState: Equatable, Sendable {
    case current
    case canSwitch
    case needSignInOnce
}

public struct AntigravityAccountShare: Equatable, Identifiable, Sendable {
    public var id: String { email ?? "__unattributed__" }
    public var email: String?
    public var displayName: String
    public var tokens: Int
    public var costUsd: Double
    public var messages: Int
    public var share: Double
    public var isUnattributed: Bool { email == nil }

    public init(
        email: String?,
        displayName: String,
        tokens: Int,
        costUsd: Double,
        messages: Int,
        share: Double
    ) {
        self.email = email
        self.displayName = displayName
        self.tokens = tokens
        self.costUsd = costUsd
        self.messages = messages
        self.share = share
    }
}

public enum AntigravityAccountLogic {
    public static func buttonState(for account: AntigravityAccount, currentEmail: String?) -> AntigravityAccountButtonState {
        if let current = currentEmail, account.email.lowercased() == current.lowercased() {
            return .current
        }
        if account.savedLogin {
            return .canSwitch
        }
        return .needSignInOnce
    }

    public static func localPart(of email: String) -> String {
        let parts = email.split(separator: "@", maxSplits: 1)
        return parts.first.map(String.init) ?? email
    }

    /// Row label for an account: the email local part, unless two listed
    /// accounts share that local part, in which case the full email is shown
    /// for those rows so they stay distinguishable.
    public static func displayName(forEmail email: String, amongEmails emails: [String]) -> String {
        let lp = localPart(of: email)
        let lowerEmail = email.lowercased()
        let sharesLocalPart = emails.contains {
            $0.lowercased() != lowerEmail && localPart(of: $0) == lp
        }
        return sharesLocalPart ? email : lp
    }

    public static func displayName(for account: AntigravityAccount, among accounts: [AntigravityAccount]) -> String {
        displayName(forEmail: account.email, amongEmails: accounts.map(\.email))
    }

    public static func sectionTitle(windowKind: String, windowStartFormatted: String, language: String? = nil) -> String {
        switch windowKind {
        case "quota_week":
            return L10n.tr("overview.agy.title_quota_week", language: language, windowStartFormatted)
        case "billing_cycle":
            return L10n.tr("overview.agy.title_billing_cycle", language: language, windowStartFormatted)
        default:
            return L10n.tr("overview.agy.title_last_7_days", language: language, windowStartFormatted)
        }
    }

    /// Per-account share of Antigravity usage in the given range (day granularity).
    /// Active accounts are sorted by tokens descending; null-email usage follows as "Unattributed";
    /// accounts with zero usage in range are listed at the bottom.
    public static func shares(
        from agy: AntigravityAccounts?,
        range spec: RangeSpec,
        language: String? = nil
    ) -> [AntigravityAccountShare] {
        guard let agy, let byDay = agy.byDay, !byDay.isEmpty else { return [] }

        var byEmail: [String: (email: String, tokens: Int, costUsd: Double, messages: Int)] = [:]
        var unattributedTokens = 0
        var unattributedCost = 0.0
        var unattributedMessages = 0

        for entry in byDay {
            if !spec.isAll {
                guard let d0 = HeatStrip.parseDay(entry.day, calendar: spec.calendar),
                      let d1 = spec.calendar.date(byAdding: .day, value: 1, to: d0),
                      spec.includes(dayStart: d0, dayEnd: d1, agent: "antigravity") else {
                    continue
                }
            }
            if let rawEmail = entry.email?.trimmingCharacters(in: .whitespacesAndNewlines), !rawEmail.isEmpty {
                let key = rawEmail.lowercased()
                var existing = byEmail[key] ?? (email: rawEmail, tokens: 0, costUsd: 0.0, messages: 0)
                existing.tokens += entry.tokens
                existing.costUsd += entry.costUsd
                existing.messages += entry.messages
                byEmail[key] = existing
            } else {
                unattributedTokens += entry.tokens
                unattributedCost += entry.costUsd
                unattributedMessages += entry.messages
            }
        }

        let totalTokens = byEmail.values.reduce(0) { $0 + $1.tokens } + unattributedTokens
        let totalCost = byEmail.values.reduce(0.0) { $0 + $1.costUsd } + unattributedCost
        guard totalTokens > 0 || totalCost > 0 else { return [] }

        func shareFraction(tokens: Int, cost: Double) -> Double {
            if totalTokens > 0 {
                return Double(tokens) / Double(totalTokens)
            }
            if totalCost > 0 {
                return cost / totalCost
            }
            return 0.0
        }

        var canonicalEmails: [String] = []
        var seenKeys = Set<String>()
        for acc in agy.accounts {
            let key = acc.email.lowercased()
            if seenKeys.insert(key).inserted {
                canonicalEmails.append(acc.email)
            }
        }
        for (key, item) in byEmail.sorted(by: { $0.key < $1.key }) where seenKeys.insert(key).inserted {
            canonicalEmails.append(item.email)
        }

        var activeRows: [AntigravityAccountShare] = []
        var zeroRows: [AntigravityAccountShare] = []

        for email in canonicalEmails {
            let key = email.lowercased()
            let agg = byEmail[key]
            let tokens = agg?.tokens ?? 0
            let cost = agg?.costUsd ?? 0.0
            let messages = agg?.messages ?? 0
            let name = displayName(forEmail: email, amongEmails: canonicalEmails)
            let row = AntigravityAccountShare(
                email: email,
                displayName: name,
                tokens: tokens,
                costUsd: cost,
                messages: messages,
                share: shareFraction(tokens: tokens, cost: cost)
            )
            if tokens > 0 || cost > 0 {
                activeRows.append(row)
            } else {
                zeroRows.append(row)
            }
        }

        activeRows.sort { a, b in
            if a.tokens != b.tokens { return a.tokens > b.tokens }
            if a.costUsd != b.costUsd { return a.costUsd > b.costUsd }
            return (a.email ?? "") < (b.email ?? "")
        }

        var out = activeRows
        if unattributedTokens > 0 || unattributedCost > 0 {
            out.append(AntigravityAccountShare(
                email: nil,
                displayName: L10n.tr("agents.detail.unattributed", language: language),
                tokens: unattributedTokens,
                costUsd: unattributedCost,
                messages: unattributedMessages,
                share: shareFraction(tokens: unattributedTokens, cost: unattributedCost)
            ))
        }
        out.append(contentsOf: zeroRows)
        return out
    }

    /// Compact single-line summary of a non-current account's last-seen quota windows,
    /// e.g. "5-hour 10% · Weekly 4% · as of 11/17, 21:30".
    public static func compactQuotaText(
        _ quota: AntigravityAccountQuota,
        timezone: TimeZone = .current,
        language: String? = nil
    ) -> String? {
        guard !quota.windows.isEmpty else { return nil }

        let ordered = quota.windows.enumerated().sorted { a, b in
            let pa = windowSortOrder(a.element.id)
            let pb = windowSortOrder(b.element.id)
            if pa != pb { return pa < pb }
            return a.offset < b.offset
        }.map(\.element)

        var parts: [String] = ordered.map { w in
            let title = localizedWindowTitle(w, language: language)
            let pct: String
            if let raw = w.usedPercent, raw.isFinite {
                let clamped = min(max(raw, 0), 100)
                pct = "\(Int(clamped.rounded()))%"
            } else {
                pct = "—"
            }
            return "\(title) \(pct)"
        }

        let stamp: String
        if let d = ReportDates.parseTimestamp(quota.capturedAt) {
            let cal = RangeEngine.calendar(timezone: timezone)
            stamp = RangeCaptionBuilder.templateFormatter("MdHHmm", cal, language: language).string(from: d)
        } else {
            stamp = quota.capturedAt
        }
        parts.append(L10n.tr("overview.agy.as_of", language: language, stamp))
        return parts.joined(separator: " · ")
    }

    private static func windowSortOrder(_ id: String) -> Int {
        switch id {
        case "five_hour": return 0
        case "weekly": return 1
        default: return 2
        }
    }

    private static func localizedWindowTitle(_ w: ExtraQuotaWindow, language: String? = nil) -> String {
        switch w.id {
        case "five_hour":
            return L10n.tr("overview.quota.five_hour", language: language)
        case "weekly":
            return L10n.tr("overview.quota.weekly", language: language)
        case "3p-weekly":
            return L10n.tr("overview.quota.claude_gpt_weekly", language: language)
        case "3p-5h":
            return L10n.tr("overview.quota.claude_gpt_five_hour", language: language)
        default:
            return w.title
        }
    }
}
