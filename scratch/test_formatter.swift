import Foundation

let formatter = ISO8601DateFormatter()
formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

let s1 = "2026-11-18T14:16:50.1Z"
let s2 = "2026-11-18T14:16:50.123456Z"

print(formatter.date(from: s1)!)
print(formatter.date(from: s2)!)
