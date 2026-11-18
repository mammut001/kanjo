import Foundation

func fastParseTimestamp(_ s: String) -> Date? {
    let bytes = Array(s.utf8)
    guard bytes.count >= 20 else { return nil } // YYYY-MM-DDTHH:MM:SSZ

    // Very simple check for shape
    guard bytes[4] == 45, bytes[7] == 45, bytes[10] == 84, // - - T
          bytes[13] == 58, bytes[16] == 58 else { return nil } // : :

    // Parse YYYY
    let year = (Int(bytes[0]-48)*1000 + Int(bytes[1]-48)*100 + Int(bytes[2]-48)*10 + Int(bytes[3]-48))
    let month = (Int(bytes[5]-48)*10 + Int(bytes[6]-48))
    let day = (Int(bytes[8]-48)*10 + Int(bytes[9]-48))
    let hour = (Int(bytes[11]-48)*10 + Int(bytes[12]-48))
    let minute = (Int(bytes[14]-48)*10 + Int(bytes[15]-48))
    let second = (Int(bytes[17]-48)*10 + Int(bytes[18]-48))

    var pos = 19
    // Optional fraction
    if pos < bytes.count, bytes[pos] == 46 { // .
        pos += 1
        while pos < bytes.count, bytes[pos] >= 48, bytes[pos] <= 57 {
            pos += 1
        }
    }

    var secondsFromGMT = 0
    if pos < bytes.count {
        if bytes[pos] == 90 { // Z
            secondsFromGMT = 0
        } else if bytes[pos] == 43 || bytes[pos] == 45 { // + or -
            if pos + 5 < bytes.count {
                let sign = bytes[pos] == 45 ? -1 : 1
                let h = (Int(bytes[pos+1]-48)*10 + Int(bytes[pos+2]-48))
                let m = (Int(bytes[pos+4]-48)*10 + Int(bytes[pos+5]-48))
                secondsFromGMT = sign * (h * 3600 + m * 60)
            }
        }
    }

    // Days from civil formula
    // Simplified, assuming valid inputs as per requirements
    // For now, using Calendar to verify, will replace with arithmetic later
    var components = DateComponents()
    components.year = year
    components.month = month
    components.day = day
    components.hour = hour
    components.minute = minute
    components.second = second
    components.timeZone = TimeZone(secondsFromGMT: secondsFromGMT)
    
    return Calendar(identifier: .gregorian).date(from: components)
}

let testDate = "2026-11-18T14:16:50.123Z"
print(fastParseTimestamp(testDate)!)
