"""删除 VRM 1.0 里不带动任何顶点的 spring 链（蒙皮权重全 0 的残留物理骨）。

VRoid 工程里挂着但未实际穿着的服装模板（实测：栖灵01 的 6 条 CoatSkirt 链、
14 关节）会照常导出 springBone，把关节数推过栖灵 30 上限；它们权重为 0，
删掉对渲染和物理表现没有任何影响。只改 GLB 的 JSON chunk，BIN 原样保留。

用法: python3 scripts/vrm/strip_weightless_springs.py <src.vrm> <dst.vrm>
"""
import json
import struct
import sys

CT_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
CT_FMT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def split_glb(data):
    magic, version, total = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        raise ValueError("不是 GLB")
    chunks = []
    off = 12
    while off + 8 <= total:
        ln, ty = struct.unpack("<II", data[off:off + 8])
        chunks.append((ty, bytearray(data[off + 8:off + 8 + ln])))
        off += 8 + ln
    return version, chunks


def read_accessor(doc, binchunk, index, weights=False):
    a = doc["accessors"][index]
    view = doc["bufferViews"][a["bufferView"]]
    size = CT_SIZE[a["componentType"]]
    n = NCOMP[a["type"]]
    base = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = view.get("byteStride", size * n)
    fmt = "<" + CT_FMT[a["componentType"]] * n
    step = size * n
    out = []
    for k in range(a["count"]):
        p = base + k * stride
        out.append(struct.unpack(fmt, bytes(binchunk[p:p + step])))
    return out


def node_weight_usage(doc, binchunk):
    usage = {}
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "JOINTS_0" not in attrs:
                continue
            joints = read_accessor(doc, binchunk, attrs["JOINTS_0"])
            if "WEIGHTS_0" in attrs:
                wts = read_accessor(doc, binchunk, attrs["WEIGHTS_0"])
            else:
                wts = [(1.0, 0.0, 0.0, 0.0)] * len(joints)
            for js, ws in zip(joints, wts):
                for j, w in zip(js, ws):
                    if w:
                        usage[j] = usage.get(j, 0) + w
    return usage


def joint_count(doc):
    chains = doc.get("extensions", {}).get("VRMC_springBone", {}).get("springs", [])
    entries = sum(len(s.get("joints", [])) for s in chains)
    return chains, entries - len(chains)


def main(src, dst):
    data = open(src, "rb").read()
    version, chunks = split_glb(data)
    json_i = next(i for i, (t, _) in enumerate(chunks) if t == 0x4E4F534A)
    bin_i = next((i for i, (t, _) in enumerate(chunks) if t == 0x004E4942), None)
    doc = json.loads(bytes(chunks[json_i][1]).rstrip(b"\x00 ").decode("utf-8"))
    binchunk = chunks[bin_i][1] if bin_i is not None else b""

    chains, before = joint_count(doc)
    usage = node_weight_usage(doc, binchunk)
    kept, dropped = [], []
    for s in chains:
        nodes = [j["node"] for j in s.get("joints", [])]
        if nodes and all(usage.get(n, 0) == 0 for n in nodes):
            dropped.append(nodes)
        else:
            kept.append(s)
    doc["extensions"]["VRMC_springBone"]["springs"] = kept
    after_entries = sum(len(s["joints"]) for s in kept)
    after = after_entries - len(kept)

    raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((4 - len(raw) % 4) % 4)
    chunks[json_i] = (0x4E4F534A, bytearray(raw))
    out = struct.pack("<4sII", b"glTF", version, 12)
    total = 12
    for ty, body in chunks:
        body = bytearray(body)
        if len(body) % 4:
            body += b"\x00" * (4 - len(body) % 4)
        out += struct.pack("<II", len(body), ty) + bytes(body)
        total += 8 + len(body)
    out = out[:8] + struct.pack("<I", total) + out[12:]
    open(dst, "wb").write(out)

    names = doc.get("nodes", [])
    for nodes in dropped:
        print("drop:", " -> ".join(names[n].get("name", "?") for n in nodes))
    print("spring 关节: %d -> %d（删除 %d 条零权重链）" % (before, after, len(dropped)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
