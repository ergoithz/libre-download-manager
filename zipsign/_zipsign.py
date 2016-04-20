#!/usr/bin/env python
# -*- coding: utf-8 -*-
import struct

import rsa
import rsa.key
import rsa.pkcs1
import rsa.common
import rsa.transform
import rsa.core

def keys_from_string(key_data):
    '''
    Generate key object pair (private, public) for key_data string

    Params:
        key_data: pkcs1 key data as string

    Returns:
        Key object pair as (private key, public key)
    '''
    if "-----BEGIN RSA PRIVATE KEY-----" in key_data:
        private_key = rsa.PrivateKey.load_pkcs1(key_data)
        public_key = rsa.PublicKey(private_key.n, private_key.e)
    elif "-----BEGIN RSA PUBLIC KEY-----" in key_data:
        private_key = None
        public_key = rsa.PublicKey.load_pkcs1(key_data)
    else:
        raise ValueError, "Given string is not valid pkcs1 encoded SHA-512 key"
    return private_key, public_key

def get_comment(data):
    '''
    Returns comment of given zip data string

    Params:
        data: zip file data as string

    Returns:
        Comment as string.
    '''
    eocd = data.rfind(EOCD)
    offs = eocd+22
    size = COMMENT_SIZE_FIELD.unpack(data[offs-2:offs])[0]
    return data[offs:offs+size]

def strip_comment(data):
    '''
    Strips comment to zip file data.

    Params:
        data: zip file data as string

    Returns:
        Zip data with no comment.
    '''
    return set_comment(data, "")

def set_comment(data, comment):
    '''
    Appends comment string to

    Params:
        data: zip file data as string
        comment: comment to append

    Returns:
        Zip data with given comment as string
    '''
    eocd = data.rfind(EOCD)
    size = len(comment)
    return data[:eocd+20] + COMMENT_SIZE_FIELD.pack(size) + comment

SIGN_START_TAG = "-----BEGIN RSA SIGNATURE-----"
SIGN_END_TAG = "-----END RSA SIGNATURE-----"
SIGN_LINE_WIDTH = 64
EOCD = struct.pack("<L", 0x06054b50)
COMMENT_SIZE_FIELD = struct.Struct("<H")
def get_signature(data):
    '''
    Gets signature from zipfile comment field.

    Params:
        data

    Returns:
        Signature as unencoded byte string.
    '''
    comment = get_comment(data)
    spos = comment.rfind(SIGN_START_TAG)+len(SIGN_START_TAG)
    epos = comment.rfind(SIGN_END_TAG)
    if spos == -1 or epos == -1 or spos > epos:
        return None
    return "".join(line.strip() for line in comment[spos:epos].splitlines()).decode("base-64")

def set_signature(data, signature):
    '''
    Writes signature on zipfile comment field, keeping old comments.

    Params:
        data
        signature

    Returns:
        zipfile data with signature in comment field
    '''
    lw = SIGN_LINE_WIDTH # SIGN_LINE_WITH turned local for performance
    et = len(SIGN_END_TAG)

    try:
        comment = get_comment(data)
        while SIGN_START_TAG in comment:
            comment = comment[:comment.find(SIGN_START_TAG)] + comment[comment.find(SIGN_END_TAG)+et:]
    except:
        comment = ""

    signature = signature.encode("base64")

    comment = (
        comment + "\n"
        + SIGN_START_TAG + "\n"
        + "\n".join(signature[i:i+lw] for i in xrange(0, len(signature)-1, lw)) + "\n"
        + SIGN_END_TAG
        )
    return set_comment(data, comment)

def verify(file_or_path, public_key):
    '''
    Check if file is signed with the same private key of given public_key

    Params:
        file_or_path
        public_key

    Returns:
        True if success else False
    '''
    if isinstance(file_or_path, basestring):
        with open(file_or_path, "rb") as f:
            data = f.read()
    else:
        data = file_or_path

    zipdata = strip_comment(data)

    if isinstance(public_key, basestring):
        private_key, public_key = keys_from_string(public_key)

    signature = get_signature(data)
    if signature is None:
        return False

    try:
        return rsa.pkcs1.verify(zipdata, signature, public_key)
    except rsa.pkcs1.VerificationError:
        return False

def signfile(path, private_key):
    '''
    Sign file with private key and append to it's end.

    Params:
        path
        private_key

    Returns:
        True if success, False otherwise.
    '''
    if isinstance(private_key, basestring):
        private_key, public_key = keys_from_string(private_key)
    try:
        with open(path, "rb") as f:
            data = f.read()
        signature = rsa.pkcs1.sign(strip_comment(data), private_key, 'SHA-512')
        with open(path, "wb") as f:
            f.write(set_signature(data, signature))
    except:
        return False
    return True

def signed(file_or_path, public_key):
    '''
    Check if file is signed

    Params:
        file_or_path
        public_key

    Returns:
        True if file have no valid signature, False otherwise.
    '''
    if isinstance(file_or_path, basestring):
        with open(file_or_path, "rb") as f:
            data = f.read()
    else:
        data = file_or_path

    signature = get_signature(data)
    if signature is None:
        return False

    if isinstance(public_key, basestring):
        private_key, public_key = keys_from_string(public_key)

    try:
        blocksize = rsa.common.byte_size(public_key.n)
        encrypted = rsa.transform.bytes2int(signature)
        decrypted = rsa.core.decrypt_int(encrypted, public_key.e, public_key.n)
        clearsig = rsa.transform.int2bytes(decrypted, blocksize)
    except BaseException:
        return False

    # If we can't find the signature  marker, verification failed.
    if clearsig[0:2] != '\x00\x01':
        return False

    # Find the 00 separator between the padding and the payload
    try:
        clearsig.index('\x00', 2)
    except ValueError:
        return False
    return True

def genkeys(private_key_path, public_key_path):
    '''
    Generate private and public key files

    Params:
        private_key_path
        public_key_path
    '''
    pubkey, privkey = rsa.key.newkeys(2048)
    pubdata = pubkey.save_pkcs1()
    privdata = privkey.save_pkcs1()

    with open(private_key_path, "wb") as f:
        f.write(privdata)

    with open(public_key_path, "wb") as f:
        f.write(pubdata)

