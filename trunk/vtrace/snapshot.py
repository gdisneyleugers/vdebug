"""
All the code related to vtrace process snapshots
and TraceSnapshot classes.
"""

import vtrace
import vtrace.platforms.base as v_base

class TraceSnapshot(v_base.TracerBase):
    """
    A tracer snapshot is similar to a traditional "core file" except that
    you may also have memory only snapshots that are never written to disk.

    TraceSnapshots allow you to take a picture of a process from a given point
    in it's execution and manipulate/test from there or save it to disk for later
    analysis...
    """
    def __init__(self, filename=None, snapdict=None):
        Trace.__init__(self)
        if filename == None and snapdict == None:
            raise Exception("ERROR: TraceSnapshot needs either filename or snapdict!")

        if filename:
            sfile = file(filename, "rb")
            snapdict = pickle.load(sfile)

        self.s_snapcache = {}
        self.s_snapdict = snapdict

        # a seperate parser for each version...
        if snapdict['version'] == 1:
            self.s_version = snapdict['version']
            self.s_threads = snapdict['threads']
            self.s_regs = snapdict['regs']
            self.s_maps = snapdict['maps']
            self.s_mem = snapdict['mem']
            self.metadata = snapdict['meta']
            self.s_stacktrace = snapdict['stacktrace']
            self.s_exe = snapdict['exe']
            self.s_fds = snapdict['fds']
            self.localvars = snapdict.get('vars', {})
        else:
            raise Exception("ERROR: Unknown snapshot version!")

        #FIXME hard-coded page size!
        self.s_map_lookup = {}
        for map in self.s_maps:
            for i in range(map[0],map[0] + map[1], 4096):
                self.s_map_lookup[i] = map

        self.attached = True
        # So that we pickle
        self.bplock = None
        self.thread = None

        #FIXME maybe self.arch is NOT the same as real platform...

    def saveToFile(self, filename):
        """
        Save a snapshot to file for later reading in...
        """
        #import zlib
        f = file(filename, "wb")
        pickle.dump(self.s_snapdict, f)
        #f.write(zlib.compress(rawbytes))
        f.close()

    def getMemoryMap(self, addr):
        base = addr & 0xfffff000
        return self.s_map_lookup.get(base, None)

    def platformGetFds(self):
        return self.s_fds

    def getExe(self):
        return self.s_exe

    def getStackTrace(self):
        tid = self.getMeta("ThreadId")
        tr = self.s_stacktrace.get(tid, None)
        if tr == None:
            raise Exception("ERROR: Invalid thread id specified")
        return tr

    def platformGetMaps(self):
        return self.s_maps

    def platformGetThreads(self):
        return self.s_threads

    def platformReadMemory(self, address, size):
        map = self.getMemoryMap(address)
        if map == None:
            raise Exception("ERROR: platformReadMemory says no map for 0x%.8x" % address)
        offset = address - map[0] # Base address
        mapbytes = self.s_mem.get(map[0], None)
        if mapbytes == None:
            raise vtrace.PlatformException("ERROR: Memory map at 0x%.8x is not backed!" % map[0])
        if len(mapbytes) == 0:
            raise vtrace.PlatformException("ERROR: Memory Map at 0x%.8x is backed by ''" % map[0])

        ret = mapbytes[offset:offset+size]
        rlen = len(ret)
        # We may have a cross-map read, just recurse for the rest
        if rlen != size:
            ret += self.platformReadMemory(address+rlen, size-rlen)
        return ret

    def platformWriteMemory(self, address, bytes):
        map = self.getMemoryMap(address)
        if map == None:
            raise Exception("ERROR: platformWriteMemory says no map for 0x%.8x" % address)
        offset = address - map[0]
        mapbytes = self.s_mem[map[0]]
        self.s_mem[map[0]] = mapbytes[:offset] + bytes + mapbytes[offset+len(bytes):]

    def platformDetach(self):
        pass

    # Over-ride register *caching* subsystem to store/retrieve
    # register information in pure dictionaries
    def cacheRegs(self, threadid):
        pass

    # FIXME regs in snapshots are broke...

    def syncRegs(self):
        pass


def takeSnapshot(trace):
    """
    Take a snapshot of the process from the current state and return
    a reference to a tracer which wraps a "snapshot" or "core file".
    """
    sd = dict()
    orig_thread = trace.getMeta("ThreadId")

    regs = dict()
    stacktrace = dict()

    for thrid,tdata in trace.getThreads().items():
        trace.selectThread(thrid)
        regs[thrid] = trace.getRegisters()
        try:
            stacktrace[thrid] = trace.getStackTrace()
        except Exception, msg:
            print >> sys.stderr, "WARNING: Failed to get stack trace for thread 0x%.8x" % thrid

    if orig_thread != -1:
        trace.selectThread(orig_thread)

    mem = dict()
    maps = []
    for base,size,perms,fname in trace.getMemoryMaps():
        try:
            mem[base] = trace.readMemory(base, size)
            maps.append((base,size,perms,fname))
        except Exception, msg:
            print >> sys.stderr, "WARNING: Can't snapshot memmap at 0x%.8x (%s)" % (base,msg)

    # If the contents here change, change the version...
    sd['version'] = 1
    sd['threads'] = trace.getThreads()
    sd['regs'] = regs
    sd['maps'] = maps
    sd['mem'] = mem
    sd['meta'] = copy.deepcopy(trace.metadata)
    sd['stacktrace'] = stacktrace
    sd['exe'] = trace.getExe()
    sd['fds'] = trace.getFds()
    sd['vars'] = trace.localvars

    return TraceSnapshot(snapdict=sd)

