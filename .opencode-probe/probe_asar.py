import json, struct, os, sys, hashlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASAR = r"D:\DeepSeek Harness\resources\app.asar"
OUT = r"C:\Users\wengw\Documents\deepseek-harness\default-workspace\.opencode-probe"
os.makedirs(OUT, exist_ok=True)

with open(ASAR, "rb") as f:
    head = f.read(16)
    u0, u4, u8, u12 = struct.unpack("<IIII", head)
    print("u32@0=%d u32@4=%d u32@8=%d u32@12=%d" % (u0, u4, u8, u12))
    json_len = u12
    raw = f.read(json_len)

catalog = json.loads(raw.decode("utf-8"))
print("catalog parsed OK, top-level:", sorted(catalog.get("files", {}).keys()))

def find_probe_file(node):
    for name, e in node.get("files", {}).items():
        if "files" in e:
            r = find_probe_file(e)
            if r: return r
        elif "offset" in e and e.get("size", 0) > 0 and "integrity" in e and not e.get("unpacked"):
            return (int(e["offset"]), int(e["size"]), e["integrity"]["hash"])
    return None

probe = find_probe_file(catalog)
def test_base(base):
    off, size, h = probe
    with open(ASAR, "rb") as f:
        f.seek(base + off)
        return hashlib.sha256(f.read(size)).hexdigest() == h

cands = [16 + json_len + ((-json_len) % 4), 16 + json_len, 12 + json_len]
data_base = next((b for b in cands if test_base(b)), None)
print("data_base =", data_base)
if data_base is None:
    print("FAILED to locate data base via SHA256 probe")
    sys.exit(1)

def read_at(off, size):
    with open(ASAR, "rb") as f:
        f.seek(data_base + off)
        return f.read(size)

def get_entry(path_parts):
    node = catalog
    for part in path_parts:
        if "files" not in node or part not in node["files"]:
            return None
        node = node["files"][part]
    return node

hits = []
def walk(node, path):
    for name, entry in node.get("files", {}).items():
        child = path + "/" + name
        if "files" in entry:
            walk(entry, child)
        elif "offset" in entry and "opencode" in name.lower():
            hits.append((child, int(entry["offset"]), int(entry.get("size", 0))))

walk(catalog, "")

print()
print("=== opencode entries in asar ===")
for p, off, size in hits:
    print("%s  off=%d size=%d" % (p, off, size))

print()
print("=== dsh top-level ===")
try:
    print(sorted(catalog["files"]["dsh"]["files"].keys()))
except Exception as e:
    print("dsh top-level failed:", e)

print()
print("=== small file contents ===")
saved_readmes = set()
for p, off, size in hits:
    if size <= 6000:
        print("--- %s ---" % p)
        print(read_at(off, size).decode("utf-8", "replace"))
        print()
    else:
        out = os.path.join(OUT, os.path.basename(p))
        with open(out, "wb") as g:
            g.write(read_at(off, size))
        print("[saved] %s -> %s" % (p, out))
    parts = [x for x in p.strip("/").split("/") if x]
    for i in range(len(parts) - 1, 0, -1):
        cand = parts[:i]
        e = get_entry(cand)
        if e and "files" in e and "README.zh.md" in e["files"]:
            key = "/".join(cand)
            if key not in saved_readmes:
                saved_readmes.add(key)
                r = e["files"]["README.zh.md"]
                if "offset" in r:
                    roff, rsize = int(r["offset"]), int(r.get("size", 0))
                    outp = os.path.join(OUT, "README-" + "-".join(cand[-2:]) + ".zh.md")
                    with open(outp, "wb") as g:
                        g.write(read_at(roff, rsize))
                    print("[saved readme] %s -> %s (%d bytes)" % (key, outp, rsize))
            break

print()
print("done.")
