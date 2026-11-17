import Dispatch

/// An executor for long computations – frames, papers, pages: each piece of work on a thread of its own instead of
/// the cooperative pool. The pool has a thread per core; a few minutes of pixels on it would leave nothing for the
/// work that waits on time – the engine's answers and timeouts, the downloads.
///
///     Task.detached(executorPreference: OwnThreads.shared) { try AnimationExporter.gif(job, to: url) }
public final class OwnThreads: TaskExecutor {
    public static let shared = OwnThreads()

    public func enqueue(_ job: consuming ExecutorJob) {
        let job = UnownedJob(job)
        let executor = asUnownedTaskExecutor()
        // (a serial queue of its own: it gets a thread even while every thread of the pool computes)
        DispatchQueue(label: "clipasso.own-thread", qos: .userInitiated).async {
            job.runSynchronously(on: executor)
        }
    }
}
