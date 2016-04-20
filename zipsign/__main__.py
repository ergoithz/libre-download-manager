#!/usr/bin/env python
import sys
import os
import os.path

import my_env
from _zipsign import *


cli_help = '''SHA-512 file sign tool

USAGE: %(file)s KEYFILE FILE
Signs FILE using KEYFILE private key.

USAGE: %(file)s --verify KEYFILE FILE
Check if FILE is signed with KEYFILE public or private key.

USAGE: %(file)s --genkeys PRIVATE_KEYFILE PUBLIC_KEYFILE
Generate private PRIVATE_KEYFILE and public PUBLIC_KEYFILE key files.

OPTIONS:
    --help     show this help message
    --verify   signature verification
    --genkeys  generate private and public key files
'''

if __name__ == "__main__":
    if my_env.is_frozen:
        argv_offset = 1
    elif __file__ in sys.argv:
        argv_offset = sys.argv.index(__file__) + 1
    else:
        argv_offset = 1

    params = [i for i in sys.argv[argv_offset:] if not i.startswith("--")]

    if "--help" in sys.argv or not params:
        print cli_help % {"file":" ".join(os.path.basename(i) if os.path.isabs(i) else i for i in sys.argv[:argv_offset])}
        sys.exit(0 if "--help" in sys.argv else 1)

    if "--genkeys" in sys.argv:
        private_key_path, public_key_path = params[0:2]
        genkeys(private_key_path, public_key_path)
        sys.exit(0)

    key_path, module_path = params[0:2]

    with open(key_path) as f:
        key_data = f.read()

    try:
        private_key, public_key = keys_from_string(key_data)
    except ValueError:
        print >> sys.stderr, "Error: %r is not valid private or public key file" % key_path
        sys.exit(1)

    # Verify signature
    if verify(module_path, public_key):
        if "--verify" in sys.argv:
            print "Verification was OK"
            sys.exit(0)
        print >> sys.stderr, "Error: Already signed with given key."
        sys.exit(1)
    elif "--verify" in sys.argv:
        if signed(module_path, public_key):
            print >> sys.stderror, "Error: File is signed using other key."
            sys.exit(1)
        print >> sys.stderr, "Error: File isn't signed."
        sys.exit(1)

    if private_key is None:
        print >> sys.stderr, "Error: Cannot sign file using %r: is not a private key file" % key_path
        sys.exit(1)

    # Attach signature
    signfile(module_path, private_key)

    # Test if really signed
    if signed(module_path, public_key):
        print "Signed succesfully"
        sys.exit(0)

    print >> sys.stderr, "Error: Signature error."
    sys.exit(1)
