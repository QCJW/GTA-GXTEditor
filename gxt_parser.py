import struct
import os
import sys
import mmap
import numpy as np

# =======================
# 极致优化版 GXT 解析（修正为原始分割逻辑，兼容所有结尾情况）
# =======================

class III:
    def hasTables(self):
        return False

    def parseTables(self, stream):
        return []

    def parseTKeyTDat(self, stream):
        size = findBlock(stream, 'TKEY')
        entry_count = size // 12
        tkey_data = stream.read(size)
        tkey_np = np.frombuffer(tkey_data, dtype=[('offset', '<u4'), ('key', 'S8')])
        offsets = tkey_np['offset']
        keys = [sys.intern(k.split(b'\x00')[0].decode(errors='ignore')) for k in tkey_np['key']]
        datSize = findBlock(stream, 'TDAT')
        TDat = stream.read(datSize)
        arr = np.frombuffer(TDat, dtype=np.uint16)
        zero_idx = np.where(arr == 0)[0]
        starts = offsets // 2
        ends = np.searchsorted(zero_idx, starts, side='left')
        ends = np.where(ends < len(zero_idx), zero_idx[ends], len(arr))
        values = []
        for i in range(entry_count):
            raw = arr[starts[i]:ends[i]].tobytes()
            try:
                v = raw.decode('utf-16le', errors='ignore')
            except Exception:
                v = ""
            idx = v.find('\x00')
            if idx != -1:
                v = v[:idx]
            values.append(sys.intern(v))
        return list(zip(keys, values))

class VC:
    def hasTables(self):
        return True

    def parseTables(self, stream):
        return _parseTables(stream)

    def parseTKeyTDat(self, stream):
        size = findBlock(stream, 'TKEY')
        entry_count = size // 12
        tkey_data = stream.read(size)
        tkey_np = np.frombuffer(tkey_data, dtype=[('offset', '<u4'), ('key', 'S8')])
        offsets = tkey_np['offset']
        keys = [sys.intern(k.split(b'\x00')[0].decode(errors='ignore')) for k in tkey_np['key']]
        datSize = findBlock(stream, 'TDAT')
        TDat = stream.read(datSize)
        arr = np.frombuffer(TDat, dtype=np.uint16)
        zero_idx = np.where(arr == 0)[0]
        starts = offsets // 2
        ends = np.searchsorted(zero_idx, starts, side='left')
        ends = np.where(ends < len(zero_idx), zero_idx[ends], len(arr))
        values = []
        for i in range(entry_count):
            raw = arr[starts[i]:ends[i]].tobytes()
            try:
                v = raw.decode('utf-16le', errors='ignore')
            except Exception:
                v = ""
            idx = v.find('\x00')
            if idx != -1:
                v = v[:idx]
            values.append(sys.intern(v))
        return list(zip(keys, values))

class SA:
    def hasTables(self):
        return True

    def parseTables(self, stream):
        return _parseTables(stream)

    def parseTKeyTDat(self, stream):
        size = findBlock(stream, 'TKEY')
        entry_count = size // 8
        tkey_bytes = stream.read(size)
        tkey_np = np.frombuffer(tkey_bytes, dtype=np.uint32).reshape(-1, 2)
        offsets = tkey_np[:, 0]
        crcs = tkey_np[:, 1]
        datSize = findBlock(stream, 'TDAT')
        TDat = stream.read(datSize)
        arr = np.frombuffer(TDat, dtype=np.uint8)
        zero_idx = np.where(arr == 0)[0]
        starts = offsets
        ends = np.searchsorted(zero_idx, starts, side='left')
        ends = np.where(ends < len(zero_idx), zero_idx[ends], len(arr))
        mv = memoryview(TDat)
        values = []
        for i in range(entry_count):
            raw = mv[starts[i]:ends[i]]
            try:
                v = raw.tobytes().decode('utf-8', errors='strict')
            except Exception:
                try:
                    gbk_bytes = raw.tobytes()
                    ansi_bytes = gbk_bytes.decode('gbk', errors='strict').encode('cp1252', errors='replace')
                    v = ansi_bytes.decode('cp1252', errors='replace')
                except Exception:
                    v = raw.tobytes().decode('cp1252', errors='replace')
            idx = v.find('\x00')
            if idx != -1:
                v = v[:idx]
            values.append(sys.intern(v))
        keys = [f"{crc:08X}" for crc in crcs]
        return list(zip(keys, values))

class IV:
    def hasTables(self):
        return True

    def parseTables(self, stream):
        return _parseTables(stream)

    def parseTKeyTDat(self, stream):
        size = findBlock(stream, 'TKEY')
        tkey_bytes = stream.read(size)
        entry_count = size // 8
        tkey_np = np.frombuffer(tkey_bytes, dtype=np.uint32).reshape(-1, 2)
        offsets = tkey_np[:, 0]
        crcs = tkey_np[:, 1]

        datSize = findBlock(stream, 'TDAT')
        TDat = stream.read(datSize)
        arr = np.frombuffer(TDat, dtype=np.uint16)
        zero_idx = np.where(arr == 0)[0]

        values = []
        for i in range(entry_count):
            start = offsets[i] // 2
            end_idx = np.searchsorted(zero_idx, start, side='left')
            end = zero_idx[end_idx] if end_idx < len(zero_idx) else len(arr)

            u16_list = arr[start:end].tolist()
            u16_list.append(0)  # 终止符

            fix_characters_u16(u16_list)
            game_to_literal_u16(u16_list)

            if u16_list and u16_list[-1] == 0:
                u16_list = u16_list[:-1]

            try:
                v = struct.pack('<' + 'H'*len(u16_list), *u16_list).decode('utf-16-le', errors='ignore')
            except Exception:
                v = ""

            values.append(v)

        keys = [f"0x{crc:08X}" for crc in crcs]
        return list(zip(keys, values))

