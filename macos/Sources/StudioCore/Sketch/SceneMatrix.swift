import Foundation

/// SceneSketch's abstraction matrix (gui/widgets/canvas.MatrixView): one column per fidelity layer (L2, L8, L11 …),
/// one row per simplicity level (0, the sketch most like the image, then the simpler ones). A cell is the job's item
/// `layer * 100 + level` (settings_schema.scene_cell_id) – the seed of its run. The rows and columns are those of the
/// cells there are, so the rules of which ones a job computes stay in Python.
public struct SceneMatrix: Sendable, Equatable {
    public let layers: [Int]
    public let levels: [Int]
    public let cells: Set<Int>

    /// settings_schema.scene_cell_id
    public static func cell(layer: Int, level: Int) -> Int { layer * 100 + level }

    public static func split(_ cell: Int) -> (layer: Int, level: Int) { (cell / 100, cell % 100) }

    /// nil when there are no cells, or a seed is no cell (below 100: no layer).
    public init?(cells: [Int]) {
        guard !cells.isEmpty, cells.allSatisfy({ $0 >= 100 }) else { return nil }
        self.cells = Set(cells)
        layers = Set(cells.map { Self.split($0).layer }).sorted()
        levels = Set(cells.map { Self.split($0).level }).sorted()
    }

    public func contains(layer: Int, level: Int) -> Bool { cells.contains(Self.cell(layer: layer, level: level)) }
}
