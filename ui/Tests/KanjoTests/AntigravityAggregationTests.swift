import XCTest
@testable import KanjoCore

final class AntigravityAggregationTests: XCTestCase {
    func testAggregation() {
        let acc1 = AntigravityAccount(email: "a@test.com", tokens: 100, costUsd: 10.0, messages: 1, 
                                     plan: AntigravityAccountPlan(plan: "pro", planLabel: "Pro", monthlyPriceUsd: 20.0))
        let acc2 = AntigravityAccount(email: "b@test.com", tokens: 100, costUsd: 10.0, messages: 1, 
                                     plan: AntigravityAccountPlan(plan: "pro", planLabel: "Pro", monthlyPriceUsd: 20.0))
        let acc3 = AntigravityAccount(email: "c@test.com", tokens: 100, costUsd: 10.0, messages: 1, 
                                     plan: AntigravityAccountPlan(plan: "ultra", planLabel: "Ultra", monthlyPriceUsd: 200.0))
        
        let agg = AntigravityAggregation.aggregate(accounts: [acc1, acc2, acc3])
        
        XCTAssertNotNil(agg)
        XCTAssertEqual(agg!.accountsPriced, 3)
        XCTAssertEqual(agg!.monthlyPriceUsd, 240.0)
        XCTAssertEqual(agg!.plan, "multi")
        XCTAssertTrue(agg!.planLabel.contains("Pro ×2"))
        XCTAssertTrue(agg!.planLabel.contains("Ultra"))
    }
    
    func testNoneHandling() {
        let acc1 = AntigravityAccount(email: "a@test.com", tokens: 100, costUsd: 10.0, messages: 1, 
                                     plan: AntigravityAccountPlan(plan: "none", planLabel: "None", monthlyPriceUsd: 0.0))
        
        let agg = AntigravityAggregation.aggregate(accounts: [acc1])
        XCTAssertNil(agg)
    }
}
