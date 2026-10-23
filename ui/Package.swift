// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "AICost",
    platforms: [.macOS(.v13)],
    targets: [
        // 纯逻辑：契约模型、数据源、格式化、对账。不依赖 SwiftUI，方便测试。
        .target(
            name: "AICostCore",
            path: "Sources/AICostCore"
        ),
        // 菜单栏应用本体。
        .executableTarget(
            name: "AICost",
            dependencies: ["AICostCore"],
            path: "Sources/AICost"
        ),
        .testTarget(
            name: "AICostTests",
            dependencies: ["AICostCore"],
            path: "Tests/AICostTests"
        ),
    ]
)
