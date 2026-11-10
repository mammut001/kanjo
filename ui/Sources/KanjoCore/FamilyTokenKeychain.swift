import Foundation
import Security

/// Abstraction for storing the family report token.
public protocol FamilyTokenStorage: Sendable {
    func loadToken() -> String?
    func saveToken(_ token: String) -> Bool
    func deleteToken() -> Bool
    func hasToken() -> Bool
}

/// macOS Keychain implementation using the Security framework.
/// Service: "com.lanshuagent.kanjo.family", Account: "report-token"
public final class KeychainFamilyTokenStorage: FamilyTokenStorage, @unchecked Sendable {
    public static let shared = KeychainFamilyTokenStorage()

    public static let service = "com.lanshuagent.kanjo.family"
    public static let account = "report-token"

    public init() {}

    public func loadToken() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: Self.account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    public func hasToken() -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: Self.account,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        let status = SecItemCopyMatching(query as CFDictionary, nil)
        return status == errSecSuccess
    }

    public func saveToken(_ token: String) -> Bool {
        guard let data = token.data(using: .utf8) else { return false }
        let deleteQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: Self.account,
        ]
        SecItemDelete(deleteQuery as CFDictionary)

        let addQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: Self.account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        let status = SecItemAdd(addQuery as CFDictionary, nil)
        return status == errSecSuccess
    }

    public func deleteToken() -> Bool {
        let deleteQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: Self.account,
        ]
        let status = SecItemDelete(deleteQuery as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }
}

/// In-memory token storage for tests.
public final class MockFamilyTokenStorage: FamilyTokenStorage, @unchecked Sendable {
    private var token: String?
    private let lock = NSLock()

    public init(initialToken: String? = nil) {
        self.token = initialToken
    }

    public func loadToken() -> String? {
        lock.lock()
        defer { lock.unlock() }
        return token
    }

    public func hasToken() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return token != nil && !token!.isEmpty
    }

    public func saveToken(_ token: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        self.token = token
        return true
    }

    public func deleteToken() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        self.token = nil
        return true
    }
}
