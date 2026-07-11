// AlloyRun.java — headless driver for the Alloy models (WorkGraph.als, Amendment.als).
//
// Alloy's default `java -jar org.alloytools.alloy.dist.jar` launches the GUI; this driver runs
// every `check`/`run` command in a given .als file through the Alloy Java API (default SAT4J solver,
// -Djava.awt.headless=true) and reports each verdict, so `scripts/run_formal.sh` can machine-check
// the models with no display. A `check` is OK iff it finds NO counterexample; a `run` is OK iff it
// finds an instance. Exit 0 iff every command is as-expected.
//
// D1 (WP-F): the FIRST argument, if numeric, is the EXPECTED total command count. This kills the
// implicit-`Default` hole — an .als stripped of every check/run would otherwise fall back to Alloy's
// implicit `Default` run command and print a vacuous "SUMMARY: 1/1"; asserting the expected count
// (8 for WorkGraph.als + Amendment.als) makes that a hard FAIL.
// D5 (WP-F): Alloy warnings (which the GUI treats as blocking) were silently swallowed by the default
// no-op A4Reporter. We override warning() to print AND count them as failures.
//
// Build tool only (like tla2tools.jar / the Alloy jar) — NOT read at runtime by the skill. Compile
// and run via scripts/run_formal.sh, which fetches the pinned Alloy jar to a cache dir first:
//   javac -cp <alloy.jar> -d <out> formal/AlloyRun.java
//   java -Djava.awt.headless=true -cp <alloy.jar>:<out> AlloyRun 8 formal/WorkGraph.als formal/Amendment.als
import edu.mit.csail.sdg.alloy4.A4Reporter;
import edu.mit.csail.sdg.alloy4.ErrorWarning;
import edu.mit.csail.sdg.ast.Command;
import edu.mit.csail.sdg.ast.Module;
import edu.mit.csail.sdg.parser.CompUtil;
import edu.mit.csail.sdg.translator.A4Options;
import edu.mit.csail.sdg.translator.A4Solution;
import edu.mit.csail.sdg.translator.TranslateAlloyToKodkod;

public class AlloyRun {
    public static void main(String[] args) throws Exception {
        // D1: leading numeric arg = expected total command count (defense against the implicit-Default hole).
        int expectedTotal = -1;
        int argStart = 0;
        if (args.length > 0 && args[0].matches("\\d+")) {
            expectedTotal = Integer.parseInt(args[0]);
            argStart = 1;
        }
        // D5: count Alloy warnings and treat them as failures (they are blocking in the GUI).
        final int[] warnings = {0};
        A4Reporter rep = new A4Reporter() {
            @Override public void warning(ErrorWarning msg) {
                warnings[0]++;
                System.out.println("   [WARN] " + (msg == null ? "(null)" : msg.toString()));
            }
        };
        int fail = 0, total = 0;
        for (int i = argStart; i < args.length; i++) {
            String path = args[i];
            Module world = CompUtil.parseEverything_fromFile(rep, null, path);
            A4Options opts = new A4Options();          // default solver is SAT4J (bundled, pure-Java)
            System.out.println("== " + path + " (" + world.getAllCommands().size() + " commands) ==");
            for (Command cmd : world.getAllCommands()) {
                total++;
                A4Solution sol = TranslateAlloyToKodkod.execute_command(rep, world.getAllReachableSigs(), cmd, opts);
                boolean isCheck = cmd.check;           // check => want NO counterexample; run => want instance
                boolean sat = sol.satisfiable();
                boolean ok;
                String verdict;
                if (isCheck) { ok = !sat; verdict = sat ? "COUNTEREXAMPLE FOUND" : "no counterexample"; }
                else         { ok = sat;  verdict = sat ? "instance found" : "NO INSTANCE"; }
                if (!ok) fail++;
                System.out.printf("   [%s] %-28s -> %s%n", ok ? "OK" : "FAIL", cmd.label, verdict);
            }
        }
        System.out.printf("SUMMARY: %d/%d commands as-expected%n", total - fail, total);
        // D1: hard-fail on a command-count mismatch (implicit-Default / stripped-commands guard).
        boolean countOk = (expectedTotal < 0) || (total == expectedTotal);
        if (!countOk) {
            System.out.printf("   [FAIL] expected %d command(s) but ran %d — the model may have lost commands "
                    + "or fell back to Alloy's implicit Default run%n", expectedTotal, total);
        }
        // D5: any warning is a hard failure.
        if (warnings[0] > 0) {
            System.out.printf("   [FAIL] %d Alloy warning(s) (blocking in the GUI) — treated as failure%n", warnings[0]);
        }
        System.exit((fail == 0 && countOk && warnings[0] == 0) ? 0 : 1);
    }
}
