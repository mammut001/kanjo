import XCTest
@testable import KanjoCore

final class BackgroundRefreshTests: XCTestCase {
    func testSystemBusyDetection() {
        // Not busy
        XCTAssertFalse(SystemBusy.isBusy(thermalState: .nominal, loadAverage: 2.0, cores: 4))
        
        // Busy by thermal
        XCTAssertTrue(SystemBusy.isBusy(thermalState: .serious, loadAverage: 1.0, cores: 4))
        XCTAssertTrue(SystemBusy.isBusy(thermalState: .critical, loadAverage: 1.0, cores: 4))
        
        // Busy by load
        XCTAssertTrue(SystemBusy.isBusy(thermalState: .nominal, loadAverage: 5.0, cores: 4))
    }
    
    func testBackgroundRefreshIntervalResolve() {
        XCTAssertEqual(BackgroundRefreshInterval.resolve(30), .s30)
        XCTAssertEqual(BackgroundRefreshInterval.resolve(60), .s60)
        XCTAssertEqual(BackgroundRefreshInterval.resolve(300), .s300)
        XCTAssertEqual(BackgroundRefreshInterval.resolve(600), .s600)
        
        // Unknown defaults to 60
        XCTAssertEqual(BackgroundRefreshInterval.resolve(0), .s60)
        XCTAssertEqual(BackgroundRefreshInterval.resolve(999), .s60)
    }
}