
"""
The guts for the i386 envi opcode disassembler.
"""

import struct

import envi
import envi.bits as e_bits

import opcode86
all_tables = opcode86.tables86

# Grab our register enums etc...
from envi.archs.i386.regs import *

# Our instruction prefix masks
# NOTE: table 3-4 (section 3.6) of intel 1 shows how REX/OP_SIZE
# interact...
INSTR_PREFIX=      0x0001
PREFIX_LOCK =      0x0002
PREFIX_REPNZ=      0x0004
PREFIX_REPZ =      0x0008
PREFIX_REP  =      0x0010
PREFIX_REP_SIMD=   0x0020
PREFIX_OP_SIZE=    0x0040
PREFIX_ADDR_SIZE=  0x0080
PREFIX_SIMD=       0x0100
PREFIX_CS  =       0x0200
PREFIX_SS  =       0x0400
PREFIX_DS  =       0x0800
PREFIX_ES  =       0x1000
PREFIX_FS  =       0x2000
PREFIX_GS  =       0x4000
PREFIX_REG_MASK=   0x8000

# envi.registers meta offsets
RMETA_LOW8  = 0x00080000
RMETA_HIGH8 = 0x08080000
RMETA_LOW16 = 0x00100000

# Use a list here instead of a dict for speed (max 255 anyway)
i386_prefixes = [ None for i in range(256) ]
i386_prefixes[0xF0] = PREFIX_LOCK
i386_prefixes[0xF2] = PREFIX_REPNZ
i386_prefixes[0xF3] = PREFIX_REP
i386_prefixes[0x2E] = PREFIX_CS
i386_prefixes[0x36] = PREFIX_SS
i386_prefixes[0x3E] = PREFIX_DS
i386_prefixes[0x26] = PREFIX_ES
i386_prefixes[0x64] = PREFIX_FS
i386_prefixes[0x65] = PREFIX_GS
i386_prefixes[0x66] = PREFIX_OP_SIZE
i386_prefixes[0x67] = PREFIX_ADDR_SIZE

# The scale byte index into this for multiplier imm
scale_lookup = (1, 2, 4, 8)

# A set of instructions that are considered privileged (mark with IF_PRIV)
# FIXME this should be part of the opcdode tables!
priv_lookup = {
    "int":True,
    "in":True,
    "out":True,
    "insb":True,
    "outsb":True,
    "insd":True,
    "outsd":True,
    "vmcall":True,
    "vmlaunch":True,
    "vmresume":True,
    "vmxoff":True,
    "vmread":True,
    "vmwrite":True,
    "rsm":True,
    "lar":True,
    "lsl":True,
    "clts":True,
    "invd":True,
    "wbinvd":True,
    "wrmsr":True,
    "rdmsr":True,
    "sysexit":True,
    "lgdt":True,
    "lidt":True,
    "lmsw":True,
    "monitor":True,
    "mwait":True,
    "vmclear":True,
    "vmptrld":True,
    "vmptrst":True,
    "vmxon":True,
}

# Map of codes to their respective envi flags
iflag_lookup = {
    opcode86.INS_RET: envi.IF_NOFALL|envi.IF_RET,
    opcode86.INS_CALL: envi.IF_CALL,
    opcode86.INS_CALLCC: envi.IF_CALL,
    opcode86.INS_BRANCH: envi.IF_NOFALL | envi.IF_BRANCH,
    opcode86.INS_BRANCHCC: envi.IF_BRANCH,
}

sizenames = ["" for x in range(17)]
sizenames[1] = "byte"
sizenames[2] = "word"
sizenames[4] = "dword"
sizenames[8] = "qword"
sizenames[16] = "oword"

# Printable prefix names
prefix_names = [
    (PREFIX_LOCK, "lock"),
    (PREFIX_REPNZ, "repnz"),
    (PREFIX_REP, "rep"),
    (PREFIX_CS, "cs"),
    (PREFIX_SS, "ss"),
    (PREFIX_DS, "ds"),
    (PREFIX_ES, "es"),
    (PREFIX_FS, "fs"),
    (PREFIX_GS, "gs"),
]

