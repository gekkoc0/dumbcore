"""Test the public PAC rebuild and verification commands on synthetic firmware containers."""

from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


DUMBCORE = Path(__file__).resolve().with_name('dumbcore.py')
PACWRITE = DUMBCORE.with_name('pacwrite.py')
RESOURCE_NAME = 'mmi_res.bin'
PARTITIONS = (
    ('UserImg', 'user.bin', b'Example signed partition data'),
    ('MMIRes', RESOURCE_NAME, b'sres0001example resource data'),
    ('OmaDM', '', b''),
    ('APN', 'apn.bin', b'Example APN data'),
)


def reference_crc16(data):
    """Compute CRC-16/ARC one bit at a time, independently of the packer."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def set_crcs(data):
    struct.pack_into('<HH', data, 0x848, reference_crc16(data[:0x848]), reference_crc16(data[0x84c:]))


def make_pac(partitions):
    header = bytearray(0x84c)
    header[:18] = 'BP_R1.0.0'.encode('utf-16le')
    struct.pack_into('<II', header, 0x434, len(partitions), len(header))
    struct.pack_into('<I', header, 0x844, 0xfffafffa)

    table = bytearray()
    payload = bytearray()
    data_start = len(header) + len(partitions) * 0xa14
    for name, filename, data in partitions:
        entry = bytearray(0xa14)
        struct.pack_into('<I', entry, 0, len(entry))
        partition_id = name.encode('utf-16le')
        file_name = filename.encode('utf-16le')
        entry[4:4 + len(partition_id)] = partition_id
        entry[0x204:0x204 + len(file_name)] = file_name
        offset = data_start + len(payload) if data else 0
        struct.pack_into('<I', entry, 0x604, len(data))
        struct.pack_into('<I', entry, 0x610, offset)
        table.extend(entry)
        payload.extend(data)

    body = table + payload
    struct.pack_into('<I', header, 0x30, len(header) + len(body))
    image = header + body
    set_crcs(image)
    return bytes(image)


class PacRebuildTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        directory = Path(temp.name)
        self.source = directory / 'source.pac'
        self.destination = directory / 'rebuilt.pac'
        self.replacement = directory / 'replacement.bin'
        self.original = make_pac(PARTITIONS)
        self.source.write_bytes(self.original)

    def run_rebuild(self, *changes):
        return subprocess.run(
            [sys.executable, '-I', str(DUMBCORE), 'pac',
             str(self.source), str(self.destination), *changes],
            capture_output=True, text=True, timeout=10,
        )

    def run_verify(self):
        return subprocess.run(
            [sys.executable, '-I', str(PACWRITE), str(self.source), '--verify'],
            capture_output=True, text=True, timeout=10,
        )

    def assert_resource_replacement(self, data):
        self.replacement.write_bytes(data)
        process = self.run_rebuild(f'MMIRes={self.replacement}')
        self.assertEqual(process.returncode, 0, process.stderr)
        # Compare both CRCs, all table entries and every payload byte against the expected layout.
        expected = (PARTITIONS[0], ('MMIRes', RESOURCE_NAME, data), *PARTITIONS[2:])
        self.assertEqual(self.destination.read_bytes(), make_pac(expected))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_rebuild_without_replacements_preserves_every_byte(self):
        process = self.run_rebuild()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(self.destination.read_bytes(), self.original)

    def test_resource_partition_can_grow(self):
        self.assert_resource_replacement(PARTITIONS[1][2] + b' (with more data)')

    def test_resource_partition_can_shrink(self):
        self.assert_resource_replacement(b'sres0001short')

    def test_verify_accepts_valid_image(self):
        process = self.run_verify()
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_verify_signals_bad_checksum_as_failure(self):
        broken = bytearray(self.original)
        broken[-1] ^= 1
        self.source.write_bytes(broken)
        process = self.run_verify()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("'crc2': False", process.stdout)

    def test_bad_layout_is_rejected_even_with_valid_checksums(self):
        first_entry = 0x84c
        last_entry = first_entry + 3 * 0xa14
        first_payload = struct.unpack_from('<I', self.original, first_entry + 0x610)[0]
        cases = (
            (0x434, 20, 'table extends beyond end of file'),
            (first_entry, 0, 'has an invalid length'),
            (last_entry + 0x610, first_entry, 'lies outside the data area'),
            (last_entry + 0x610, len(self.original), 'lies outside the data area'),
            (last_entry + 0x610, first_payload, 'overlaps another partition'),
        )
        for field, value, message in cases:
            with self.subTest(message=message, field=field, value=value):
                broken = bytearray(self.original)
                struct.pack_into('<I', broken, field, value)
                set_crcs(broken)
                self.source.write_bytes(broken)

                process = self.run_verify()
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(message, process.stderr)

                process = self.run_rebuild()
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(message, process.stderr)
                self.assertFalse(self.destination.exists())

    def test_verify_rejects_short_header(self):
        self.source.write_bytes(self.original[:16])
        process = self.run_verify()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn('truncated PAC header', process.stderr)

    def test_invalid_replacements_are_rejected_without_an_output(self):
        cases = (
            ('Missing', b'replacement', 'no partition'),
            ('UserImg', b'replacement', 'is a signed image'),
            ('MMIRes', b'wrong resource format', 'must be an sres0001 file'),
        )
        for partition, data, message in cases:
            with self.subTest(partition=partition):
                self.replacement.write_bytes(data)
                process = self.run_rebuild(f'{partition}={self.replacement}')
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(message, process.stderr)
                self.assertFalse(self.destination.exists())
                self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
