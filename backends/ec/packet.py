#!/usr/bin/env python
# -*- coding: utf-8 -*-

import zlib
from struct import pack, unpack
from hashlib import md5

from tag import ECTag, ReadTag
from constants import EC_CODES as codes

class VirtualTag(dict):
    '''
    Virtual attribute object for TagDict
    '''
    def __init__(self, parent, prefix):
        self._parent = parent
        self._prefix = prefix

    _solved = None
    @property
    def solved(self):
        if self._solved is None:
            parent = self._parent
            prefix = self._prefix
            while isinstance(parent, VirtualTag):
                prefix = parent._prefix + prefix
                parent = parent._parent
            self._solved = parent, prefix
        return self._solved

    def items(self):
        parent, prefix = self.solved
        return [(k, v) for k, v in parent.iteritems() if k.startswith(prefix)]

    def values(self):
        parent, prefix = self.solved
        return [v for k, v in parent.iteritems() if k.startswith(prefix)]

    def keys(self):
        parent, prefix = self.solved
        return [k for k in parent.iterkeys() if k.startswith(prefix)]

    def iteritems(self):
        parent, prefix = self.solved
        for k, v in parent.iteritems():
            if k.startswith(prefix):
                yield k, v

    def iterkeys(self):
        parent, prefix = self.solved
        for k in parent.iterkeys():
            if k.startswith(prefix):
                yield k

    def itervalues(self):
        parent, prefix = self.solved
        for k, v in parent.iteritems():
            if k.startswith(prefix):
                yield v

    def __iter__(self):
        return self.iterkeys()

    def update(self, k):
        parent, prefix = self.solved
        prefix += "_"
        parent.update((prefix+k, v) for k, v in dict(k).iteritems())

    def __len__(self):
        return sum((1 for i in self.iterkeys()), 0)

    def __getitem__(self, k):
        return self._parent.__getitem__("%s%s" % (self._prefix, k))

    def __setitem__(self, k, v):
        self._parent.__setitem__(self._prefix+k, v)

    def __delitem__(self, k):
        self._parent.__delitem__(self._prefix+k)

    def __contains__(self, k):
        return self._parent.__contains__("%s%s" % (self._prefix, k))

    def __getattr__(self, k):
        return self._parent.__getattr__("%s%s" % (self._prefix, k))

    def __str__(self):
        return "<VirtualTag%s>" % dict(self.iteritems())


class TagDict(dict):
    '''
    Dictionary which converts backslashes dict keys in
    attributes and subattributes using a helper class.
    '''
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self._known_prefixes = set()

    def _has_prefix(self, prefix):
        prefix = "%s_" % prefix
        if prefix in self._known_prefixes:
            return True
        elif any(k for k in self if k.startswith(prefix)):
            self._known_prefixes.add(prefix)
            return True
        return False

    def __getattr__(self, k):
        if dict.__contains__(self, k):
            return dict.__getitem__(self, k)
        elif self._has_prefix(k):
            return VirtualTag(self, "%s_" % k)
        raise AttributeError("%s has no attribute %s." % (self.__class__.__name__, k))

    @classmethod
    def from_list(cls, tags):
        '''
        Arguments:
            - tags: list of tuples of tags

        Translate recursive list of tags tuples to dictionaries using tag
        constants names.
        '''
        r = cls()
        for k, v in tags:
            k = codes.reverse_tags.get(k, k)
            if v and isinstance(v, list) and isinstance(v[0], tuple) and len(v[0]) == 2 and isinstance(v[0][0], int):
                v = cls.from_list(v)
            elif isinstance(v, tuple) and len(v) == 2:
                v = cls.from_list([v])
            if k in r:
                if isinstance(r[k], dict) and isinstance(v, dict):
                    r[k].update(v)
                elif isinstance(r[k], list):
                    r[k].append(v)
                else:
                    r[k] = [r[k], v]
            else:
                r[k] = v
        # Downgrade to plain dict if all keys are not tags
        return dict(r) if all(isinstance(i, int) for i in r) else r

    def __delitem__(self, k):
        p = k.split("_")
        self._known_prefixes.difference_update("_".join(p[:i]) for i in xrange(1, len(p)))
        dict.__delitem__(self, k)

    def __str__(self):
        return "<TagDict%s>" % dict.__str__(self)

PACKET_BASE = 0x20
def ECPacket(data_tuple):
    r'''
    >>> opcode = codes.EC_OP_ADD_LINK
    >>> link = u'ed2k://|file|asdfasdfasdfasfasdfasdfasdfasfdasfddasdf.wmv|220640069|7F868F9343D632D8C1557BF270D7EC50|/'
    >>> data = ECPacket((opcode, [(codes.EC_TAG_STRING, link)]))
    >>> flags, data_len = unpack("!II",  data[:8])
    >>> packet_data = data[8:data_len+8]
    >>> assert len(packet_data) == data_len, "Wrong data size"
    >>> if flags & codes.EC_FLAG_ZLIB:
    ...     packet_data = zlib.decompress(packet_data)
    >>> op, debug_data = ReadPacketData(packet_data, bool(flags & codes.EC_FLAG_UTF8_NUMBERS))
    >>> op == opcode and debug_data.string == link
    True
    '''
    data = ECPacketData(data_tuple)
    flags = PACKET_BASE | codes.EC_FLAG_UTF8_NUMBERS
    if len(data) > 1024:
        flags |= codes.EC_FLAG_ZLIB
        data = zlib.compress(data)
    return pack('!II', flags, len(data)) + data

def ECPacketData(data_tuple):
    dtype, tags = data_tuple
    return pack('!BB', dtype, len(tags)) + ''.join(ECTag(name, data) for name, data in tags)

def ReadPacketData(data, utf8_nums = True):
    opcode, = unpack('!B', data[:1])

    if opcode == codes.EC_OP_NOOP:
        # NOOP has no tags
        return opcode, []

    if utf8_nums:
        offset = 2
        num_tags, = unpack('!B', data[1:2])
    else:
        offset = 3
        num_tags, = unpack('!H', data[1:3])

    tags = []
    for i in range(num_tags):
        tag_len, tag_name, tag_data = ReadTag(data[offset:], utf8_nums)
        offset += tag_len
        tags.append((tag_name, tag_data))

    return opcode, TagDict.from_list(tags)

def ECLoginPacket(app, version, password):
    return ECPacket(
        (codes.EC_OP_AUTH_REQ, [
            (codes.EC_TAG_CLIENT_NAME, unicode(app)),
            (codes.EC_TAG_CLIENT_VERSION, unicode(version)),
            (codes.EC_TAG_PROTOCOL_VERSION, codes.EC_CURRENT_PROTOCOL_VERSION),
            (codes.EC_TAG_PASSWD_HASH, md5(password).digest())
            ]))

def ECAuthPacket(password):
    return ECPacket(
        (codes.EC_OP_AUTH_PASSWD, [
            (codes.EC_TAG_PASSWD_HASH,      md5(password).digest())
            ]))
