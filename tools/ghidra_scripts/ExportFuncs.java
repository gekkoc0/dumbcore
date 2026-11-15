// Post-analysis: dump every function as one JSON line:
// {"a":entry,"n":name,"sz":bytes,"str":[referenced strings],"calls":[callee entries]}
// Strings are found through references (direct, or via one pointer in a literal pool).
// Script args: <out.jsonl>
// @category nokia3210
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.Reference;
import java.io.*;
import java.util.*;

public class ExportFuncs extends GhidraScript {
    Memory mem;

    String cstr(Address a) {
        try {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 160; i++) {
                int c = mem.getByte(a.add(i)) & 0xff;
                if (c == 0) break;
                if (c < 0x20 && c != 9 && c != 10 && c != 13) return null;
                if (c > 0x7e) return null;
                sb.append((char) c);
            }
            return sb.length() >= 4 ? sb.toString() : null;
        } catch (Exception e) {
            return null;
        }
    }

    static String esc(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
            else b.append(c);
        }
        return b.append('"').toString();
    }

    @Override
    public void run() throws Exception {
        mem = currentProgram.getMemory();
        String out = getScriptArgs()[0];
        Listing L = currentProgram.getListing();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        int n = 0;
        try (PrintWriter w = new PrintWriter(new BufferedWriter(new FileWriter(out)))) {
            for (Function f : L.getFunctions(true)) {
                if (monitor.isCancelled()) break;
                Set<String> strs = new LinkedHashSet<>();
                for (Instruction ins : L.getInstructions(f.getBody(), true)) {
                    for (Reference r : ins.getReferencesFrom()) {
                        Address to = r.getToAddress();
                        if (!to.isMemoryAddress() || !mem.contains(to)) continue;
                        String s = cstr(to);
                        if (s == null) {
                            try {  // literal pool word -> pointer to string
                                long v = mem.getInt(to) & 0xffffffffL;
                                Address p = sp.getAddress(v);
                                if (mem.contains(p)) s = cstr(p);
                            } catch (Exception e) { }
                        }
                        if (s != null) strs.add(s);
                    }
                }
                StringBuilder calls = new StringBuilder();
                for (Function c : f.getCalledFunctions(monitor)) {
                    if (calls.length() > 0) calls.append(',');
                    calls.append('"').append(c.getEntryPoint()).append('"');
                }
                StringBuilder ss = new StringBuilder();
                for (String s : strs) {
                    if (ss.length() > 0) ss.append(',');
                    ss.append(esc(s));
                }
                w.printf("{\"a\":\"%s\",\"n\":%s,\"sz\":%d,\"str\":[%s],\"calls\":[%s]}%n",
                        f.getEntryPoint(), esc(f.getName()), f.getBody().getNumAddresses(), ss, calls);
                n++;
            }
        }
        println("ExportFuncs: " + n + " functions -> " + out);
    }
}