def addrToName(mcanv, va):
    sym = mcanv.syms.getSymByAddr(va)
    if sym != None:
        return repr(sym)
    return "0x%.8x" % va

###########################################################################
#
# Operand objects for the i386 architecture
#


class i386RegOper(envi.Operand):

    def __init__(self, reg, tsize):
        self.reg = reg
        self.tsize = tsize

    def repr(self, op):
        return self._dis_regctx.getRegisterName(self.reg)

    def getOperValue(self, op, emu=None):
        if emu == None: return None # This operand type requires an emulator
        return emu.getRegister(self.reg)

    def setOperValue(self, op, emu, value):
        emu.setRegister(self.reg, value)

    def render(self, mcanv, op, idx):
        hint = mcanv.syms.getSymHint(op.va, idx)
        if hint != None:
            mcanv.addNameText(name, typename="registers")
        else:
            name = self._dis_regctx.getRegisterName(self.reg)
            mcanv.addNameText(name, typename="registers")

    def __eq__(self, other):
        if not isinstance(other, i386RegOper):
            return False
        if other.reg != self.reg:
            return False
        if other.tsize != self.tsize:
            return False
        return True

# For opcodes which need their immediate extended on print
sextend = [opcode86.INS_ADD, opcode86.INS_SUB, opcode86.INS_AND]

class i386ImmOper(envi.Operand):
    """
    An operand representing an immediate.
    """
    def __init__(self, imm, tsize):
        self.imm = imm
        self.tsize = tsize

    def repr(self, op):
        ival = self.imm
        # Do the extra conditionals to make this fast
        if self.tsize == 1:
            if op.opcode in sextend:
                o1 = op.opers[0]
                if self.tsize != o1.tsize:
                    ival = e_bits.sign_extend(ival, self.tsize, o1.tsize)
        if ival > 4096:
            return "0x%.8x" % ival
        return str(ival)

    def getOperValue(self, op, emu=None):
        return self.imm

    def render(self, mcanv, op, idx):
        value = self.imm
        hint = mcanv.syms.getSymHint(op.va, idx)
        if hint != None:
            mcanv.addVaText(hint)
        elif mcanv.mem.isValidPointer(value):
            name = addrToName(mcanv, value)
            mcanv.addVaText(name, value)
        else:
            mcanv.addNameText(str(value))

    def __eq__(self, other):
        if not isinstance(other, i386ImmOper):
            return False
        if other.imm != self.imm:
            return False
        if other.tsize != self.tsize:
            return False
        return True


class i386PcRelOper(envi.Operand):
    """
    This is the operand used for EIP relative offsets
    for operands on instructions like jmp/call
    """
    def __init__(self, imm, tsize):
        self.imm = imm
        self.tsize = tsize

    def repr(self, op):
        return "0x%.8x" % (op.va + op.size + self.imm)

    def getOperValue(self, op, emu=None):
        return op.va + op.size + self.imm

    def render(self, mcanv, op, idx):
        hint = mcanv.syms.getSymHint(op.va, idx)
        if hint != None:
            mcanv.addVaText(hint, value)
        else:
            value = op.va + op.size + self.imm
            name = addrToName(mcanv, value)
            mcanv.addVaText(name, value)

    def __eq__(self, other):
        if not isinstance(other, i386PcRelOper):
            return False
        if other.imm != self.imm:
            return False
        if other.tsize != self.tsize:
            return False
        return True

