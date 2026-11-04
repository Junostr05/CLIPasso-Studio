import Testing
@testable import StudioCore

/// The matrix of a SceneSketch job: columns of layers, rows of levels, from the cells (settings_schema.scene_cell_id).
@Suite struct SceneMatrixTests {
    @Test func layersAcrossLevelsDown() throws {
        let matrix = try #require(SceneMatrix(cells: [1104, 800, 204, 1100, 804, 200, 808]))
        #expect(matrix.layers == [2, 8, 11] && matrix.levels == [0, 4, 8])
        #expect(matrix.contains(layer: 8, level: 8) && !matrix.contains(layer: 2, level: 8))  // (not every cell is there)
        #expect(SceneMatrix.cell(layer: 11, level: 4) == 1104)
        #expect(SceneMatrix.split(1104).layer == 11 && SceneMatrix.split(1104).level == 4)
        #expect(SceneMatrix.split(800).layer == 8 && SceneMatrix.split(800).level == 0)
    }

    @Test func onlyCellsMakeAMatrix() {
        #expect(SceneMatrix(cells: []) == nil)
        #expect(SceneMatrix(cells: [0, 1000, 2000]) == nil)  // the seeds of a CLIPasso job (the result asks the method too)
        #expect(SceneMatrix(cells: [800, 7]) == nil)
    }
}
