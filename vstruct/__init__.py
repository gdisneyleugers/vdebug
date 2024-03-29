
import struct
from StringIO import StringIO

import vstruct.primitives as vs_prims

def isVstructType(x):
    return isinstance(x, vs_prims.v_base)

class VStruct(vs_prims.v_base):

    def __init__(self):
        # A tiny bit of evil...
        object.__setattr__(self, "_vs_values", {})
        vs_prims.v_base.__init__(self)
        self._vs_name = self.__class__.__name__
        self._vs_fields = []
        self._vs_field_align = False # To toggle visual studio style packing
        self._vs_padnum = 0

    def vsParse(self, bytes):
        """
        For all the primitives contained within, allow them
        an opportunity to parse the given data and return the
        total offset...
        """
        plist = self.vsGetPrims()
        fmt = self.vsGetFormat()
        size = struct.calcsize(fmt)
        vals = struct.unpack(fmt, bytes[:size])
        for i in range(len(plist)):
            plist[i].vsSetParsedValue(vals[i])

    def vsEmit(self):
        """
        Get back the byte sequence associated with this structure.
        """
        fmt = self.vsGetFormat()
        r = []
        for p in self.vsGetPrims():
            r.append(p.vsGetValue())
        return struct.pack(fmt, *r)

    def vsGetFormat(self):
        """
        Return the format specifier which would then be used
        """
        # Unpack everything little endian, let vsParseValue deal...
        ret = "<"
        for p in self.vsGetPrims():
            ret += p.vsGetFormat()
        return ret

    def vsIsPrim(self):
        return False

    def vsGetFields(self):
        ret = []
        for fname in self._vs_fields:
            fobj = self._vs_values.get(fname)
            ret.append((fname,fobj))
        return ret

    def vsGetField(self, name):
        x = self._vs_values.get(name)
        if x == None:
            raise Exception("Invalid field: %s" % name)
        return x

    def vsSetField(self, name, value):
        if isVstructType(value):
            self._vs_values[name] = value
            return
        x = self._vs_values.get(name)
        return x.vsSetValue(value)

    def vsAddField(self, name, value):
        if not isVstructType(value):
            raise Exception("Added fields MUST be vstruct types!")

        # Do optional field alignment...
        if self._vs_field_align:

            # If it's a primitive, all is well, if not, pad to size of
            # the first element of the VStruct/VArray...
            if value.vsIsPrim():
                align = len(value)
            else:
                fname = value._vs_fields[0]
                align = len(value._vs_values.get(fname))

            delta = len(self) % align
            if delta != 0:
                print "PADDING %s by %d" % (name,align-delta)
                pname = "_pad%d" % self._vs_padnum
                self._vs_padnum += 1
                self._vs_fields.append(pname)
                self._vs_values[pname] = vs_prims.v_bytes(align-delta)

        self._vs_fields.append(name)
        self._vs_values[name] = value

    def vsGetPrims(self):
        """
        return an order'd list of the primitive fields in this
        structure definition.  This is recursive and will return
        the sub fields of all nested structures.
        """
        ret = []
        for name, field in self.vsGetFields():
            if field.vsIsPrim():
                ret.append(field)
            else:
                ret.extend(field.vsGetPrims())

        return ret

    def vsGetTypeName(self):
        return self._vs_name

    def vsGetOffset(self, name):
        """
        Return the offset of a member.
        """
        offset = 0
        for fname in self._vs_fields:
            if name == fname:
                return offset
            x = self._vs_values.get(fname)
            offset += len(x)
        raise Exception("Invalid Field Specified!")

    def vsGetPrintInfo(self, offset=0, indent=0, top=True):
        ret = []
        if top:
            ret.append((offset, indent, self._vs_name, self))
        indent += 1
        for fname in self._vs_fields:
            x = self._vs_values.get(fname)
            off = offset + self.vsGetOffset(fname)
            if isinstance(x, VStruct):
                ret.append((off, indent, fname, x))
                ret.extend(x.vsGetPrintInfo(offset=off, indent=indent, top=False))
            else:
                ret.append((off, indent, fname, x))
        return ret

    def __len__(self):
        fmt = self.vsGetFormat()
        return struct.calcsize(fmt)

    def __getattr__(self, name):
        # Gotta do this for pickle issues...
        vsvals = self.__dict__.get("_vs_values")
        if vsvals == None:
            vsvals = {}
            self.__dict__["_vs_values"] = vsvals
        r = vsvals.get(name)
        if r is None:
            raise AttributeError(name)
        if isinstance(r, vs_prims.v_prim):
            return r.vsGetValue()
        return r

    def __setattr__(self, name, value):
        # If we have this field, asign to it
        x = self._vs_values.get(name, None)
        if x != None:
            return self.vsSetField(name, value)

        # If it's a vstruct type, create a new field
        if isVstructType(value):
            return self.vsAddField(name, value)

        # Fail over to standard object attribute behavior
        return object.__setattr__(self, name, value)

    def __iter__(self):
        # Our iteration returns name,field pairs
        ret = []
        for name in self._vs_fields:
            ret.append((name, self._vs_values.get(name)))
        return iter(ret)

    def __repr__(self):
        return self._vs_name

    def tree(self, va=0):
        ret = ""
        for off, indent, name, field in self.vsGetPrintInfo():
            rstr = field.vsGetTypeName()
            if isinstance(field, vs_prims.v_prim):
                rstr = repr(field)
            ret += "%.8x%s %s: %s\n" % (va+off, " "*(indent*2),name,rstr)
        return ret