class i386RegMemOper(envi.Operand):
    """
    An operand which represents the result of reading/writting memory from the
    dereference (with possible displacement) from a given register.
    """
    def __init__(self, reg, tsize, disp=0):
        self.reg = reg
        self.tsize = tsize
        self.disp = disp

    def repr(self, op):
        r = self._dis_regctx.getRegisterName(self.reg)
        if self.disp > 0:
            return "%s [%s + %d]" % (sizenames[self.tsize],r,self.disp)
        elif self.disp < 0:
            return "%s [%s - %d]" % (sizenames[self.tsize],r,abs(self.disp))
        return "%s [%s]" % (sizenames[self.tsize],r)

    def getOperValue(self, op, emu=None):
        if emu == None: return None # This operand type requires an emulator
        return emu.readMemValue(self.getOperAddr(op, emu), self.tsize)

    def setOperValue(self, op, emu, val):
        emu.writeMemValue(self.getOperAddr(op, emu), val, self.tsize)

    def getOperAddr(self, op, emu):
        if emu == None: return None # This operand type requires an emulator
        base, size = emu.getSegmentInfo(op)
        rval = emu.getRegister(self.reg)
        return base + rval + self.disp

    def isDeref(self):
        #FIXME check for lea and probably need to hand in opcode
        return True

    def render(self, mcanv, op, idx):
        mcanv.addNameText(sizenames[self.tsize])
        mcanv.addText(" [")
        mcanv.addNameText(self._dis_regctx.getRegisterName(self.reg), typename="registers")
        hint = mcanv.syms.getSymHint(op.va, idx)
        if hint != None:
            mcanv.addText(" + ")
            mcanv.addNameText(hint)

        else:
            if self.disp > 0:
                mcanv.addText(" + ")
                mcanv.addNameText(str(self.disp))
            elif self.disp < 0:
                mcanv.addText(" - ")
                mcanv.addNameText(str(abs(self.disp)))
        mcanv.addText("]")

    def __eq__(self, other):
        if not isinstance(other, i386RegMemOper):
            return False
        if other.reg != self.reg:
            return False
        if other.disp != self.disp:
            return False
        if other.tsize != self.tsize:
            return False
        return True

class i386ImmMemOper(envi.Operand):
    """
    An operand which represents the dereference (memory read/write) of
    a memory location associated with an immediate.
    """
    def __init__(self, imm, tsize):
        self.imm = imm
        self.tsize = tsize

    def repr(self, op):
        return "%s [0x%.8x]" % (sizenames[self.tsize], self.imm)

    def getOperValue(self, op, emu=None):
        if emu == None: return None # This operand type requires an emulator
        return emu.readMemValue(self.getOperAddr(op, emu), self.tsize)

    def setOperValue(self, op, emu, val):
        emu.writeMemValue(self.getOperAddr(op, emu), val, self.tsize)

    def getOperAddr(self, op, emu=None):
        ret = self.imm
        if emu != None:
            base, size = emu.getSegmentInfo(op)
            ret += base
        return ret

    def isDeref(self):
        return True

    def render(self, mcanv, op, idx):
        mcanv.addNameText(sizenames[self.tsize])
        mcanv.addText(" [")
        value = self.imm

        hint = mcanv.syms.getSymHint(op.va, idx)
        if hint != None:
            mcanv.addVaText(hint, value)
        else:
            name = addrToName(mcanv, value)
            mcanv.addVaText(name, value)

        mcanv.addText("]")

    def __eq__(self, other):
        if not isinstance(other, i386ImmMemOper):
            return False
        if other.imm != self.imm:
            return False
        if other.tsize != self.tsize:
            return False
        return True

