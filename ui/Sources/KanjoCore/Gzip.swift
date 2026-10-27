import Compression
import Foundation

public enum GzipError: LocalizedError, Equatable {
    case invalidHeader
    case truncated
    case unsupportedMethod
    case decompressionFailed

    public var errorDescription: String? {
        switch self {
        case .invalidHeader: return L10n.tr("gzip.error.invalid_header")
        case .truncated: return L10n.tr("gzip.error.truncated")
        case .unsupportedMethod: return L10n.tr("gzip.error.unsupported_method")
        case .decompressionFailed: return L10n.tr("gzip.error.decompression_failed")
        }
    }
}

public enum Gzip {
    public static func decompress(_ data: Data) throws -> Data {
        let bytes = [UInt8](data)
        guard bytes.count >= 18 else { throw GzipError.truncated }
        guard bytes[0] == 0x1f, bytes[1] == 0x8b else { throw GzipError.invalidHeader }
        guard bytes[2] == 0x08 else { throw GzipError.unsupportedMethod }

        let flags = bytes[3]
        var offset = 10

        if flags & 0x04 != 0 {
            guard offset + 2 <= bytes.count else { throw GzipError.truncated }
            let extraLength = Int(bytes[offset]) | (Int(bytes[offset + 1]) << 8)
            offset += 2 + extraLength
            guard offset <= bytes.count else { throw GzipError.truncated }
        }
        if flags & 0x08 != 0 {
            while offset < bytes.count, bytes[offset] != 0 { offset += 1 }
            offset += 1
        }
        if flags & 0x10 != 0 {
            while offset < bytes.count, bytes[offset] != 0 { offset += 1 }
            offset += 1
        }
        if flags & 0x02 != 0 {
            offset += 2
        }

        guard offset <= bytes.count - 8 else { throw GzipError.truncated }
        let deflated = Data(bytes[offset..<(bytes.count - 8)])
        let expectedSize = bytes.suffix(4).enumerated().reduce(0) { total, pair in
            total | (Int(pair.element) << (8 * pair.offset))
        }
        return try inflate(deflated, expectedSize: expectedSize)
    }

    private static func inflate(_ data: Data, expectedSize: Int) throws -> Data {
        guard !data.isEmpty else { throw GzipError.decompressionFailed }
        let capacity = max(expectedSize, data.count * 4, 64)
        var output = Data(count: capacity)
        let decoded = output.withUnsafeMutableBytes { destination -> Int in
            data.withUnsafeBytes { source -> Int in
                guard let destinationBase = destination.bindMemory(to: UInt8.self).baseAddress,
                      let sourceBase = source.bindMemory(to: UInt8.self).baseAddress else {
                    return 0
                }
                return compression_decode_buffer(
                    destinationBase, capacity,
                    sourceBase, data.count,
                    nil, COMPRESSION_ZLIB
                )
            }
        }
        guard decoded == expectedSize else { throw GzipError.decompressionFailed }
        output.removeSubrange(decoded..<output.count)
        return output
    }
}
