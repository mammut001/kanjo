import XCTest
@testable import KanjoCore

final class ProjectPrefsTests: KanjoTestCase {
    func testParse() {
        XCTAssertEqual(ProjectPrefs.parse(""), [])
        XCTAssertEqual(ProjectPrefs.parse("a\nb\n\n  c  \r\nb\n"), ["a", "b", "c"])
        XCTAssertEqual(ProjectPrefs.parse("/Users/me/My Repo\ngithub.com/x/y"), ["/Users/me/My Repo", "github.com/x/y"])
    }

    func testSerializeIsSortedAndRoundTrips() {
        let s: Set<String> = ["github.com/b", "/local/a", "github.com/a"]
        XCTAssertEqual(ProjectPrefs.serialize(s), "/local/a\ngithub.com/a\ngithub.com/b")
        XCTAssertEqual(ProjectPrefs.parse(ProjectPrefs.serialize(s)), s)
        XCTAssertEqual(ProjectPrefs.serialize([]), "")
    }

    func testToggle() {
        XCTAssertEqual(ProjectPrefs.toggle("a", in: Set<String>()), ["a"])
        XCTAssertEqual(ProjectPrefs.toggle("a", in: ["a", "b"] as Set<String>), ["b"])
        XCTAssertEqual(ProjectPrefs.toggle("c", in: "a\nb"), "a\nb\nc")
        XCTAssertEqual(ProjectPrefs.toggle("a", in: "a\nb"), "b")
        XCTAssertEqual(ProjectPrefs.toggle("a", in: "a"), "")
    }

    func testArrange() {
        let items = ["p1", "p2", "p3", "p4", "p5"]
        let r = ProjectPrefs.arrange(items, id: { $0 }, pinned: ["p4", "p2", "p5"], hidden: ["p3", "p5"])
        XCTAssertEqual(r.visible, ["p2", "p4", "p1"])   // 置顶在前、各自保持原顺序；隐藏优先于置顶
        XCTAssertEqual(r.hidden, ["p3", "p5"])
        let none = ProjectPrefs.arrange(items, id: { $0 }, pinned: [], hidden: [])
        XCTAssertEqual(none.visible, items)
        XCTAssertTrue(none.hidden.isEmpty)
    }
}
