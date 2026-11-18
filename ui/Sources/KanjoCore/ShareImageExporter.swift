#if os(macOS)

import AppKit

public enum ShareImageExporter {
    public static func copyToPasteboard(image: NSImage, pasteboard: NSPasteboard = .general) {
        pasteboard.clearContents()
        pasteboard.writeObjects([image])
        
        // Also write PNG
        if let png = pngData(image) {
            pasteboard.setData(png, forType: .png)
        }
    }
    
    public static func pngData(_ image: NSImage) -> Data? {
        guard let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) else {
            return nil
        }
        return bitmap.representation(using: .png, properties: [:])
    }
}

#endif
