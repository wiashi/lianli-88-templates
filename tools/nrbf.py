"""Minimal .NET BinaryFormatter (NRBF) parser that records byte offsets,
so values can be patched/spliced in place. Used for L-Connect 3 .template files."""
import struct

PRIM_SIZES = {1: 1, 2: 1, 6: 8, 7: 2, 8: 4, 9: 8, 10: 1, 11: 4, 12: 8, 13: 8, 14: 2, 15: 4, 16: 8}
PRIM_FMT = {1: '<?', 2: '<B', 6: '<d', 7: '<h', 8: '<i', 9: '<q', 10: '<b', 11: '<f',
            12: '<q', 13: '<q', 14: '<H', 15: '<I', 16: '<Q'}


class Node:
    def __init__(self, kind, start, **kw):
        self.kind = kind; self.start = start; self.__dict__.update(kw)

    def __repr__(self):
        return f"<{self.kind} @{self.start:#x} {getattr(self, 'cls', '')}>"


class Parser:
    def __init__(self, data):
        self.d = data; self.p = 0
        self.meta = {}      # metadata id -> (classname, member names, member types, addinfo)
        self.objects = {}   # object id -> Node
        self.strings = []   # (offset_of_lenprefix, end, value)

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def lpstr(self):
        start = self.p; n = 0; shift = 0
        while True:
            b = self.u8(); n |= (b & 0x7f) << shift; shift += 7
            if not b & 0x80: break
        s = self.d[self.p:self.p + n].decode('utf-8'); self.p += n
        return s, start

    def prim(self, t):
        off = self.p
        if t == 18:
            s, _ = self.lpstr(); return s, off
        if t == 3:  # char utf8
            b = self.d[self.p]; ln = 1 if b < 0x80 else 2 if b < 0xe0 else 3 if b < 0xf0 else 4
            v = self.d[self.p:self.p + ln].decode('utf-8'); self.p += ln; return v, off
        if t == 5:
            s, _ = self.lpstr(); return s, off
        v = struct.unpack_from(PRIM_FMT[t], self.d, self.p)[0]; self.p += PRIM_SIZES[t]
        return v, off

    def classinfo(self):
        oid = self.i32(); name, _ = self.lpstr(); cnt = self.i32()
        names = [self.lpstr()[0] for _ in range(cnt)]
        return oid, name, names

    def typeinfo(self, cnt):
        bts = [self.u8() for _ in range(cnt)]; add = []
        for bt in bts:
            if bt in (0, 7): add.append(self.u8())
            elif bt == 3: add.append(self.lpstr()[0])
            elif bt == 4: n = self.lpstr()[0]; lib = self.i32(); add.append((n, lib))
            else: add.append(None)
        return bts, add

    def values(self, oid, cls, names, bts, add, start):
        node = Node('class', start, oid=oid, cls=cls, fields={})
        self.objects[oid] = node
        pending_null = 0
        for nm, bt, ad in zip(names, bts, add):
            if pending_null:
                pending_null -= 1; node.fields[nm] = None; continue
            if bt == 0:
                v, off = self.prim(ad); node.fields[nm] = ('prim', ad, v, off)
            else:
                r = self.record()
                if r.kind == 'nullmulti':
                    pending_null = r.count - 1; node.fields[nm] = None
                else:
                    node.fields[nm] = r
        node.end = self.p
        return node

    def array_elems(self, n, bt, ad):
        out = []; i = 0
        while i < n:
            if bt == 0:
                v, off = self.prim(ad); out.append(('prim', ad, v, off)); i += 1
            else:
                r = self.record()
                if r.kind == 'nullmulti': out.extend([None] * r.count); i += r.count
                else: out.append(r); i += 1
        return out

    def record(self):
        start = self.p; rt = self.u8()
        if rt == 0:
            self.p += 16; return Node('header', start)
        if rt == 1:
            oid = self.i32(); mid = self.i32(); cls, names, bts, add = self.meta[mid]
            return self.values(oid, cls, names, bts, add, start)
        if rt in (4, 5):
            oid, cls, names = self.classinfo(); bts, add = self.typeinfo(len(names))
            if rt == 5: self.i32()
            self.meta[oid] = (cls, names, bts, add)
            return self.values(oid, cls, names, bts, add, start)
        if rt in (2, 3):
            raise NotImplementedError('class without types')
        if rt == 6:
            oid = self.i32(); s, off = self.lpstr()
            n = Node('string', start, oid=oid, value=s, lenoff=off, end=self.p)
            self.objects[oid] = n; self.strings.append(n); return n
        if rt == 7:
            oid = self.i32(); at = self.u8(); rank = self.i32()
            lens = [self.i32() for _ in range(rank)]
            if at in (3, 4, 5): [self.i32() for _ in range(rank)]
            bt = self.u8(); ad = None
            if bt in (0, 7): ad = self.u8()
            elif bt == 3: ad = self.lpstr()[0]
            elif bt == 4: ad = (self.lpstr()[0], self.i32())
            total = 1
            for l in lens: total *= l
            n = Node('array', start, oid=oid, bt=bt, ad=ad, lens=lens)
            n.items = self.array_elems(total, bt, ad); n.end = self.p
            self.objects[oid] = n; return n
        if rt == 8:
            t = self.u8(); v, off = self.prim(t); return Node('primtyped', start, t=t, value=v, off=off)
        if rt == 9:
            return Node('ref', start, ref=self.i32())
        if rt == 10:
            return Node('null', start)
        if rt == 11:
            return Node('end', start)
        if rt == 12:
            lid = self.i32(); s, _ = self.lpstr(); return Node('library', start, lid=lid, name=s)
        if rt == 13:
            return Node('nullmulti', start, count=self.u8())
        if rt == 14:
            return Node('nullmulti', start, count=self.i32())
        if rt == 15:
            oid = self.i32(); ln = self.i32(); t = self.u8()
            dstart = self.p
            if t == 2:
                self.p += ln
            else:
                for _ in range(ln): self.prim(t)
            n = Node('primarray', start, oid=oid, length=ln, t=t, dstart=dstart, end=self.p)
            self.objects[oid] = n; return n
        if rt in (16, 17):
            oid = self.i32(); ln = self.i32()
            n = Node('objarray', start, oid=oid); n.items = self.array_elems(ln, 2, None); n.end = self.p
            self.objects[oid] = n; return n
        raise ValueError(f'unknown record {rt} at {start:#x}')

    def parse(self):
        recs = []
        while self.p < len(self.d):
            r = self.record(); recs.append(r)
            if r.kind == 'end': break
        self.records = recs
        return recs


def resolve(p, v):
    if isinstance(v, Node) and v.kind == 'ref':
        return p.objects.get(v.ref)
    return v


def lp_encode(s):
    b = s.encode('utf-8'); n = len(b); out = bytearray()
    while True:
        c = n & 0x7f; n >>= 7
        out.append(c | (0x80 if n else 0))
        if not n: break
    return bytes(out) + b
