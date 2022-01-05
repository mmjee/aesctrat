import sys
import random

# The file is based on https://github.com/mmcloughlin/aesnix/blob/master/gen.py

FILE_HEADER = (
u'''
// Code generated by multiblock_arm64_gen.py. DO NOT EDIT.

#include "textflag.h"

// See https://golang.org/src/crypto/aes/gcm_arm64.s
#define NR R9
#define XK R10
#define DST R11
#define SRC R12
// R13 is reserved. See https://www.keil.com/support/man/docs/armasm/armasm_dom1361289861367.htm
#define IV_PTR R14
// R15 is reserved. See https://www.keil.com/support/man/docs/armasm/armasm_dom1361289861367.htm
#define IV_LOW_LE R16
#define IV_HIGH_LE R17
// R18 is reserved.
#define IV_LOW_BE R19
#define IV_HIGH_BE R20
#define BLOCK_INDEX R21

// V0.B16 - V7.B16 are for blocks (<=8). See BLOCK_OFFSET.
// V8.B16 - V22.B16 are for <=15 round keys (<=15). See ROUND_KEY_OFFSET.
// V23.B16 - V30.B16 are for destinations (<=8). See DST_OFFSET.
''')

BLOCK_OFFSET = 0
ROUND_KEY_OFFSET = 8
DST_OFFSET = 23

TEXT = u'TEXT \u00b7{name}(SB),NOSPLIT,$0'

CTR_DECL = '// func {name}(nr int, xk *uint32, dst, src, ivRev *byte, blockIndex uint64)'
CTR_HEADER = (
u'''
	MOVD nr+0(FP), NR
	MOVD xk+8(FP), XK
	MOVD dst+16(FP), DST
	MOVD src+24(FP), SRC
	MOVD ivRev+32(FP), IV_PTR
	LDP (IV_PTR), (IV_LOW_LE, IV_HIGH_LE)
	MOVD blockIndex+40(FP), BLOCK_INDEX
''')


REV16_DECL = '// func {name}(iv *byte)'
REV16_HEADER = (

u'''
	MOVD iv+0(FP), IV_PTR
	LDP (IV_PTR), (IV_HIGH_BE, IV_LOW_BE)
	REV IV_LOW_BE, IV_LOW_LE
	REV IV_HIGH_BE, IV_HIGH_LE
	STP (IV_LOW_LE, IV_HIGH_LE), (IV_PTR)
''')


def ctr(n):
    """
    Generate Go assembly for XORing CTR output to n blocks at once with one key.
    """

    assert n <= 8

    params = {
        'name': 'ctrBlocks{}Asm'.format(n),
    }

    # Header.
    for tmpl in [CTR_DECL, TEXT, CTR_HEADER]:
        print tmpl.format(**params)

    # Prepare plain from IV and blockIndex.

    # Add blockIndex.
    print '\tADDS BLOCK_INDEX, IV_LOW_LE'
    print '\tADC $0, IV_HIGH_LE'

    # Copy to plaintext registers.
    for i in xrange(n):
        print '\tREV IV_LOW_LE, IV_LOW_BE'
        print '\tREV IV_HIGH_LE, IV_HIGH_BE'

        # https://developer.arm.com/documentation/dui0801/g/A64-SIMD-Vector-Instructions/MOV--vector--from-general-
        print '\tVMOV IV_LOW_BE, V{block}.D[1]'.format(block=BLOCK_OFFSET+i)
        print '\tVMOV IV_HIGH_BE, V{block}.D[0]'.format(block=BLOCK_OFFSET+i)
        if i != n-1:
            print '\tADDS $1, IV_LOW_LE'
            print '\tADC $0, IV_HIGH_LE'

    # Num rounds branching.
    print '\tCMP $12, NR'
    print '\tBLT Lenc128'
    print '\tBEQ Lenc192'

    def do_regs(first_reg, nregs, cmd):
        while nregs != 0:
            batch = min(nregs, 4)
            reg_list = ['V{key}.B16'.format(key=j) for j in range(first_reg, first_reg+batch)]
            print cmd.format(size=16*batch, regs=', '.join(reg_list))
            nregs -= batch
            first_reg += batch

    def load_keys(first_key, nkeys):
        do_regs(ROUND_KEY_OFFSET+first_key, nkeys, '\tVLD1.P {size}(XK), [{regs}]')

    def enc(key, with_mc):
        for i in xrange(n):
            print '\tAESE V{key}.B16, V{block}.B16'.format(key=ROUND_KEY_OFFSET+key, block=BLOCK_OFFSET+i)
            if with_mc:
                print '\tAESMC V{block}.B16, V{block}.B16'.format(block=BLOCK_OFFSET+i)

    # 2 extra rounds for 256-bit keys.
    print 'Lenc256:'
    load_keys(0, 2)
    enc(0, True)
    enc(1, True)

    # 2 extra rounds for 192-bit keys.
    print 'Lenc192:'
    load_keys(2, 2)
    enc(2, True)
    enc(3, True)

    # 10 rounds for 128-bit (with special handling for final).
    print 'Lenc128:'
    load_keys(4, 11)
    for r in xrange(4, 4+9):
        enc(r, True)
    enc(13, False)

    # We need to XOR blocks with the last round key (key 14, register V22).
    for i in xrange(n):
        print '\tVEOR V{block}.B16, V{key}.B16, V{block}.B16'.format(key=ROUND_KEY_OFFSET+14, block=BLOCK_OFFSET+i)

    # XOR results to destination.
    do_regs(DST_OFFSET, n, '\tVLD1.P {size}(SRC), [{regs}]')
    for i in xrange(n):
        print '\tVEOR V{dst}.B16, V{block}.B16, V{dst}.B16'.format(block=BLOCK_OFFSET+i, dst=DST_OFFSET+i)
    do_regs(DST_OFFSET, n, '\tVST1.P [{regs}], {size}(DST)')

    print '\tRET'
    print


def rev16():
    """
    Generate Go assembly for BSWAP.
    """

    params = {
        'name': 'rev16Asm',
    }

    # Header.
    for tmpl in [REV16_DECL, TEXT, REV16_HEADER]:
        print tmpl.format(**params)

    print '\tRET'
    print


def generate_file(sizes):
    print FILE_HEADER
    for size in sizes:
        ctr(size)
    rev16()


def main(args):
    sizes = map(int, args[1].split(','))
    generate_file(sizes)


if __name__ == '__main__':
    main(sys.argv)