import os
import random
from typing import Any, List, NamedTuple
import ctypes, ctypes.util

import modman
import utils

PROT_RWX = 0x1 | 0x2 | 0x4
PROT_RX = 0x1 | 0x4

libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
mprotect = libc.mprotect
mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
mprotect.restype = ctypes.c_int

class LoadedModInfo(NamedTuple):
    # A runnable module
    mod: Any
    so_path: str
    region_start: int
    region_size: int
    # The offset of the loaded region in the executable
    region_elf_offset: int

class BitFlip(NamedTuple):
    byteidx: int
    bitidx: int

def new_flip(byteidx, bitidx):
    if isinstance(byteidx, str):
        byteidx = int(byteidx, 16)
    if isinstance(bitidx, str):
        bitidx = int(bitidx)
    assert 0 <= bitidx < 8
    return BitFlip(byteidx, bitidx)

def set_mmap_perms(addr, size, mprot_flags):
    """Sets the permission of the given region to rwx."""
    ret = mprotect(addr, size, mprot_flags)
    assert ret == 0, f'Failed to set permissions of mmap region: {os.strerror(ctypes.get_errno())}'

def parse_maps_line(line):
    fields = line.split()
    addrs = [int(x, 16) for x in fields[0].split('-')]
    start = addrs[0]
    size = addrs[1] - addrs[0]
    offset = int(fields[2], 16)
    perms = fields[1]
    return start, size, offset, perms

def load_mod(bi: utils.BinaryInfo, fpath=None):
    fpath = fpath or bi.fpath
    mod = modman.load_built_model(bi, fpath=fpath)

    target_start, target_size, target_offset = -1, -1, -1
    with open(f'/proc/self/maps', 'r') as maps_file:
        for line in filter(lambda x: fpath in x, maps_file):
            start, size, offset, perms = parse_maps_line(line)
            if perms == 'r-xp':
                set_mmap_perms(start, size, PROT_RWX)
                target_start, target_size, target_offset = start, size, offset
                print(f'Code region: {start:x} - {start+size-1:x} ({size} bytes, loaded from offset 0x{offset:x})')

    if target_start == -1:
        raise RuntimeError(f'Could not find target region for {fpath}')

    # print(f'Mod loaded: {path}')
    return LoadedModInfo(mod, fpath, target_start, target_size, target_offset)

def flip_bits(lmi: LoadedModInfo, flips: List[BitFlip], quiet=False, recover_perms=True):
    """Flips the bits in the given module's target region."""

    with open(f'/proc/self/mem', 'rb+') as mem_file:
        mem_file.seek(lmi.region_start)
        content = mem_file.read(lmi.region_size)
        assert len(content) == lmi.region_size, f'Failed to read content from memory'
        content = bytearray(content)
        # Random flips
        for flip in flips:
            old = content[flip.byteidx]
            content[flip.byteidx] ^= 1 << flip.bitidx
            if not quiet:
                print(f'Flipped bit in byte (+0x{flip.byteidx:x}, {flip.bitidx}): {old:x} -> {content[flip.byteidx]:x}')
        mem_file.seek(lmi.region_start)
        mem_file.write(content)

    if recover_perms:
        set_mmap_perms(lmi.region_start, lmi.region_size, PROT_RX)

    # if not quiet:
    #     print(f'Flipped {len(flips)}/{lmi.region_size*8} bits ({len(flips)/lmi.region_size/8:.2%})')

def random_flip_bits(lmi: LoadedModInfo, nbits):
    flips = [new_flip(random.randrange(lmi.region_size), random.randrange(8)) for _ in range(nbits)]
    flip_bits(lmi, flips)
    return flips
