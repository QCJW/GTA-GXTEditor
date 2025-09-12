import re
import struct
import sys
from pathlib import Path

# ---------- 配置 ----------
INPUT_TXT = Path('GTA4.txt')
OUTPUT_GXT = Path('chinese.gxt')

# ---------- 文本格式 ----------
TABLE_RE = re.compile(r'^\[([0-9a-zA-Z_]{1,7})\]\s*$')
ENTRY_RE = re.compile(r'^\s*((?:0[xX][0-9A-Fa-f]{8}|[A-Za-z0-9_]+))=\s*(.+?)\s*$')

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
    """
    模拟 C++ 中的 U8ToWide:
    - utf8 -> utf16le 编码单元 (uint16列表)
    - 追加结尾的0
    - 然后调用 LiteralToGame（在写入前做）
    """
    if not u8_string:
        return [0]
    # 解码为python字符串，然后编码为utf-16-le以获取编码单元
    utf16le = u8_string.encode('utf-16-le')
    u16 = list(struct.unpack('<' + 'H' * (len(utf16le) // 2), utf16le))
    # 确保有结尾的0
    if not u16 or u16[-1] != 0:
        u16.append(0)
    return u16

def literal_to_game_u16(u16_list):
    """C++ LiteralToGame: 把 '™' (U+2122) 替换为 0x0099（游戏内部编码）"""
    for i, v in enumerate(u16_list):
        if v == 0x2122:
            u16_list[i] = 0x0099

# 方便打印警告（C++ 也会输出警告，但不会中止）
def warn(msg):
    print("警告:", msg)

def load_txt(filepath: Path, special_chars=None, validate_callback=None):
    if special_chars is None:
        special_chars = set()

    m_Data = {}
    invalid_keys = []  # 用于存储无效的键
    current_table = None

    raw = filepath.read_bytes()
    # 如果存在BOM则去除 (C++ SkipUTF8Signature 的功能)
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

        # 接受 0x...=text 和 普通键名=text 两种格式
        is_original = False
        if line.startswith(';'):
            # 原始文本/注释 — C++ 会设置 is_original 为 true; 我们也支持它
            is_original = True
            line = line[1:]

        m_entry = ENTRY_RE.match(line)
        if m_entry:
            key_left = m_entry.group(1).strip()
            b_string = m_entry.group(2)
            
            # 使用回调函数验证键名格式
            if validate_callback:
                is_valid, msg = validate_callback(key_left, 'IV')
                if not is_valid:
                    invalid_keys.append((key_left, line_no, msg))
                    continue # 跳过此无效键

            if current_table is None:
                warn(f"{filepath}: 第 {line_no} 行条目没有所属表; 将分配到 'MAIN' 表")
                current_table = 'MAIN'
                if current_table not in m_Data:
                    m_Data[current_table] = []

            # 计算 hash_string: 只允许明确以 0x 开头的十六进制键直接使用数字，其他都计算哈希
            hash_str = key_left
            try:
                if key_left.lower().startswith('0x'):
                    int(key_left, 16)  # 验证格式
                    # 保持原样（十六进制数字键）
                else:
                    # 所有其他键（包括带下划线的"数字"键）都计算哈希
                    raise ValueError("非十六进制键")
            except Exception:
                # 作为普通键名 -> 计算哈希
                h = gta4_gxt_hash(key_left)
                hash_str = f'0x{h:08X}'

            # 确保列表存在
            if current_table not in m_Data:
                m_Data[current_table] = []

            # C++ 逻辑: 如果表为空或最后一个条目的 hash_string 不等于当前 hash_string -> 新建一个 TextEntry
            if not m_Data[current_table] or m_Data[current_table][-1]['hash_string'] != hash_str:
                m_Data[current_table].append({'hash_string': hash_str, 'original': '', 'translated': ''})
            
            p_entry = m_Data[current_table][-1]
            if is_original:
                p_entry['original'] = b_string
            else:
                p_entry['translated'] = b_string
                # 检查 ~ 符号的奇偶性，类似C++ (可选的警告)
                if (b_string.count('~') % 2) == 1:
                    warn(f"{filepath}: 第 {line_no} 行有奇数个 '~' 符号。")
        else:
            warn(f"{filepath}: 第 {line_no} 行无法识别。")
            
    # 确保MAIN表存在
    if 'MAIN' not in m_Data:
        m_Data['MAIN'] = []
        
    return m_Data, invalid_keys, special_chars

# ---------- 写 GXT（严格仿 C++ GenerateBinary） ----------
def generate_binary(m_Data, output_path: Path):
    # 确保表的顺序: MAIN 表在最前面, 其他表按字母顺序排序
    table_names = ['MAIN'] + sorted([name for name in m_Data.keys() if name != 'MAIN'])

    with open(output_path, 'wb') as f:
        # GXTHeader: 版本号(uint16)=4, 字符位数(uint16)=16
        f.write(struct.pack('<H', 4))
        f.write(struct.pack('<H', 16))

        # TableBlock: 'TABL' + 大小 (int32), 大小 = 表数量 * TableEntry大小(12)
        table_count = len(table_names)
        f.write(b'TABL')
        f.write(struct.pack('<I', table_count * 12))

        # 预留表条目的空间
        table_entries_pos = f.tell()
        f.write(b'\x00' * (table_count * 12))

        # 写入每个表的数据块, 并记录 TableEntry (表名, 偏移量)
        table_entries = []  # (表名_8字节, 偏移量_整数) 的元组列表
        for table_name in table_names:
            # 记录偏移量
            table_offset = f.tell()
            table_entries.append((table_name, table_offset))

            entries = m_Data.get(table_name, [])

            # 像C++一样, 先在内存中准备好 KeyBlock 和数据数组
            key_entries = []
            datas = []  # uint16 值的列表

            for entry in entries:
                hash_str = entry.get('hash_string', '') or entry.get('original', '')
                try:
                    # 允许 '0x...' 或回退到十进制
                    if isinstance(hash_str, str) and hash_str.lower().startswith('0x'):
                        h_val = int(hash_str, 16)
                    else:
                        h_val = int(hash_str)
                except Exception:
                    h_val = 0
                    warn(f"表 {table_name} 中存在无效的哈希字符串: '{hash_str}'")

                # 计算偏移量(字节), 从数据区开始 = 当前数据长度 * 2
                offset_bytes = len(datas) * 2
                key_entries.append((offset_bytes, h_val))

                # 将翻译文本转换为带结尾0的u16列表 (U8ToWide)
                w_u16 = u8_to_u16_list(entry.get('translated', ''))
                # 应用 LiteralToGame 映射 (C++ LiteralToGame)
                literal_to_game_u16(w_u16)
                # 追加到 datas (包括结尾的0)
                datas.extend(w_u16)

            # 现在写入 KeyBlock: 对于 MAIN 表, 只写 TKEY + 大小; 其他表则写 表名[8] + TKEY + 大小
            if table_name == 'MAIN':
                f.write(b'TKEY')
            else:
                f.write(name_to_8_bytes(table_name))
                f.write(b'TKEY')
            # KeyEntry 区域的大小(字节) = 键数量 * KeyEntry大小
            key_block_size = len(key_entries) * struct.calcsize('<iI')  # 偏移量(int32) + 哈希(uint32)
            f.write(struct.pack('<I', key_block_size))

            # 写入 KeyEntry 数组
            for off_b, hash_v in key_entries:
                f.write(struct.pack('<iI', off_b, hash_v))

            # 写入 DataBlock 头部 'TDAT' + 大小(字节)
            data_block_size = len(datas) * 2
            f.write(b'TDAT')
            f.write(struct.pack('<I', data_block_size))

            # 将 datas 作为 uint16 小端序写入
            if datas:
                f.write(struct.pack('<' + 'H' * len(datas), *datas))

        # 写完所有表后, 回到 table_entries_pos 位置填充 TableEntry 数组
        f.seek(table_entries_pos, 0)
        for name, offset in table_entries:
            f.write(name_to_8_bytes(name))
            f.write(struct.pack('<I', offset))

    print(f"已生成GXT文件: {output_path} (表的数量: {len(table_names)})")

# ---------- 特殊字符收集功能 ----------
def process_special_chars(special_chars):
    # 移除不需要的特殊字符
    special_chars.discard(chr(0x2122))  # 商标符号
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

    m_Data, _, special_chars = load_txt(input_file)
    generate_binary(m_Data, OUTPUT_GXT)
    process_special_chars(special_chars)

if __name__ == '__main__':
    main()
