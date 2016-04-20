#!/usr/bin/env python
# -*- coding: utf-8 -*-

import struct

from constants import EC_TAGTYPES as tagtype

def ECTag(name, data):
    return unichr(2 * name + isinstance(data, tuple)).encode("utf-8") + ECTagData(data)

def ECTagData(data):
    retval = ''
    subtag_data = ''
    if isinstance(data, tuple):
        data, subtags = data
        subtag_data += unichr(len(subtags)).decode("utf-8")
        for tag in subtags:
            subtag_data += ECTag(tag[0], tag[1])
    if isinstance(data, unicode):
        data = data.encode("utf-8") + '\0'
        retval += struct.pack('!B', tagtype.EC_TAGTYPE_STRING) + ECUTF8Num(len(data)+len(subtag_data))
        retval += subtag_data + data
    elif isinstance(data, (int, long)):
        if data < 0x100:
            fmtStr = '!B'
            tagType = tagtype.EC_TAGTYPE_UINT8
            length = 1
        elif data < 0x10000:
            fmtStr = '!H'
            tagType = tagtype.EC_TAGTYPE_UINT16
            length = 2
        elif data < 0x100000000:
            fmtStr = '!I'
            tagType = tagtype.EC_TAGTYPE_UINT32
            length = 4
        else:
            fmtStr = '!Q'
            tagType = tagtype.EC_TAGTYPE_UINT64
            length = 8
        retval += struct.pack('!BB', tagType, length + len(subtag_data))
        retval += subtag_data
        retval += struct.pack(fmtStr, data)
    elif isinstance(data, str):
        retval += struct.pack('!BB', tagtype.EC_TAGTYPE_HASH16, 16 + len(subtag_data))
        retval += subtag_data
        retval += data
    else:
        raise TypeError('Argument of invalid type specified')
    return retval

def ECTagDataStr(data):
    r'''
    >>> ECTagDataStr(u'\x61') == '\x06\x02\x61\0' # ASCII TEST
    True
    >>> ECTagDataStr(u'\xf1') == '\x06\x03\xc3\xb1\0' # UNICODE TEST
    True
    '''
    data = unicode.encode(data, "utf-8") + '\0'
    fmtStr = '!BB%ds' % len(data)
    return struct.pack(fmtStr, tagtype.EC_TAGTYPE_STRING, len(data), data)

def ECTagDataHash(data):
    if len(data) != 16:
        raise ValueError('length of hash not 16')
    return struct.pack('!BB16s', tagtype.EC_TAGTYPE_HASH16, 16, data)

def ECTagDataInt(data):
    if data < 0x100:
        fmtStr = '!BBB'
        tagType = tagtype.EC_TAGTYPE_UINT8
        length = 1
    elif data < 0x10000:
        fmtStr = '!BBH'
        tagType = tagtype.EC_TAGTYPE_UINT16
        length = 2
    elif data < 0x100000000:
        fmtStr = '!BBI'
        tagType = tagtype.EC_TAGTYPE_UINT32
        length = 4
    else:
        fmtStr = '!BBQ'
        tagType = tagtype.EC_TAGTYPE_UINT64
        length = 8
    return struct.pack(fmtStr, tagType, length, data)

def ECUTF8Num(number):
    return unichr(number).encode("utf-8")

def ReadUTF8Num(data):
    r'''
    >>> ReadUTF8Num('\x10') == (1, 0x10)
    True
    >>> ReadUTF8Num('\xc3\xba') == (2, 250)
    True
    '''
    fco = ord(data[0])
    if fco < 0x80:
        utf_len = 1
    elif 0xBF < fco < 0xE0:
        utf_len = 2
    elif 0x5F < fco < 0xF0:
        utf_len = 3
    elif 0xEF < fco < 0xF8:
        utf_len = 4
    else:
        raise ValueError("%s not a valid unicode range" % hex(ord(data[0])))
    value = ord(data[:utf_len].decode("utf-8"))
    return utf_len, value

def ReadTag(data, utf8_nums = True):
    if utf8_nums:
        name_len, tag_value = ReadUTF8Num(data)
    else:
        name_len = 2
        tag_value, = struct.unpack("!H", data[:2])
    tag_name = tag_value/2
    tag_has_subtags = (tag_value%2 == 1)
    data_len, data = ReadTagData(data[name_len:], tag_has_subtags, utf8_nums)
    return name_len + data_len , tag_name, data

_readTagDataStructLength = struct.Struct('!I')
_readTagDataStructNumTags = struct.Struct('!H')

def ReadTagData(data, tag_has_subtags=False, utf8_nums=True):
    dtype = ord(data[0])
    if utf8_nums:
        utf_len, length = ReadUTF8Num(data[1:])
        tag_data = data[1+utf_len:]
    else:
        length = _readTagDataStructLength.unpack(data[1:5])[0]
        utf_len = 4
        tag_data = data[5:]
    if tag_has_subtags:
        if utf8_nums:
            num_subtags = ord(tag_data[0])
            offset = 1
        else:
            num_subtags = _readTagDataStructNumTags.unpack(tag_data[:2])[0]
            offset = 2
        subtags = []
        subtag_data = tag_data
        length = 1+utf_len+offset
        for i in range(num_subtags):
            subtag_len, subtag_name, subtag_data = ReadTag(tag_data[offset:],utf8_nums)
            offset += subtag_len
            length += subtag_len
            subtags.append((subtag_name, subtag_data))
        tag_data = tag_data[offset:]

    if dtype in (tagtype.EC_TAGTYPE_UINT8, tagtype.EC_TAGTYPE_UINT16,
                 tagtype.EC_TAGTYPE_UINT32, tagtype.EC_TAGTYPE_UINT64):
        intlen = 1 # tagtype.EC_TAGTYPE_UINT8
        if dtype == tagtype.EC_TAGTYPE_UINT16:
            intlen = 2
        elif dtype == tagtype.EC_TAGTYPE_UINT32:
            intlen = 4
        elif dtype == tagtype.EC_TAGTYPE_UINT64:
            intlen = 8
        if tag_has_subtags:
            length += intlen
        value = ReadInt(tag_data[:intlen])
    elif dtype == tagtype.EC_TAGTYPE_HASH16:
        if tag_has_subtags:
            length += 16
        value = ReadHash(tag_data[:16])
    elif dtype == tagtype.EC_TAGTYPE_STRING:
        value = ReadString(tag_data)
        if tag_has_subtags:
            length += len(value)+1
    elif dtype == tagtype.EC_TAGTYPE_IPV4:
        if tag_has_subtags:
            length += 6
        value = ReadIPv4(tag_data)
    elif dtype == tagtype.EC_TAGTYPE_CUSTOM:
        value = tag_data[:length]
    else:
        raise TypeError("Invalid tag type %d" % dtype)
    if tag_has_subtags:
        return length, (value, subtags)
    return length + utf_len + 1, value

ReadInt_fmtStr = {1: "!B", 2: "!H", 4: "!I", 8: "!Q"}
def ReadInt(data):
    try:
        fmtStr = ReadInt_fmtStr[len(data)]
    except KeyError:
        raise ValueError("ReadInt: Wrong length for number: %d [%s]" % (len(data), repr(data)))
    return struct.unpack(fmtStr, data)[0]

_readIPv4 = struct.Struct("!BBBBH")
def ReadIPv4(data):
    return "%d.%d.%d.%d:%d" % _readIPv4.unpack(data[:6])

def ReadString(data):
    return unicode(data[:data.find('\0')], "utf-8")

def ReadHash(data):
    if len(data) != 16:
        raise ValueError("Expected length 16, got length %d" % len(data))
    return data
