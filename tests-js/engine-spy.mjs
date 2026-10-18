// The loaded solver with a spy on its models, for the tests of the sessions (engine-solve, engine-path). `spyOn(highs, hooks)` gives a solver that behaves as
// `highs` does and a log of what the sessions asked of it:
//
//   log.created   the number of models made, and log.createdAt the clock when each was made
//   log.limits    every time limit set: `{at, limitMs}` (`at` is what `clock()` read when the limit was set)
//   log.runs      every run: `{at, limitMs}` (the clock when it began, and the limit it had)
//   log.starts    every solution offered as a start, as given to `setSolution`
//
// `hooks` are for a test that moves the clock or puts something in the answer:
//
//   clock()                                      the clock of the log (default: 0)
//   created(solver)                              a model has been made
//   before(run, callbacks, solver), after(run)   around each run (a fake clock moves in `before`, or the test fires a callback event, or sets an option of
//                                                the solver)
//   outcome(outcome, run)                        may return another outcome than the run's (a run that ended optimal can be made to look as one that ran out
//                                                of time)
//   solution(solution)                           may return another solution than the solver's own
//   info(key, value)                             may return another value than the solver's for an entry of its run info (`primal_solution_status`, say:
//                                                a run that ended at its time limit can be made to look as one that had no solution)
//
// Nothing here is read by the site.

export function spyOn(highs, { clock = () => 0, created = () => {}, before = () => {}, after = () => {}, outcome = null, solution = null, info = null } = {}) {
  const log = { created: 0, createdAt: [], limits: [], runs: [], starts: [] };
  const bound = (target, name) => {
    const member = target[name];
    return typeof member === "function" ? member.bind(target) : member;
  };
  const wrapped = Object.create(highs, {
    createModel: {
      value(data) {
        const solver = highs.createModel(data);
        log.created += 1;
        log.createdAt.push(clock());
        created(solver);
        let limitMs = null;
        const options = new Proxy(solver.options, {
          get(target, name) {
            if (name !== "set") return bound(target, name);
            return (key, value) => {
              if (key === "time_limit") {
                limitMs = value * 1000;
                log.limits.push({ at: clock(), limitMs });
              }
              return target.set(key, value);
            };
          },
        });
        const runInfo = new Proxy(solver.info, {
          get(target, name) {
            if (name !== "get") return bound(target, name);
            return (key) => (info === null ? target.get(key) : info(key, target.get(key)));
          },
        });
        return new Proxy(solver, {
          get(target, name) {
            if (name === "options") return options;
            if (name === "info") return runInfo;
            if (name === "setSolution") {
              return (start) => {
                log.starts.push(start);
                return target.setSolution(start);
              };
            }
            if (name === "getSolution") return () => (solution === null ? target.getSolution() : solution(target.getSolution()));
            if (name === "run") {
              return (callbacks) => {
                const run = { at: clock(), limitMs };
                log.runs.push(run);
                before(run, callbacks, target);
                const result = target.run(callbacks);
                after(run);
                return outcome === null ? result : outcome(result, run);
              };
            }
            return bound(target, name);
          },
        });
      },
    },
  });
  return { highs: wrapped, log };
}
