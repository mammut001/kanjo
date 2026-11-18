import SwiftUI
import KanjoCore

public struct CopyButton: View {
    let action: () -> Void
    @State private var copied: Bool = false
    
    public init(action: @escaping () -> Void) {
        self.action = action
    }
    
    public var body: some View {
        Button {
            action()
            copied = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { copied = false }
        } label: {
            Image(systemName: copied ? "checkmark" : "photo.on.rectangle")
                .font(.system(size: 12))
        }
        .buttonStyle(.plain)
        .hoverTip(L10n.tr("menu.copy_usage_image"))
    }
}