def fix_characters_u16(u16_list):
    for i, v in enumerate(u16_list):
        if v == 0x0085:
            u16_list[i] = 0x0020
        elif v in (0x0092, 0x0094):
            u16_list[i] = ord("'")
        elif v == 0x0096:
            u16_list[i] = ord('-')
        elif v in (0x0097, 0x00A0):
            u16_list[i] = 0x0020

def game_to_literal_u16(u16_list):
    for i, v in enumerate(u16_list):
        if v == 0x0099:
            u16_list[i] = 0x2122

def parseTKeyTDat_common(stream, entry_size, key_format, value_encoding):
    size = findBlock(stream, 'TKEY')
    entry_count = int(size / entry_size)
    key_struct = struct.Struct(key_format)
    tkey_data = stream.read(size)
    TKey = [key_struct.unpack_from(tkey_data, i * entry_size) for i in range(entry_count)]
    datSize = findBlock(stream, 'TDAT')
    TDat = stream.read(datSize)
    mv = memoryview(TDat)
    Entries = []
    append_entry = Entries.append
    tdat_len = len(TDat)
    if key_format == 'I8s':
        key_decode = lambda b: b.split(b'\x00')[0].decode(errors='ignore')
        offsets = [entry[0] for entry in TKey]
        offsets.append(tdat_len)
        for i, entry in enumerate(TKey):
            offset = entry[0]
            key = key_decode(entry[1])
            if offset >= tdat_len:
                value = ""
            else:
                next_offset = offsets[i + 1]
                end = next_offset
                raw = mv[offset:end]
                try:
                    value = raw.tobytes().decode(value_encoding, errors='ignore')
                    idx = value.find('\x00')
                    if idx != -1:
                        value = value[:idx]
                except UnicodeDecodeError:
                    value = raw.tobytes().decode('cp1252', errors='ignore')
                    idx = value.find('\x00')
                    if idx != -1:
                        value = value[:idx]
            append_entry((key, value))
    else:
        offsets = [entry[0] for entry in TKey]
        offsets.append(tdat_len)
        for i, entry in enumerate(TKey):
            offset = entry[0]
            key = f'{entry[1]:08X}'
            if offset >= tdat_len:
                value = ""
            else:
                next_offset = offsets[i + 1]
                end = next_offset
                raw = mv[offset:end]
                try:
                    value = raw.tobytes().decode(value_encoding, errors='ignore')
                    idx = value.find('\x00')
                    if idx != -1:
                        value = value[:idx]
                except UnicodeDecodeError:
                    value = raw.tobytes().decode('cp1252', errors='ignore')
                    idx = value.find('\x00')
                    if idx != -1:
                        value = value[:idx]
            append_entry((key, value))
    return Entries

def findBlock(stream, block):
    peek = stream.peek(4096)
    idx = peek.find(block.encode())
    if idx == -1:
        while stream.peek(4)[:4] != block.encode():
            stream.seek(1, os.SEEK_CUR)
    else:
        stream.seek(idx, os.SEEK_CUR)
    _, size = struct.unpack('4sI', stream.read(8))
    return size

def getVersion(stream):
    bytes = stream.peek(8)[:8]
    version, bits_per_char = struct.unpack('HH', bytes[:4])
    if version == 4 and bits_per_char == 16:
        return 'IV'
    word1, word2 = struct.unpack('HH', bytes[:4])
    if word1 == 4 and bytes[4:] == b'TABL':
        if word2 == 8:
            return 'SA'
        if word2 == 16:
            return 'SA-Mobile'
    if bytes[:4] == b'TABL':
        return 'VC'
    if bytes[:4] == b'TKEY':
        return 'III'
    return None

def getReader(version):
    if version == 'VC':
        return VC()
    if version == 'SA':
        return SA()
    if version == 'SA-Mobile':
        return SA()
    if version == 'III':
        return III()
    if version == 'IV':
        return IV()
    return None

def _parseTables(stream):
    size = findBlock(stream, 'TABL')
    entry_count = int(size / 12)
    Tables = []
    for _ in range(entry_count):
        rawName, offset = struct.unpack('8sI', stream.read(12))
        Tables.append((rawName.split(b'\x00')[0].decode(), offset))
    return Tables

class MemoryMappedFile:
    def __init__(self, filename):
        self._file = open(filename, 'rb')
        self._mmap = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self._pos = 0
    def read(self, size):
        data = self._mmap[self._pos:self._pos+size]
        self._pos += size
        return data
    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self._pos = offset
        elif whence == os.SEEK_CUR:
            self._pos += offset
        elif whence == os.SEEK_END:
            self._pos = len(self._mmap) + offset
    def peek(self, size):
        return self._mmap[self._pos:self._pos+size]
    def tell(self):
        return self._pos
    def close(self):
        self._mmap.close()
        self._file.close()
