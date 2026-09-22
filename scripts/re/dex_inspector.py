#!/usr/bin/env python3
import struct
import sys

def read_uleb128(data, off):
    val = 0
    shift = 0
    while True:
        b = data[off]
        off += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, off

def inspect_dex(dex_path, class_name_filter):
    with open(dex_path, "rb") as f:
        data = f.read()

    magic = data[:8]
    if not magic.startswith(b"dex\n"):
        return

    string_ids_size, string_ids_off = struct.unpack_from("<II", data, 0x38)
    type_ids_size, type_ids_off = struct.unpack_from("<II", data, 0x40)
    proto_ids_size, proto_ids_off = struct.unpack_from("<II", data, 0x48)
    field_ids_size, field_ids_off = struct.unpack_from("<II", data, 0x50)
    method_ids_size, method_ids_off = struct.unpack_from("<II", data, 0x58)
    class_defs_size, class_defs_off = struct.unpack_from("<II", data, 0x60)

    strings = []
    for i in range(string_ids_size):
        str_off = struct.unpack_from("<I", data, string_ids_off + i * 4)[0]
        idx = str_off
        while data[idx] & 0x80:
            idx += 1
        idx += 1
        end = data.find(b"\x00", idx)
        strings.append(data[idx:end].decode("latin1", errors="ignore"))

    types = [strings[struct.unpack_from("<I", data, type_ids_off + i * 4)[0]] for i in range(type_ids_size)]

    field_names = []
    for i in range(field_ids_size):
        class_idx, type_idx, name_idx = struct.unpack_from("<HHI", data, field_ids_off + i * 8)
        field_names.append((types[class_idx], strings[name_idx], types[type_idx]))

    method_names = []
    for i in range(method_ids_size):
        class_idx, proto_idx, name_idx = struct.unpack_from("<HHI", data, method_ids_off + i * 8)
        method_names.append((types[class_idx], strings[name_idx]))

    for i in range(class_defs_size):
        off = class_defs_off + i * 32
        class_idx, access_flags, superclass_idx, interfaces_off, source_file_idx, annotations_off, class_data_off, static_values_off = struct.unpack_from("<IIIIIIII", data, off)
        cname = types[class_idx]
        if class_name_filter in cname:
            print(f"\n=================== CLASS: {cname} ===================")
            if class_data_off == 0:
                continue
            cur = class_data_off
            static_fields_size, cur = read_uleb128(data, cur)
            instance_fields_size, cur = read_uleb128(data, cur)
            direct_methods_size, cur = read_uleb128(data, cur)
            virtual_methods_size, cur = read_uleb128(data, cur)

            # static fields
            f_idx = 0
            for _ in range(static_fields_size):
                delta, cur = read_uleb128(data, cur)
                f_idx += delta
                flags, cur = read_uleb128(data, cur)
                if f_idx < len(field_names):
                    f_cls, f_name, f_type = field_names[f_idx]
                    print(f"  Static Field: {f_name} : {f_type}")

            # instance fields
            f_idx = 0
            for _ in range(instance_fields_size):
                delta, cur = read_uleb128(data, cur)
                f_idx += delta
                flags, cur = read_uleb128(data, cur)
                if f_idx < len(field_names):
                    f_cls, f_name, f_type = field_names[f_idx]
                    print(f"  Instance Field: {f_name} : {f_type}")

            # direct methods
            m_idx = 0
            for _ in range(direct_methods_size):
                delta, cur = read_uleb128(data, cur)
                m_idx += delta
                flags, cur = read_uleb128(data, cur)
                code_off, cur = read_uleb128(data, cur)
                if m_idx < len(method_names):
                    m_cls, m_name = method_names[m_idx]
                    print(f"  [Direct Method] {m_name} (code_off={hex(code_off)})")
                    if code_off > 0:
                        registers_size, ins_size, outs_size, tries_size, debug_info_off, insns_size = struct.unpack_from("<HHHHII", data, code_off)
                        insns = data[code_off + 16 : code_off + 16 + insns_size * 2]
                        pos = 0
                        while pos < len(insns) - 1:
                            op = insns[pos]
                            if op == 0x1a:
                                str_id = struct.unpack_from("<H", insns, pos + 2)[0] if pos + 4 <= len(insns) else 0
                                if str_id < len(strings):
                                    print(f"      const-string: {repr(strings[str_id])}")
                            pos += 2

            # virtual methods
            m_idx = 0
            for _ in range(virtual_methods_size):
                delta, cur = read_uleb128(data, cur)
                m_idx += delta
                flags, cur = read_uleb128(data, cur)
                code_off, cur = read_uleb128(data, cur)
                if m_idx < len(method_names):
                    m_cls, m_name = method_names[m_idx]
                    print(f"  [Virtual Method] {m_name} (code_off={hex(code_off)})")
                    if code_off > 0:
                        registers_size, ins_size, outs_size, tries_size, debug_info_off, insns_size = struct.unpack_from("<HHHHII", data, code_off)
                        insns = data[code_off + 16 : code_off + 16 + insns_size * 2]
                        pos = 0
                        while pos < len(insns) - 1:
                            op = insns[pos]
                            if op == 0x1a:
                                str_id = struct.unpack_from("<H", insns, pos + 2)[0] if pos + 4 <= len(insns) else 0
                                if str_id < len(strings):
                                    print(f"      const-string: {repr(strings[str_id])}")
                            pos += 2

if __name__ == "__main__":
    filt = sys.argv[1] if len(sys.argv) > 1 else "CommandPolicy"
    inspect_dex("/tmp/godox_flash_apk_extracted/classes.dex", filt)
