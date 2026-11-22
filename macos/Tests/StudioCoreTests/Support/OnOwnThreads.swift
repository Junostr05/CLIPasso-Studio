import StudioCore
import Testing

/// Runs a test on threads of its own (OwnThreads): the pixel tests compute in a debug build for many seconds, and on
/// the cooperative pool – a thread per core – they would leave nothing for the tests that wait on time (an engine
/// request's timeout, a download), whose timers could then not fire.
struct OnOwnThreads: TestTrait, SuiteTrait, TestScoping {
    var isRecursive: Bool { true }

    /// Around each test case – the body itself – not around the suite.
    func scopeProvider(for test: Test, testCase: Test.Case?) -> Self? { testCase == nil ? nil : self }

    func provideScope(for test: Test, testCase: Test.Case?,
                      performing function: @Sendable () async throws -> Void) async throws
    {
        try await withTaskExecutorPreference(OwnThreads.shared) { try await function() }
    }
}

extension Trait where Self == OnOwnThreads {
    static var onOwnThreads: Self { OnOwnThreads() }
}
