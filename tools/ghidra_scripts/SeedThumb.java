// Pre-analysis: mark the whole raw image as Thumb and create functions at seed addresses.
// Script args: <seeds.txt> (hex addresses, one per line)
// @category nokia3210
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.mem.MemoryBlock;
import java.math.BigInteger;
import java.nio.file.*;
import java.util.*;

public class SeedThumb extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Register tmode = currentProgram.getRegister("TMode");
        ProgramContext ctx = currentProgram.getProgramContext();
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            ctx.setValue(tmode, b.getStart(), b.getEnd(), BigInteger.ONE);
        }
        List<String> lines = Files.readAllLines(Paths.get(args[0]));
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        AddressSet set = new AddressSet();
        List<Address> seeds = new ArrayList<>();
        for (String l : lines) {
            l = l.trim();
            if (l.isEmpty()) continue;
            Address a = sp.getAddress(Long.parseLong(l, 16));
            seeds.add(a);
            set.add(a);
        }
        DisassembleCommand dis = new DisassembleCommand(set, null, true);
        dis.applyTo(currentProgram, monitor);
        int made = 0;
        for (Address a : seeds) {
            if (monitor.isCancelled()) break;
            if (getFunctionAt(a) != null) continue;
            CreateFunctionCmd cf = new CreateFunctionCmd(a);
            if (cf.applyTo(currentProgram, monitor)) made++;
        }
        println("SeedThumb: seeds " + seeds.size() + ", functions created " + made);
    }
}
