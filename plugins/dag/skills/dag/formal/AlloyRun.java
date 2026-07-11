// AlloyRun.java — headless driver for the Alloy models (WorkGraph.als, Amendment.als).
//
// Alloy's default `java -jar org.alloytools.alloy.dist.jar` launches the GUI; this driver runs
// every `check`/`run` command in a given .als file through the Alloy Java API (default SAT4J solver,
// -Djava.awt.headless=true) and reports each verdict, so `scripts/run_formal.sh` can machine-check
// the models with no display. A `check` is OK iff it finds NO counterexample; a `run` is OK iff it
// finds an instance. Exit 0 iff every command is as-expected.
//
// Build tool only (like tla2tools.jar / the Alloy jar) — NOT read at runtime by the skill. Compile
// and run via scripts/run_formal.sh, which fetches the pinned Alloy jar to a cache dir first:
//   javac -cp <alloy.jar> -d <out> formal/AlloyRun.java
//   java -Djava.awt.headless=true -cp <alloy.jar>:<out> AlloyRun formal/WorkGraph.als formal/Amendment.als
import edu.mit.csail.sdg.alloy4.A4Reporter;
import edu.mit.csail.sdg.ast.Command;
import edu.mit.csail.sdg.ast.Module;
import edu.mit.csail.sdg.parser.CompUtil;
import edu.mit.csail.sdg.translator.A4Options;
import edu.mit.csail.sdg.translator.A4Solution;
import edu.mit.csail.sdg.translator.TranslateAlloyToKodkod;

public class AlloyRun {
    public static void main(String[] args) throws Exception {
        A4Reporter rep = new A4Reporter();
        int fail = 0, total = 0;
        for (String path : args) {
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
        System.exit(fail == 0 ? 0 : 1);
    }
}
