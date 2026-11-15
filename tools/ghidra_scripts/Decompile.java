// Decompile functions to C. Script args: <out_dir> <hexaddr> [<hexaddr> ...]
// Each function goes to <out_dir>/<addr>.c (creates the function if missing).
// @category nokia3210
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.*;

public class Decompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        File dir = new File(a[0]);
        dir.mkdirs();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (int i = 1; i < a.length; i++) {
            Address ad = toAddr(Long.parseLong(a[i].replace("0x", ""), 16));
            Function f = getFunctionContaining(ad);
            if (f == null) f = createFunction(ad, null);
            if (f == null) { println("no function at " + ad); continue; }
            DecompileResults r = di.decompileFunction(f, 120, monitor);
            String c = r.decompileCompleted() ? r.getDecompiledFunction().getC() : ("// failed: " + r.getErrorMessage());
            try (PrintWriter w = new PrintWriter(new File(dir, f.getEntryPoint() + ".c"))) { w.print(c); }
            println("decompiled " + f.getEntryPoint() + " (" + f.getName() + ")");
        }
        di.dispose();
    }
}
