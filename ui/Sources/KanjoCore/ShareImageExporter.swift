import AppKit

public enum ShareImageExporter {
    public static func copyToPasteboard(image: NSImage, pasteboard: NSPasteboard = .general) {
        pasteboard.clearContents()
        pasteboard.writeObjects([image])
        
        // Also write PNG
        if let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) {
            if let png = bitmap.representation(using: .png, properties: [:]) {
                pasteboard.setData(png, forType: .png)
            }
        }
    }
}
