import re
import struct
import sys
from pathlib import Path

# ---------- 配置 ----------
INPUT_TXT = Path('GTA4.txt')
OUTPUT_GXT = Path('chinese.gxt')

# ---------- 文本格式 ----------
TABLE_RE = re.compile(r'^\[([0-9a-zA-Z_]{1,7})\]\s*$')
ENTRY_RE = re.compile(r'^(.+?)=(.*)$')

# ---------- GTA4 GXT 哈希 ----------
def gta4_gxt_hash(key: str) -> int:
    ret_hash = 0
    i = 0
    if key.startswith('"'):
        i = 1
    while i < len(key):
        c = key[i]
        if 'A' <= c <= 'Z':
            c = c.lower()
        elif c == '\\':
            c = '/'
        c_val = ord(c) & 0xFF
        tmp = (ret_hash + c_val) & 0xFFFFFFFF
        mult = (1025 * tmp) & 0xFFFFFFFF
        ret_hash = ((mult >> 6) ^ mult) & 0xFFFFFFFF
        i += 1
    a = (9 * ret_hash) & 0xFFFFFFFF
    a_x = (a ^ (a >> 11)) & 0xFFFFFFFF
    ret_hash = (32769 * a_x) & 0xFFFFFFFF
    return ret_hash

# ---------- 帮助函数 ----------

def name_to_8_bytes(name: str) -> bytes:
    b = name.encode('utf-8')[:8]
    return b + b'\x00' * (8 - len(b))

