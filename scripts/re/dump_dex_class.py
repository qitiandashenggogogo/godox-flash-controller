#!/usr/bin/env python3
import struct
import sys

def parse_dex(dex_path, target_class_name):
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
        strings.append(data[idx:end].decode("latin1"))

    types = []
    for i in range(type_ids_size):
        desc_idx = struct.unpack_from("<I", data, type_ids_off + i * 4)[0]
        types.append(strings[desc_idx])

    for i in range(class_defs_size):
        off = class_defs_off + i * 32
        class_idx, access_flags, superclass_idx, interfaces_off, source_file_idx, annotations_off, class_data_off, static_values_off = struct.unpack_from("<IIIIIIII", data, off)
        cname = types[class_idx]
        if target_class_name in cname:
            print(f"Found class: {cname} (class_data_off={hex(class_data_off)}, static_values_off={hex(static_values_off)})")
            if static_values_off > 0:
                print("  Static values raw:", data[static_values_off:static_values_off+64].hex())
            if class_data_off > 0:
                raw = data[class_data_off:class_data_off+2048]
                for s in strings:
                    if len(s) > 3 and s.encode("latin1") in raw:
                        print("  Embedded string:", s)

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "BluetoothUUID"
    import glob
    for d in glob.glob("/tmp/godox_flash_apk_extracted/classes*.dex"):
        parse_dex(d, target)