class i386SibOper(envi.Operand):
    """
    An operand which represents the result of reading/writting memory from the
    dereference (with possible displacement) from a given register.
    """
    def __init__(self, tsize, reg=None, imm=None, index=None, scale=1, disp=0):
        self.reg = reg
        self.imm = imm
        self.index = index
        self.scale = scale
        self.tsize = tsize
        self.disp = disp

    def __eq__(self, other):
        if not isinstance(other, i386SibOper):
            return False
        if other.imm != self.imm:
            return False
        if other.reg != self.reg:
            return False
        if other.index != self.index:
            return False
        if other.scale != self.scale:
            return False
        if other.disp != self.disp:
            return False
        if other.tsize != self.tsize:
            return False
        return True

    def repr(self, op):

        r = "%s [" % sizenames[self.tsize]

        if self.reg != None:
            r += self._dis_regctx.getRegisterName(self.reg)

        if self.imm != None:
            r += "0x%.8x" % self.imm

        if self.index != None:
            r += " + %s" % self._dis_regctx.getRegisterName(self.index)
            if self.scale != 1:
                r += " * %d" % self.scale

        if self.disp != 0:
            r += " + %d" % self.disp

        r += "]"

        return r

    def getOperValue(self, op, emu=None):
        if emu == None: return None # This operand type requires an emulator
        return emu.readMemValue(self.getOperAddr(op, emu), self.tsize)

    def setOperValue(self, op, emu, val):
        emu.writeMemValue(self.getOperAddr(op, emu), val, self.tsize)

    def getOperAddr(self, op, emu=None):
        if emu == None: return None # This operand type requires an emulator

        ret = 0

        if self.imm != None:
            ret += self.imm

        if self.reg != None:
            ret += emu.getRegister(self.reg)

        if self.index != None:
            ret += (emu.getRegister(self.index) * self.scale)

        # Handle x86 segmentation
        base, size = emu.getSegmentInfo(op)
        ret += base

        return ret + self.disp

    def _getOperBase(self, emu=None):
        # Special SIB only method for getting the SIB base value
        if self.imm:
            return self.imm
        if emu:
            return emu.getRegister(self.reg)
        return None

    def isDeref(self):
        return True

    def render(self, mcanv, op, idx):

        mcanv.addNameText(sizenames[self.tsize])
        mcanv.addText(" [")
        if self.imm != None:
            name = addrToName(mcanv, self.imm)
            mcanv.addVaText(name, self.imm)

        if self.reg != None:
            name = self._dis_regctx.getRegisterName(self.reg)
            mcanv.addNameText(name, typename="registers")

        # Does our SIB have a scale
        if self.index != None:
            mcanv.addText(" + ")
            name = self._dis_regctx.getRegisterName(self.index)
            mcanv.addNameText(name, typename="registers")
            if self.scale != 1:
                mcanv.addText(" * ")
                mcanv.addNameText(str(self.scale))

        hint = mcanv.syms.getSymHint(op.va, idx)
        if hint != None:
            mcanv.addText(" + ")
            mcanv.addNameText(hint)

        else:
            # If we have a displacement, add it.
            if self.disp != 0:
                mcanv.addText(" + ")
                mcanv.addNameText(str(self.disp))

        mcanv.addText("]")

class i386Opcode(envi.Opcode):

    def getBranches(self, emu=None):
        ret = []

        # To start with we have no flags.
        flags = 0
        addb = False

        # If we are a conditional branch, even our fallthrough
        # case is conditional...
        if self.opcode == opcode86.INS_BRANCHCC:
            flags |= envi.BR_COND
            addb = True

        # If we can fall through, reflect that...
        if not self.iflags & envi.IF_NOFALL:
            ret.append((self.va + self.size, flags|envi.BR_FALL))

        # In intel, if we have no operands, it has no
        # further branches...
        if len(self.opers) == 0:
            return ret

        # Check for a call...
        if self.opcode == opcode86.INS_CALL:
            flags |= envi.BR_PROC
            addb = True

        # A conditional call?  really?  what compiler did you use? ;)
        elif self.opcode == opcode86.INS_CALLCC:
            flags |= (envi.BR_PROC | envi.BR_COND)
            addb = True

        elif self.opcode == opcode86.INS_BRANCH:
            oper0 = self.opers[0]
            if isinstance(oper0, i386SibOper) and oper0.scale == 4:
                # In the case with no emulator, note that our deref is
                # from the base of a table. If we have one, parse out all the
                # valid pointers from our base
                base = oper0._getOperBase(emu)
                if emu == None:
                    ret.append((base, flags | envi.BR_DEREF | envi.BR_TABLE))

                else:
                    # Since we're parsing this out, lets just resolve the derefs
                    # for our caller...
                    dest = emu.readMemValue(base, oper0.tsize)
                    while emu.isValidPointer(dest):
                        ret.append((dest, envi.BR_COND))
                        base += oper0.tsize
                        dest = emu.readMemValue(base, oper0.tsize)
            else:
                addb = True

        if addb:
            oper0 = self.opers[0]
            if oper0.isDeref():
                flags |= envi.BR_DEREF
                tova = oper0.getOperAddr(self, emu=emu)
            else:
                tova = oper0.getOperValue(self, emu=emu)

            # FIXME check for SIB decodes and if we have an emulator,
            # FIXME lets do switch case decoding here!

            ret.append((tova, flags))

        return ret

    def render(self, mcanv):
        """
        Render this opcode to the specified memory canvas
        """
        if self.prefixes:
            pfx = self._getPrefixName(self.prefixes)
            if pfx:
                mcanv.addNameText("%s: " % pfx, pfx)

        mcanv.addNameText(self.mnem, typename="mnemonic")
        mcanv.addText(" ")

        # Allow each of our operands to render
        imax = len(self.opers)
        lasti = imax - 1
        for i in xrange(imax):
            oper = self.opers[i]
            oper.render(mcanv, self, i)
            if i != lasti:
                mcanv.addText(",")

    def _getPrefixName(self, prefix):
        """
        """
        ret = []
        for byte,name in prefix_names:
            if prefix & byte:
                ret.append(name)
        return "".join(ret)
            
