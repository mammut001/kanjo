import XCTest
@testable import KanjoCore

final class ShareImageTests: KanjoTestCase {
    func testExporter() throws {
        let image = NSImage(size: NSSize(width: 10, height: 10))
        image.lockFocus()
        NSColor.red.set()
        NSRect(x: 0, y: 0, width: 10, height: 10).fill()
        image.unlockFocus()
        
        let pasteboard = NSPasteboard(name: .init("kanjo-share-test"))
        ShareImageExporter.copyToPasteboard(image: image, pasteboard: pasteboard)
        
        let pngData = pasteboard.data(forType: .png)
        XCTAssertNotNil(pngData)
        
        let imageFromPasteboard = NSImage(pasteboard: pasteboard)
        XCTAssertNotNil(imageFromPasteboard)
        
        let pngDataFromExporter = ShareImageExporter.pngData(image)
        XCTAssertNotNil(pngDataFromExporter)
        
        pasteboard.clearContents()
    }
}
