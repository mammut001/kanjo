// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Kanjo",
    defaultLocalization: "en",
    platforms: [.macOS(.v13), .iOS(.v17)],
    products: [
        // 供 iOS app 复用纯逻辑与本地化资源。
        .library(name: "KanjoCore", targets: ["KanjoCore"]),
    ],
    targets: [
        // 纯逻辑：契约模型、数据源、格式化、对账。不依赖 SwiftUI，方便测试。
        .target(
            name: "KanjoCore",
            path: "Sources/KanjoCore",
            resources: [.process("Resources")]
        ),
        // 菜单栏应用本体。
        .executableTarget(
            name: "Kanjo",
            dependencies: ["KanjoCore"],
            path: "Sources/Kanjo"
        ),
        .testTarget(
            name: "KanjoTests",
            dependencies: ["KanjoCore"],
            path: "Tests/KanjoTests"
        ),
    ]
)
