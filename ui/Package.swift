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
    dependencies: [
        // 应用内更新（macOS 版专用）。KanjoCore 保持零依赖，iOS app 不受影响。
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.6.0"),
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
            dependencies: [
                "KanjoCore",
                .product(name: "Sparkle", package: "Sparkle", condition: .when(platforms: [.macOS])),
            ],
            path: "Sources/Kanjo"
        ),
        .testTarget(
            name: "KanjoTests",
            dependencies: ["KanjoCore"],
            path: "Tests/KanjoTests"
        ),
    ]
)
