import Foundation
#if canImport(AppKit)
import AppKit

public enum BrandIcon {
    public static var image: NSImage? {
        Bundle.module.image(forResource: "Kanjo-icon")
    }
}
#endif
