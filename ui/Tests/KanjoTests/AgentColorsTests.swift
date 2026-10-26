import XCTest
@testable import KanjoCore

final class AgentColorsTests: KanjoTestCase {
    private struct Lab {
        let l: Double
        let a: Double
        let b: Double
    }

    private static func srgbToLab(_ hex: UInt32) -> Lab {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0

        func invGamma(_ c: Double) -> Double {
            c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }

        let rL = invGamma(r)
        let gL = invGamma(g)
        let bL = invGamma(b)

        let x = rL * 0.4124564 + gL * 0.3575761 + bL * 0.1804375
        let y = rL * 0.2126729 + gL * 0.7151522 + bL * 0.0721750
        let z = rL * 0.0193339 + gL * 0.1191920 + bL * 0.9503041

        // D65 reference white
        let xn = 0.95047
        let yn = 1.00000
        let zn = 1.08883

        let delta = 6.0 / 29.0
        let delta3 = delta * delta * delta

        func f(_ t: Double) -> Double {
            t > delta3 ? cbrt(t) : (t / (3.0 * delta * delta)) + (4.0 / 29.0)
        }

        let fx = f(x / xn)
        let fy = f(y / yn)
        let fz = f(z / zn)

        let l = 116.0 * fy - 16.0
        let aVal = 500.0 * (fx - fy)
        let bVal = 200.0 * (fy - fz)

        return Lab(l: l, a: aVal, b: bVal)
    }

    private static func ciede2000(_ c1: Lab, _ c2: Lab, kL: Double = 1.0, kC: Double = 1.0, kH: Double = 1.0) -> Double {
        let L1 = c1.l, a1 = c1.a, b1 = c1.b
        let L2 = c2.l, a2 = c2.a, b2 = c2.b

        let C1 = sqrt(a1 * a1 + b1 * b1)
        let C2 = sqrt(a2 * a2 + b2 * b2)
        let cBar = (C1 + C2) / 2.0

        let cBar7 = pow(cBar, 7.0)
        let g = 0.5 * (1.0 - sqrt(cBar7 / (cBar7 + pow(25.0, 7.0))))

        let a1Prime = (1.0 + g) * a1
        let a2Prime = (1.0 + g) * a2

        let C1Prime = sqrt(a1Prime * a1Prime + b1 * b1)
        let C2Prime = sqrt(a2Prime * a2Prime + b2 * b2)

        func hueAngle(b: Double, aPrime: Double) -> Double {
            if b == 0.0 && aPrime == 0.0 { return 0.0 }
            let deg = atan2(b, aPrime) * 180.0 / .pi
            return deg >= 0 ? deg : deg + 360.0
        }

        let h1Prime = hueAngle(b: b1, aPrime: a1Prime)
        let h2Prime = hueAngle(b: b2, aPrime: a2Prime)

        let deltaLPrime = L2 - L1
        let deltaCPrime = C2Prime - C1Prime

        let deltaHPrimeAngle: Double
        if C1Prime * C2Prime == 0.0 {
            deltaHPrimeAngle = 0.0
        } else if abs(h2Prime - h1Prime) <= 180.0 {
            deltaHPrimeAngle = h2Prime - h1Prime
        } else if (h2Prime - h1Prime) > 180.0 {
            deltaHPrimeAngle = (h2Prime - h1Prime) - 360.0
        } else {
            deltaHPrimeAngle = (h2Prime - h1Prime) + 360.0
        }

        let deltaHPrime = 2.0 * sqrt(C1Prime * C2Prime) * sin((deltaHPrimeAngle / 2.0) * .pi / 180.0)

        let lBarPrime = (L1 + L2) / 2.0
        let cBarPrime = (C1Prime + C2Prime) / 2.0

        let hBarPrime: Double
        if C1Prime * C2Prime == 0.0 {
            hBarPrime = h1Prime + h2Prime
        } else if abs(h1Prime - h2Prime) <= 180.0 {
            hBarPrime = (h1Prime + h2Prime) / 2.0
        } else if (h1Prime + h2Prime) < 360.0 {
            hBarPrime = (h1Prime + h2Prime + 360.0) / 2.0
        } else {
            hBarPrime = (h1Prime + h2Prime - 360.0) / 2.0
        }

        let degToRad = Double.pi / 180.0
        let t = 1.0 - 0.17 * cos((hBarPrime - 30.0) * degToRad)
                    + 0.24 * cos(2.0 * hBarPrime * degToRad)
                    + 0.32 * cos((3.0 * hBarPrime + 6.0) * degToRad)
                    - 0.20 * cos((4.0 * hBarPrime - 63.0) * degToRad)

        let deltaTheta = 30.0 * exp(-pow((hBarPrime - 275.0) / 25.0, 2.0))
        let cBarPrime7 = pow(cBarPrime, 7.0)
        let rC = 2.0 * sqrt(cBarPrime7 / (cBarPrime7 + pow(25.0, 7.0)))
        let sL = 1.0 + (0.015 * pow(lBarPrime - 50.0, 2.0)) / sqrt(20.0 + pow(lBarPrime - 50.0, 2.0))
        let sC = 1.0 + 0.045 * cBarPrime
        let sH = 1.0 + 0.015 * cBarPrime * t
        let rT = -sin(2.0 * deltaTheta * degToRad) * rC

        let termL = deltaLPrime / (kL * sL)
        let termC = deltaCPrime / (kC * sC)
        let termH = deltaHPrime / (kH * sH)

        return sqrt(termL * termL + termC * termC + termH * termH + rT * termC * termH)
    }

