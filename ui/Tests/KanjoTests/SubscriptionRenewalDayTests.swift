import XCTest
@testable import KanjoCore

final class SubscriptionRenewalDayTests: KanjoTestCase {
  private func sub(
    anchorDay: Int?, cycleSource: String, source: String = "detected"
  ) -> Subscription {
    Subscription(
      plan: "pro", planLabel: "Pro", monthlyPriceUsd: 20,
      cycleStart: "2026-01-31T00:00:00Z", cycleEnd: "2026-03-01T00:00:00Z",
      anchorDay: anchorDay, cycleSource: cycleSource,
      extraUsageEnabled: false, source: source)
  }

  func testDetectedAnchor31IsNotStepperClamped() {
    let s = sub(anchorDay: 31, cycleSource: "subscription_date")
    XCTAssertTrue(SubscriptionRenewalDay.isDetectedHighAnchor(s))
    XCTAssertFalse(SubscriptionRenewalDay.allowsManualStepper(s))
    XCTAssertEqual(SubscriptionRenewalDay.stepperValue(anchorDay: 31), 28)
  }

  func testManualAnchor31IsSteppable() {
    let s = sub(anchorDay: 31, cycleSource: "manual", source: "manual")
    XCTAssertFalse(SubscriptionRenewalDay.isDetectedHighAnchor(s))
    XCTAssertTrue(SubscriptionRenewalDay.allowsManualStepper(s))
  }

  func testManualOverrideWithinRange() {
    XCTAssertEqual(SubscriptionRenewalDay.stepperValue(anchorDay: 15), 15)
    XCTAssertTrue(SubscriptionRenewalDay.allowsManualStepper(sub(anchorDay: 15, cycleSource: "manual", source: "manual")))
  }
}