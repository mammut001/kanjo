import Foundation

let formatter = ISO8601DateFormatter()
formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

let s1 = "2026-11-18T14:16:50.123Z"
let s2 = "2026-11-18T14:16:50.123456Z"

let d1 = formatter.date(from: s1)!
let d2 = formatter.date(from: s2)!

print(d1.timeIntervalSince1970)
print(d2.timeIntervalSince1970)
print(d1 == d2)