class VArray(VStruct):

    def __init__(self, elems=()):
        VStruct.__init__(self)
        for e in elems:
            self.vsAddElement(e)

    def vsAddElement(self, elem):
        """
        Used to add elements to an array
        """
        idx = len(self._vs_fields)
        self.vsAddField("%d" % idx, elem)

    def __getitem__(self, index):
        return self.vsGetField("%d" % index)

    #FIXME slice asignment

def resolve(impmod, nameparts):
    """
    Resolve the given (potentially nested) object
    from within a module.
    """
    if not nameparts:
        return None

    m = impmod
    for nname in nameparts:
        m = getattr(m, nname, None)
        if m == None:
            break

    return m

added_structs = {}
# NOTE: Gotta import this *after* VStruct/VSArray defined
import vstruct.defs as vs_defs

def getStructure(sname):
    """
    Return an instance of the specified structure.  The
    structure name may be a definition that was added with
    addStructure() or a python path (ie. win32.TEB) of a
    definition from within vstruct.defs.
    """
    s = added_structs.get(sname, None)
    if s != None:
        return s()

    x = resolve(vs_defs, sname.split("."))
    if x != None:
        return x()

    return None

def addStructure(sname, builder):
    """
    Add a new structure definition.  This is
    done by adding a builder which will be called
    when somebody requests an instance of the
    new struct.
    """
    added_structs[sname] = builder

def buildStructure(name, fields):
    """
    Build a structure which was defined at runtime.

    fields is a list of (name, type, kwargs) tuples.
    """
    s = VStruct(name)
    for fname, ftype, kwargs in fields:
        f = ftype(**kwargs)
        s.vsAddField(fname, f)
    return s

class StructureBuilder:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields

    def __call__(self):
        return buildStructure(self.name, self.fields)

def addStructureBuilder(name, fields):
    addStructure(name, StructureBuilder(name, fields))

def getModuleNames():
    return [x for x in dir(vs_defs) if not x.startswith("__")]

def getStructNames(modname):
    ret = []
    mod = resolve(vs_defs, modname)
    if mod == None:
        return ret

    for n in dir(mod):
        x = getattr(mod, n)
        if issubclass(x, VStruct):
            ret.append(n)

    return ret

