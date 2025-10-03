# 支持JSON结构: hash, original, translated, desc
import struct
import json
from pathlib import Path

UINT32 = "<I"
ENTRY_STRUCT = "<II"  # hash(uint32), offset(uint32)

def read_u32(b: bytes, off: int):
    return struct.unpack_from(UINT32, b, off)[0], off + 4

def read_entries(data: bytes):
    # 读取表头
    count, off = read_u32(data, 0)
    entries = []
    for _ in range(count):
        h, o = struct.unpack_from(ENTRY_STRUCT, data, off)
        entries.append((h, o))
        off += struct.calcsize(ENTRY_STRUCT)
    blob_size, _ = read_u32(data, off)
    blob_start = off + 4
    return entries, blob_start, blob_size

def decode_bytes(bts: bytes):
    
    for enc in ("utf-8", "cp1252", "latin1"):
        try:
            return bts.decode(enc)
        except Exception:
            continue
    return ""  # 不会异常，只是可能出现乱码

def parse_whm_table(path: Path):
    data = path.read_bytes()
    entries, blob_start, blob_size = read_entries(data)
    blob = data[blob_start:blob_start+blob_size]

    results = []
    for h, off in entries:
        if off < 0 or off >= blob_size:
            text = ""
        else:
            j = off
            while j < blob_size and blob[j] != 0:
                j += 1
            bts = blob[off:j]
            text = decode_bytes(bts) if bts else ""
        results.append({
            "hash": int(h) & 0xFFFFFFFF,
            "original": text,
            "translated": "",
            "desc": ""
        })
    return results

def dump_whm_table(out_path: Path, items):
    blob = bytearray()
    offsets = []
    for item in items:
        # 这里取 translated，如果为空则回退到 original
        txt = item.get("translated") or item.get("original") or ""
        b = txt.encode("utf-8")
        offsets.append(len(blob))
        blob.extend(b)
        blob.append(0)
    count = len(items)
    header = bytearray()
    header.extend(struct.pack(UINT32, count))
    for (item, off) in zip(items, offsets):
        header.extend(struct.pack(ENTRY_STRUCT, item["hash"], off))
    header.extend(struct.pack(UINT32, len(blob)))
    out_data = bytes(header) + bytes(blob)
    out_path.write_bytes(out_data)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法:\n"
              " 解析: python whm_table_tool.py parse in.dat out.json\n"
              " 生成: python whm_table_tool.py dump in.json out.dat")
        raise SystemExit(1)

    cmd = sys.argv[1]
    if cmd == "parse":
        items = parse_whm_table(Path(sys.argv[2]))
        with open(sys.argv[3], "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"解析完成: {len(items)} 条 → {sys.argv[3]}")
    elif cmd == "dump":
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            items = json.load(f)
        dump_whm_table(Path(sys.argv[3]), items)
        print(f"生成完成: {len(items)} 条 → {sys.argv[3]}")
