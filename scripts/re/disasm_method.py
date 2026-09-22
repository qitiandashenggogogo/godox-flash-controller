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

def disasm_class(dex_path, class_name):
    with open(dex_path, "rb") as f:
        data = f.read()

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
    method_names = [(types[struct.unpack_from("<H", data, method_ids_off + i * 8)[0]], strings[struct.unpack_from("<I", data, method_ids_off + i * 8 + 4)[0]]) for i in range(method_ids_size)]

    for i in range(class_defs_size):
        off = class_defs_off + i * 32
        class_idx, access_flags, superclass_idx, interfaces_off, source_file_idx, annotations_off, class_data_off, static_values_off = struct.unpack_from("<IIIIIIII", data, off)
        if class_name in types[class_idx]:
            print(f"Class: {types[class_idx]}")
            cur = class_data_off
            static_fields_size, cur = read_uleb128(data, cur)
            instance_fields_size, cur = read_uleb128(data, cur)
            direct_methods_size, cur = read_uleb128(data, cur)
            virtual_methods_size, cur = read_uleb128(data, cur)
            for _ in range(static_fields_size + instance_fields_size):
                _, cur = read_uleb128(data, cur)
                _, cur = read_uleb128(data, cur)

            for m_label, m_size in [("Direct", direct_methods_size), ("Virtual", virtual_methods_size)]:
                m_idx = 0
                for _ in range(m_size):
                    delta, cur = read_uleb128(data, cur)
                    m_idx += delta
                    flags, cur = read_uleb128(data, cur)
                    code_off, cur = read_uleb128(data, cur)
                    m_cls, m_name = method_names[m_idx]
                    print(f"\n[{m_label}] {m_name}")
                    if code_off > 0:
                        regs, ins, outs, tries, debug, insns_size = struct.unpack_from("<HHHHII", data, code_off)
                        insns = data[code_off + 16 : code_off + 16 + insns_size * 2]
                        # print bytecode hex and some decoded ops
                        print(f"  insns ({len(insns)} bytes): {insns.hex()}")

if __name__ == "__main__":
    disasm_class("/tmp/godox_flash_apk_extracted/classes.dex", sys.argv[1])