def u8_to_u16_list(u8_string: str):
    """模拟 C++ 中 U8ToWide:
       - utf8 -> utf16le code units (list of uint16)
       - append trailing 0
       - 然后调用 LiteralToGame（在写入前做）
    """
    if not u8_string:
        return [0]
    # decode to python str then encode utf-16-le to get code units
    utf16le = u8_string.encode('utf-16-le')
    u16 = list(struct.unpack('<' + 'H' * (len(utf16le) // 2), utf16le))
    # ensure terminating 0
    if not u16 or u16[-1] != 0:
        u16.append(0)
    return u16

def literal_to_game_u16(u16_list):
    """C++ LiteralToGame: 把 '™' (U+2122) 替为 0x0099（游戏内部）"""
    for i, v in enumerate(u16_list):
        if v == 0x2122:
            u16_list[i] = 0x0099

# 方便打印警告（C++ 也会输出警告，但不会中止）
def warn(msg):
    print("WARN:", msg)

def load_txt(filepath: Path, special_chars=None):
    

    if special_chars is None:
        special_chars = set()

    m_Data = {}
    current_table = None

    raw = filepath.read_bytes()
    # strip BOM if present (C++ SkipUTF8Signature does this)
    if raw.startswith(b'\xEF\xBB\xBF'):
        raw = raw[3:]
    text = raw.decode('utf-8', errors='replace')
    lines = text.splitlines()

    for line_no, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line:
            continue

        # 收集行中的特殊字符
        for char in raw_line:
            if ord(char) > 255:
                special_chars.add(char)

        m_tab = TABLE_RE.match(line)
        if m_tab:
            current_table = m_tab.group(1)
            if current_table not in m_Data:
                m_Data[current_table] = []
            continue

        # accept both 0x...=text and plain keys
        is_original = False
        if line.startswith(';'):
            # original/comment — C++ would set is_original true; we support it
            is_original = True
            line = line[1:]

        m_entry = ENTRY_RE.match(line)
        if m_entry:
            key_left = m_entry.group(1).strip()
            b_string = m_entry.group(2)

            if current_table is None:
                warn(f"{filepath}: line {line_no} has entry without table; assigning to MAIN")
                current_table = 'MAIN'
                if current_table not in m_Data:
                    m_Data[current_table] = []

            # compute hash_string: if left looks like 0xHEX use it, else compute hash
            hash_str = key_left
            # try to detect hex literal
            try:
                if key_left.lower().startswith('0x'):
                    int(key_left, 16)  # validate
                    # keep as-is
                else:
                    # try decimal number
                    int(key_left)
                # if parsing succeeded, keep original key_left
            except Exception:
                # treat as plain key -> compute hash
                h = gta4_gxt_hash(key_left)
                hash_str = f'0x{h:08X}'

            # ensure list exists
            if current_table not in m_Data:
                m_Data[current_table] = []

            # C++ logic: if table empty or last.hash_string != hash_string -> emplace_back new TextEntry
            if not m_Data[current_table] or m_Data[current_table][-1]['hash_string'] != hash_str:
                m_Data[current_table].append({'hash_string': hash_str, 'original': '', 'translated': ''})
            p_entry = m_Data[current_table][-1]
            if is_original:
                p_entry['original'] = b_string
            else:
                p_entry['translated'] = b_string
                # check ~ token parity like C++ did (optional warning)
                if (b_string.count('~') & 1) == 1:
                    warn(f"{filepath}: line {line_no} has odd number of '~'.")
        else:
            warn(f"{filepath}: line {line_no} cannot be recognized.")
    # ensure MAIN exists
    if 'MAIN' not in m_Data:
        m_Data['MAIN'] = []
    return m_Data, special_chars

# ---------- 写 GXT（严格仿 C++ GenerateBinary） ----------
def generate_binary(m_Data, output_path: Path):
    # Ensure table ordering: MAIN first, then other names sorted lexicographically
    table_names = ['MAIN'] + sorted([name for name in m_Data.keys() if name != 'MAIN'])

    with open(output_path, 'wb') as f:
        # GXTHeader: Version(uint16)=4, CharBits(uint16)=16
        f.write(struct.pack('<H', 4))
        f.write(struct.pack('<H', 16))

        # TableBlock: 'TABL' + Size (int32) where Size = table_count * sizeof(TableEntry) (12)
        table_count = len(table_names)
        f.write(b'TABL')
        f.write(struct.pack('<I', table_count * 12))

        # Reserve table entries
        table_entries_pos = f.tell()
        f.write(b'\x00' * (table_count * 12))

        # write each table block, record TableEntry (Name, Offset)
        table_entries = []  # list of tuples (name_bytes8, offset_int)
        for table_name in table_names:
            # record offset
            table_offset = f.tell()
            table_entries.append((table_name, table_offset))

            entries = m_Data.get(table_name, [])

            # Prepare KeyBlock and data arrays in memory first like C++ does
            key_entries = []
            datas = []  # list of uint16 values

            for entry in entries:
                hash_str = entry.get('hash_string', '') or entry.get('original', '')
                try:
                    # allow '0x...' or decimal fallback
                    if isinstance(hash_str, str) and hash_str.lower().startswith('0x'):
                        h_val = int(hash_str, 16)
                    else:
                        h_val = int(hash_str)
                except Exception:
                    h_val = 0
                    warn(f"Invalid hash string for table {table_name}: '{hash_str}'")

                # compute offset (bytes) from start of data area = current datas length * 2
                offset_bytes = len(datas) * 2
                key_entries.append((offset_bytes, h_val))

                # convert translated to u16 list with terminating 0 (U8ToWide)
                w_u16 = u8_to_u16_list(entry.get('translated', ''))
                # apply LiteralToGame mapping (C++ LiteralToGame)
                literal_to_game_u16(w_u16)
                # append into datas (including terminating 0)
                datas.extend(w_u16)

            # Now write KeyBlock: for MAIN, write only TKEY + size; others write Name[8] + TKEY + size
            if table_name == 'MAIN':
                f.write(b'TKEY')
            else:
                f.write(name_to_8_bytes(table_name))
                f.write(b'TKEY')
            # Size of KeyEntry region (bytes) = number of keys * sizeof(KeyEntry)
            key_block_size = len(key_entries) * struct.calcsize('<iI')  # Offset(int32) + Hash(uint32)
            f.write(struct.pack('<I', key_block_size))

            # write KeyEntry array
            for off_b, hash_v in key_entries:
                f.write(struct.pack('<iI', off_b, hash_v))

            # write DataBlock header 'TDAT' + Size(bytes)
            data_block_size = len(datas) * 2
            f.write(b'TDAT')
            f.write(struct.pack('<I', data_block_size))

            # write datas as uint16 little-endian
            if datas:
                f.write(struct.pack('<' + 'H' * len(datas), *datas))

        # After writing all tables, backfill TableEntry array at table_entries_pos
        f.seek(table_entries_pos, 0)
        for name, offset in table_entries:
            f.write(name_to_8_bytes(name))
            f.write(struct.pack('<I', offset))

    print(f"已生成GXT文件: {output_path} (表的数量: {len(table_names)})")

# ---------- 特殊字符收集功能 ----------
def process_special_chars(special_chars):
    # 移除不需要的特殊字符
    special_chars.discard(chr(0x2122))  # trademark
    special_chars.discard(chr(0x3000))  # 全角空格
    special_chars.discard(chr(0xFEFF))  # BOM标记

    char_per_line = 64
    char_index = 0

    # 将结果写入CHARACTERS.txt
    with open('CHARACTERS.txt', 'w', encoding='utf-8') as f:
        if special_chars:
            for char in sorted(special_chars, key=lambda c: ord(c)):
                f.write(char)
                char_index += 1
                if (char_index >= char_per_line):
                    f.write('\n')
                    char_index = 0

    print("已生成字符表 'CHARACTERS.txt'")

    # 将结果写入char_table.dat
    with open('char_table.dat', 'wb') as f:
        if special_chars:
            f.write(len(special_chars).to_bytes(4, byteorder='little'))
            for char in sorted(special_chars, key=lambda c: ord(c)):
                f.write(ord(char).to_bytes(4, byteorder='little'))

    print("已生成映射表 'char_table.dat'")

# ---------- 主流程 ----------
def main():
    input_file = INPUT_TXT
    if len(sys.argv) > 1:
        input_file = Path(sys.argv[1])

    if not input_file.exists():
        print(f"输入文件 {input_file} 在当前目录中未找到。")
        return

    m_Data, special_chars = load_txt(input_file)
    generate_binary(m_Data, OUTPUT_GXT)
    process_special_chars(special_chars)

if __name__ == '__main__':
    main()