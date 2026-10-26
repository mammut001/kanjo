import XCTest
@testable import KanjoCore

final class PathKindsTests: KanjoTestCase {
    private let home = "/Users/me"

    func testTemporaryPaths() {
        let temps = [
            "/tmp/foo",
            "/tmp",
            "/private/tmp/claude-501/-Users-me-proj/abc/scratchpad/x",
            "/var/folders/xy/T/build",
            "/private/var/folders/xy/T/build",
            "~/.gemini/antigravity-cli/brain/123/scratch/watch-ui",
            "/Users/me/.gemini/antigravity-cli/brain/123",
            "~/.claude/projects/foo",
            "/Users/me/.codex/worktrees/a1b2/proj",
            "/Users/me/work/scratchpad",
            "/Users/me/work/scratch/thing",
            "/Users/me/proj/.worktrees/feature",
            "/Volumes/ext/worktrees/proj",
        ]
        for p in temps { XCTAssertTrue(isTemporaryPath(p, home: home), p) }
    }

    func testPrimaryPaths() {
        let primaries = [
            "/Users/me/Documents/GitHub/FocusApp",
            "/Users/me/Documents/GitHub/FocusApp-fixes-146",
            "~/code/proj",
            "/Users/me/orca/workspaces/FocusApp/mako",
            "/Users/me/tmp/proj",                // 不是 /tmp/ 前缀
            "/Users/me/.geminix/proj",           // 不是 ~/.gemini/
            "/Users/other/.claude/proj",         // 别人的 home
            "/Users/me/scratchpads/proj",        // 分量必须完全相等
            "/Users/me/my-scratch/proj",
            "/Users/me/worktrees-old/proj",
        ]
        for p in primaries { XCTAssertFalse(isTemporaryPath(p, home: home), p) }
    }

    func testSplitPathsPreservesOrder() {
        let input = [
            "/tmp/a",
            "/Users/me/p1",
            "/Users/me/x/scratchpad/b",
            "/Users/me/p2",
            "~/.codex/c",
            "/Users/me/p3",
        ]
        let (primary, temporary) = splitPaths(input, home: home)
        XCTAssertEqual(primary, ["/Users/me/p1", "/Users/me/p2", "/Users/me/p3"])
        XCTAssertEqual(temporary, ["/tmp/a", "/Users/me/x/scratchpad/b", "~/.codex/c"])
        XCTAssertTrue(splitPaths([], home: home).primary.isEmpty)
    }
}
