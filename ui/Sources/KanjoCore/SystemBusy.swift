import Foundation

public enum SystemBusy {
    public static func isBusy(thermalState: ProcessInfo.ThermalState, loadAverage: Double, cores: Int) -> Bool {
        if thermalState == .serious || thermalState == .critical {
            return true
        }
        return loadAverage > Double(cores)
    }
}
