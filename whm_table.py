import struct
from pathlib import Path

UINT32 = "<I"
ENTRY_STRUCT = "<II"  # hash(uint32), offset(uint32)

def read_u32(b: bytes, off: int):
    return struct.unpack_from(UINT32, b, off)[0], off + 4

def read_entries(data: bytes):
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
    return bts.hex()

def parse_whm_table(path: Path):
    data = path.read_bytes()
    entries, blob_start, blob_size = read_entries(data)
    blob = data[blob_start:blob_start+blob_size]

    results = []
    for h, off in entries:
        # offset 相对于 blob 起始
        if off < blob_size:
            j = off
            while j < blob_size and blob[j] != 0:
                j += 1
            bts = blob[off:j]
        else:
            # 越界，标记为二进制
            bts = b''
        text = decode_bytes(bts) if bts else "[BINARY]"
        results.append({"hash": h, "text": text})
    return results

def dump_whm_table(out_path: Path, items):
    blob = bytearray()
    offsets = []
    for item in items:
        b = item["text"].encode("utf-8")
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

def load_txt_items(txt_path: Path):
    """从TXT文件加载条目，格式为0xhash=文本"""
    items = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            # 分割hash和文本部分
            if "=" in line:
                hash_part, text = line.split("=", 1)
                # 解析十六进制hash
                try:
                    hash_val = int(hash_part, 16)
                    items.append({"hash": hash_val, "text": text})
                except ValueError:
                    print(f"警告: 第{line_num}行哈希格式无效 - 已跳过")
            else:
                print(f"警告: 第{line_num}行缺少'='分隔符 - 已跳过")
    return items

def save_txt_items(txt_path: Path, items):
    """将条目保存为TXT文件，格式为0xhash=文本"""
    with open(txt_path, "w", encoding="utf-8") as f:
        for item in items:
            # 格式化hash为十六进制，前面加上0x
            hash_str = f"0x{item['hash']:08X}"
            f.write(f"{hash_str}={item['text']}\n")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("WHM表文件处理工具")
        print("功能: 将WHM二进制表文件与文本格式相互转换")
        print("\n使用方法:")
        print("  解析二进制文件到文本:")
        print("    python whm_table_tool.py parse <输入文件> <输出文本文件>")
        print("    示例: python whm_table_tool.py parse data.dat strings.txt")
        print("\n  从文本文件生成二进制:")
        print("    python whm_table_tool.py dump <输入文本文件> <输出文件>")
        print("    示例: python whm_table_tool.py dump strings.txt new_data.dat")
        print("\n文本文件格式: 每行一条记录，格式为 0x哈希值=文本内容")
        print("  示例: 0x0001A3F2=欢迎使用本系统")
        raise SystemExit(1)

    cmd = sys.argv[1]
    if cmd == "parse":
        items = parse_whm_table(Path(sys.argv[2]))
        save_txt_items(Path(sys.argv[3]), items)
        print(f"解析完成: 共处理 {len(items)} 条记录 → 保存至 {sys.argv[3]}")
    elif cmd == "dump":
        items = load_txt_items(Path(sys.argv[2]))
        dump_whm_table(Path(sys.argv[3]), items)
        print(f"生成完成: 共处理 {len(items)} 条记录 → 保存至 {sys.argv[3]}")
    else:
        print(f"错误: 未知命令 '{cmd}'")
        print("可用命令: parse, dump")
        raise SystemExit(1)