    func testLightColorsPairwiseCIEDE2000() {
        let entries = AgentColors.all.sorted { $0.key < $1.key }
        for i in 0..<entries.count {
            for j in (i + 1)..<entries.count {
                let a1 = entries[i]
                let a2 = entries[j]
                let lab1 = Self.srgbToLab(a1.value.light)
                let lab2 = Self.srgbToLab(a2.value.light)
                let de = Self.ciede2000(lab1, lab2)
                XCTAssertGreaterThanOrEqual(
                    de, 12.0,
                    "Light CIEDE2000 between \(a1.key) (#\(String(format: "%06X", a1.value.light))) and \(a2.key) (#\(String(format: "%06X", a2.value.light))) must be >= 12, got \(de)"
                )
            }
        }
    }

    func testLightColorsVsNeutralCIEDE2000() {
        let neutralLab = Self.srgbToLab(AgentColors.neutralLight)
        for (agent, pair) in AgentColors.all {
            let lab = Self.srgbToLab(pair.light)
            let de = Self.ciede2000(lab, neutralLab)
            XCTAssertGreaterThanOrEqual(
                de, 20.0,
                "Light CIEDE2000 between \(agent) (#\(String(format: "%06X", pair.light))) and neutral light (#\(String(format: "%06X", AgentColors.neutralLight))) must be >= 20, got \(de)"
            )
        }
    }

    func testDarkColorsPairwiseCIEDE2000() {
        let entries = AgentColors.all.sorted { $0.key < $1.key }
        for i in 0..<entries.count {
            for j in (i + 1)..<entries.count {
                let a1 = entries[i]
                let a2 = entries[j]
                let lab1 = Self.srgbToLab(a1.value.dark)
                let lab2 = Self.srgbToLab(a2.value.dark)
                let de = Self.ciede2000(lab1, lab2)
                XCTAssertGreaterThanOrEqual(
                    de, 12.0,
                    "Dark CIEDE2000 between \(a1.key) (#\(String(format: "%06X", a1.value.dark))) and \(a2.key) (#\(String(format: "%06X", a2.value.dark))) must be >= 12, got \(de)"
                )
            }
        }
    }

    func testDarkColorsVsNeutralCIEDE2000() {
        let neutralLab = Self.srgbToLab(AgentColors.neutralDark)
        for (agent, pair) in AgentColors.all {
            let lab = Self.srgbToLab(pair.dark)
            let de = Self.ciede2000(lab, neutralLab)
            XCTAssertGreaterThanOrEqual(
                de, 20.0,
                "Dark CIEDE2000 between \(agent) (#\(String(format: "%06X", pair.dark))) and neutral dark (#\(String(format: "%06X", AgentColors.neutralDark))) must be >= 20, got \(de)"
            )
        }
    }
}