operand_range = (2,3,4)

MODE_16 = 0
MODE_32 = 1
MODE_64 = 2

class i386Disasm:

    def __init__(self, mode=MODE_32):
        self._dis_mode = MODE_32
        self._dis_prefixes = i386_prefixes
        self._dis_regctx = i386RegisterContext()

        # This will make function lookups nice and quick
        self._dis_amethods = [ None for x in range(22) ]
        self._dis_amethods[opcode86.ADDRMETH_A>>16] = self.ameth_a
        self._dis_amethods[opcode86.ADDRMETH_C>>16] = self.ameth_c
        self._dis_amethods[opcode86.ADDRMETH_D>>16] = self.ameth_d
        self._dis_amethods[opcode86.ADDRMETH_E>>16] = self.ameth_e
        self._dis_amethods[opcode86.ADDRMETH_M>>16] = self.ameth_e
        self._dis_amethods[opcode86.ADDRMETH_N>>16] = self.ameth_n
        self._dis_amethods[opcode86.ADDRMETH_Q>>16] = self.ameth_n
        self._dis_amethods[opcode86.ADDRMETH_R>>16] = self.ameth_e
        self._dis_amethods[opcode86.ADDRMETH_W>>16] = self.ameth_w
        self._dis_amethods[opcode86.ADDRMETH_I>>16] = self.ameth_i
        self._dis_amethods[opcode86.ADDRMETH_J>>16] = self.ameth_j
        self._dis_amethods[opcode86.ADDRMETH_O>>16] = self.ameth_o
        self._dis_amethods[opcode86.ADDRMETH_G>>16] = self.ameth_g
        self._dis_amethods[opcode86.ADDRMETH_P>>16] = self.ameth_p
        self._dis_amethods[opcode86.ADDRMETH_S>>16] = self.ameth_s
        self._dis_amethods[opcode86.ADDRMETH_U>>16] = self.ameth_u
        self._dis_amethods[opcode86.ADDRMETH_V>>16] = self.ameth_v
        self._dis_amethods[opcode86.ADDRMETH_X>>16] = self.ameth_x
        self._dis_amethods[opcode86.ADDRMETH_Y>>16] = self.ameth_y

        # Offsets used to add in addressing method parsers
        self.ROFFSETMMX   = getRegOffset(i386regs, "mm0")
        self.ROFFSETSIMD  = getRegOffset(i386regs, "xmm0")
        self.ROFFSETDEBUG = getRegOffset(i386regs, "debug0")
        self.ROFFSETCTRL  = getRegOffset(i386regs, "ctrl0")
        self.ROFFSETTEST  = getRegOffset(i386regs, "test0")
        self.ROFFSETSEG   = getRegOffset(i386regs, "es")
        self.ROFFSETFPU   = getRegOffset(i386regs, "st0")

    def parse_modrm(self, byte):
        # Pass in a string with an offset for speed rather than a new string
        mod = (byte >> 6) & 0x3
        reg = (byte >> 3) & 0x7
        rm = byte & 0x7
        #print "MOD/RM",hex(byte),mod,reg,rm
        return (mod,reg,rm)

    def byteRegOffset(self, val):
        # NOTE: This is used for high byte metas in 32 bit mode only
        if val < 4:
            return val + RMETA_LOW8
        return (val-4) + RMETA_HIGH8

    # Parse modrm as though addr mode might not be just a reg
    def extended_parse_modrm(self, bytes, offset, opersize, regbase=0):
        """
        Return a tuple of (size, Operand)
        """

        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))

        size = 1

        #print "EXTENDED MOD REG RM",mod,reg,rm

        if mod == 3: # Easy one, just a reg
            # FIXME only use self.byteRegOffset in 32 bit mode, NOT 64 bit...
            if opersize == 1: rm = self.byteRegOffset(rm)
            elif opersize == 2: rm += RMETA_LOW16
            #print "OPERSIZE",opersize,rm
            return (size, i386RegOper(rm+regbase, opersize))

        elif mod == 0:
            # means we are [reg] unless rm == 4 (SIB) or rm == 5 ([imm32])
            if rm == 5:
                imm = e_bits.parsebytes(bytes, offset + size, 4)
                size += 4
                # NOTE: in 64 bit mode, *this* is where we differ, (This case is RIP relative)
                return(size, i386ImmMemOper(imm, opersize))

            elif rm == 4:
                sibsize, scale, index, base, imm = self.parse_sib(bytes, offset+size, mod)
                size += sibsize
                if base != None: base += regbase    # Adjust for different register addressing modes
                if index != None: index += regbase    # Adjust for different register addressing modes
                oper = i386SibOper(opersize, reg=base, imm=imm, index=index, scale=scale_lookup[scale])
                return (size, oper)

            else:
                return(size, i386RegMemOper(regbase+rm, opersize))

        elif mod == 1:
            # mod 1 means we are [ reg + disp8 ] (unless rm == 4 which means sib + disp8)
            if rm == 4:
                sibsize, scale, index, base, imm = self.parse_sib(bytes, offset+size, mod)
                size += sibsize
                disp = e_bits.parsebytes(bytes, offset+size, 1, sign=True)
                size += 1
                if base != None: base += regbase    # Adjust for different register addressing modes
                if index != None: index += regbase    # Adjust for different register addressing modes
                oper = i386SibOper(opersize, reg=base, index=index, scale=scale_lookup[scale], disp=disp)
                return (size,oper)
            else:
                x = e_bits.signed(ord(bytes[offset+size]), 1)
                size += 1
                return(size, i386RegMemOper(regbase+rm, opersize, disp=x))

        elif mod == 2:
            # Means we are [ reg + disp32 ] (unless rm == 4  which means SIB + disp32)
            if rm == 4:
                sibsize, scale, index, base, imm = self.parse_sib(bytes,offset+size,mod)
                size += sibsize
                disp = e_bits.parsebytes(bytes, offset + size, 4, sign=True)
                size += 4
                if base != None: base += regbase    # Adjust for different register addressing modes
                if index != None: index += regbase    # Adjust for different register addressing modes
                oper = i386SibOper(opersize, reg=base, imm=imm, index=index, scale=scale_lookup[scale], disp=disp)
                return (size, oper)

            else:
                # NOTE: Immediate displacements in SIB are still 4 bytes in 64 bit mode
                disp = e_bits.parsebytes(bytes, offset+size, 4, sign=True)
                size += 4
                return(size, i386RegMemOper(regbase+rm, opersize, disp=disp))

        else:
            raise Exception("How does mod == %d" % mod)

    def parse_sib(self, bytes, offset, mod):
        """
        Return a tuple of (size, scale, index, base, imm)
        """
        byte = ord(bytes[offset])
        scale = (byte >> 6) & 0x3
        index = (byte >> 3) & 0x7
        base  = byte & 0x7
        imm = None

        size = 1

        # Special SIB case with no index reg
        if index == 4:
            index = None

        # Special SIB case with possible immediate
        if base == 5:
            if mod == 0: # [ imm32 + index * scale ]
                base = None
                imm = e_bits.parsebytes(bytes, offset+size, 4, sign=False)
                size += 4
            # FIXME is there special stuff needed here?
            elif mod == 1:
                pass
                #raise "OMG MOD 1"
            elif mod == 2:
                pass
                #raise "OMG MOD 2"

        return (size, scale, index, base, imm)


    def _dis_calc_tsize(self, opertype, addrtype, prefixes):
        """
        Use the oper type and prefixes to decide on the tsize for
        the operand.
        """
        mode = MODE_32

        #print "OPERTYPE",hex(opertype)
        sizelist = opcode86.OPERSIZE.get(opertype, None)
        if sizelist == None:
            raise "OPERSIZE FAIL: %.8x" % opertype

        if prefixes & PREFIX_OP_SIZE:

            mode = MODE_16

        #print "OPERTYPE",hex(opertype)
        #print "SIZELIST",repr(sizelist)
        return sizelist[mode]

    def disasm(self, bytes, offset, va):

        # Stuff for opcode parsing
        tabdesc = all_tables[0] # A tuple (optable, shiftbits, mask byte, sub, max)
        startoff = offset # Use startoff as a size knob if needed

        # Stuff we'll be putting in the opcode object
        optype = None # This gets set if we successfully decode below
        mnem = None 
        operands = []

        prefixes = 0

        while True:

            obyte = ord(bytes[offset])

            # This line changes in 64 bit mode
            p = self._dis_prefixes[obyte]
            if p == None:
                break
            if obyte == 0x66 and ord(bytes[offset+1]) == 0x0f:
                break
            prefixes |= p
            offset += 1
            continue

        #pdone = False
        while True:

            obyte = ord(bytes[offset])

            #print "OBYTE",hex(obyte)
            if (obyte > tabdesc[4]):
                #print "Jumping To Overflow Table:", tabdesc[5]
                tabdesc = all_tables[tabdesc[5]]

            tabidx = ((obyte - tabdesc[3]) >> tabdesc[1]) & tabdesc[2]
            #print "TABIDX: %d" % tabidx
            opdesc = tabdesc[0][tabidx]
            #print 'OPDESC: %s' % repr(opdesc)

            # Hunt down multi-byte opcodes
            nexttable = opdesc[0]
            #print "NEXT",nexttable,hex(obyte)
            if nexttable != 0: # If we have a sub-table specified, use it.
                #print "Multi-Byte Next Hop For",hex(obyte),opdesc[0]
                tabdesc = all_tables[nexttable]

                # In the case of 66 0f, the next table is *already* assuming we ate
                # the 66 *and* the 0f...  oblidge them.
                if obyte == 0x66 and ord(bytes[offset+1]) == 0x0f:
                    offset += 1

                # Account for the table jump we made
                offset += 1

                continue

            # We are now on the final table...
            #print repr(opdesc)
            mnem = opdesc[6]
            optype = opdesc[1]
            if tabdesc[2] == 0xff:
                offset += 1 # For our final opcode byte
            break

        if optype == 0:
            #print tabidx
            #print opdesc
            #print "OPTTYPE 0"
            raise envi.InvalidInstruction()

        operoffset = 0
        # Begin parsing operands based off address method
        for i in operand_range:

            oper = None # Set this if we end up with an operand
            osize = 0

            # Pull out the operand description from the table
            operflags = opdesc[i]
            opertype = operflags & opcode86.OPTYPE_MASK
            addrtype = operflags & opcode86.ADDRMETH_MASK

            # If there are no more operands, break out of the loop!
            if operflags == 0:
                break

            #print "ADDRTYPE: %.8x OPERTYPE: %.8x" % (addrtype, opertype)

            tsize = self._dis_calc_tsize(opertype, addrtype, prefixes)

            #print hex(opertype),hex(addrtype)


            # If addrtype is zero, we have operands embedded in the opcode
            if addrtype == 0:
                osize = 0
                oper = self.ameth_0(operflags, opdesc[5+i], tsize, prefixes)

            else:
                #print "ADDRTYPE",hex(addrtype)
                ameth = self._dis_amethods[addrtype >> 16]
                #print "AMETH",ameth
                if ameth == None:
                    raise Exception("Implement Addressing Method 0x%.8x" % addrtype)

                # NOTE: Depending on your addrmethod you may get beginning of operands, or offset
                try:
                    if addrtype == opcode86.ADDRMETH_I or addrtype == opcode86.ADDRMETH_J:
                        osize, oper = ameth(bytes, offset+operoffset, tsize, prefixes)
                    else:
                        osize, oper = ameth(bytes, offset, tsize, prefixes)
                except struct.error, e:
                    # Catch struct unpack errors due to insufficient data length
                    raise envi.InvalidInstruction()

            if oper != None:
                # This is a filty hack for now...
                oper._dis_regctx = self._dis_regctx
                operands.append(oper)
            operoffset += osize

        # Pull in the envi generic instruction flags
        iflags = iflag_lookup.get(optype, 0)

        if priv_lookup.get(mnem, False):
            iflags |= envi.IF_PRIV

        ret = i386Opcode(va, optype, mnem, prefixes, (offset-startoff)+operoffset, operands, iflags)

        return ret

    # Declare all the address method parsers here!

    def ameth_0(self, operflags, operval, tsize, prefixes):
        # Special address method for opcodes with embedded operands
        if operflags & opcode86.OP_REG:
            return i386RegOper(operval, tsize)
        elif operflags & opcode86.OP_IMM:
            return i386ImmOper(operval, tsize)
        raise Exception("Unknown ameth_0! operflags: 0x%.8x" % operflags)

    def ameth_a(self, bytes, offset, tsize, prefixes):
        imm = e_bits.parsebytes(bytes, offset, tsize)
        seg = e_bits.parsebytes(bytes, offset+tsize, 2)
        # THIS BEING GHETTORIGGED ONLY EFFECTS callf jmpf
        #print "FIXME: envi.intel.ameth_a skipping seg prefix %d" % seg
        return (tsize+2, i386ImmOper(imm, tsize))

    def ameth_e(self, bytes, offset, tsize, prefixes):
        return self.extended_parse_modrm(bytes, offset, tsize)

    def ameth_n(self, bytes, offset, tsize, prefixes):
        return self.extended_parse_modrm(bytes, offset, tsize, self.ROFFSETMMX)

    def ameth_w(self, bytes, offset, tsize, prefixes):
        return self.extended_parse_modrm(bytes, offset, tsize, self.ROFFSETSIMD)

    def ameth_i(self, bytes, offset, tsize, prefixes):
        # FIXME sign extend here if opflags has OP_SIGNED
        imm = e_bits.parsebytes(bytes, offset, tsize)
        return (tsize, i386ImmOper(imm, tsize))

    def ameth_j(self, bytes, offset, tsize, prefixes):
        imm = e_bits.parsebytes(bytes, offset, tsize, sign=True)
        return (tsize, i386PcRelOper(imm, tsize))

    def ameth_o(self, bytes, offset, tsize, prefixes):
        # NOTE: displacement *stays* 32 bit even with REX
        # (but 16 bit should probably be supported)
        imm = e_bits.parsebytes(bytes, offset, 4, sign=False)
        return (4, i386ImmMemOper(imm, tsize))

    def ameth_g(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        if tsize == 1: reg = self.byteRegOffset(reg)
        elif tsize == 2: reg += RMETA_LOW16
        return (0, i386RegOper(reg, tsize))

    def ameth_c(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        return (0, i386RegOper(reg+self.ROFFSETCTRL, tsize))

    def ameth_d(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        return (0, i386RegOper(reg+self.ROFFSETDEBUG, tsize))

    def ameth_p(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        return (0, i386RegOper(reg+self.ROFFSETMMX, tsize))

    def ameth_s(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        return (0, i386RegOper(reg+self.ROFFSETSEG, tsize))

    def ameth_u(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        return (0, i386RegOper(reg+self.ROFFSETTEST, tsize))

    def ameth_v(self, bytes, offset, tsize, prefixes):
        mod,reg,rm = self.parse_modrm(ord(bytes[offset]))
        return (0, i386RegOper(reg+self.ROFFSETSIMD, tsize))

    def ameth_x(self, bytes, offset, tsize, prefixes):
        #FIXME this needs the DS over-ride, but is only for outsb which we don't support
        return (0, i386RegMemOper(REG_ESI, tsize))

    def ameth_y(self, bytes, offset, tsize, prefixes):
        #FIXME this needs the ES over-ride, but is only for insb which we don't support
        return (0, i386RegMemOper(REG_ESI, tsize))

