#!/usr/bin/env python
# -*- coding: utf-8 -*-

import socket
import zlib
import hashlib
import logging
import collections
import struct
import threading

from constants import EC_CODES as codes
from packet import ECLoginPacket, ECAuthPacket, ECPacket, ReadPacketData

class ConnectionFailedError(Exception):
    def __init__(self, error, invalidate_socket=True):
        self.error = error
        self.invalidate_socket = invalidate_socket

    def __str__(self):
        return repr(self.error)


class OperationFailedError(Exception):
    def __init__(self, op, invalidate_socket=False):
        self.op = op
        self.invalidate_socket = invalidate_socket

    def __str__(self):
        return repr("Operation %s failed: server returned error code." % self.op)


class SocketWorker(object):
    def __init__(self, socket, pool):
        self._ready = False # Setted by socket pool
        self._sock = socket
        self._pool = pool
        self._cancelled = False
        self._level = 0

    def __getattr__(self, k):
        return getattr(self._sock, k)

    def __enter__(self):
        self._level += 1 # Increase level
        return self

    def __exit__(self, type, value, traceback):
        if not self._cancelled:
            if traceback is None:
                self._level -= 1 # Decrease level
                if self._level == 0 and self._ready: # Min level, return to pool
                    self._pool.append(self)
            else:
                self._cancelled = True
                self._sock.close()
                self._sock = None


class SocketPool(object):
    def __init__(self, builder):
        self._pool = collections.deque()
        self._builder = builder
        self._lock = threading.Lock()

    def append(self, v):
        with self._lock:
            self._pool.append(v)

    def __repr__(self):
        return "<SocketPool {%s}>" % ",".join(str(id(i)) for i in self._pool)

    @property
    def socket(self):
        with self._lock:
            if self._pool:
                s = self._pool.popleft()
            else:
                s = self._builder()
                if not isinstance(s, SocketWorker):
                    s = SocketWorker(s, self)
                s._ready = True
        return s


class Connection(object):
    """Remote-control aMule(d) using "External connections."""

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(0)
        sock.settimeout(1)
        worker = SocketWorker(sock, self._pool)

        try:
            sock.connect((self._host, self._port))
        except socket.error:
            raise ConnectionFailedError("Couldn't connect to socket")

        packet_req = ECLoginPacket(self._app, self._ver, self._pass)
        opcode, tags = self.communicate(packet_req, socket=worker)

        if opcode == codes.EC_OP_AUTH_SALT:
            try:
                passwordSalt = "%lX" % tags["passwd_salt"]
                saltHash = hashlib.md5(passwordSalt).hexdigest()
                passHash = hashlib.md5(self._pass).hexdigest()
                cPassword = (passHash.lower() + saltHash)
                packet_req =  ECAuthPacket(cPassword)
                opcode, tags = self.communicate(packet_req, socket=worker)
            except:
                raise ConnectionFailedError("Authentication failed, incompatible client.")

        if opcode != codes.EC_OP_AUTH_OK:
            raise ConnectionFailedError("Authentication failed")
        logging.debug("EC client authenticated")
        return worker

    _socket_retries = 1
    def __init__(self, password, host="localhost", port=4712, app="pyEC", ver="0.6"):
        """Connect to a running aMule(d) core.

        Parameters:
        - password (required): Password for the connection
        - host (default: "localhost"): Host where core is running
        - port (default: 4712): Port where core is running
        - app (default "pyEC"): application name transmitted on login
        - ver (default: "0.5"): application version
        """
        self._app = app
        self._ver = ver
        self._pass = password
        self._host = host
        self._port = port
        self._pool = SocketPool(self._create_socket)

    def _recv(self, sock, n):
        try:
            data = ""
            while len(data) < n:
                d = sock.recv(n-len(data))
                if d == "": # Socket closed
                    raise ConnectionFailedError("Daemon closed the socket.")
                data += d
        except socket.timeout:
            raise ConnectionFailedError("Daemon does not respond.")
        if len(data) < n:
            raise ConnectionFailedError("Invalid packed size (%d instead %d)." % (len(data), n), False)
        return data

    _header_struct = struct.Struct("!II")
    def recv(self, n=None, socket=None):
        with (socket or self._pool.socket) as sock:
            header_data = self._recv(sock, 8)
            if (not header_data) or len(header_data) != 8:
                raise ConnectionFailedError("Invalid packet header: received %d of 8 expected bytes." % len(header_data))
            flags, data_len = self._header_struct.unpack(header_data)
            packet_data = self._recv(sock, data_len)
            if (not packet_data) or len(packet_data) != data_len:
                raise ConnectionFailedError("Invalid packet body: received %d of %d expected bytes." % (len(packet_data), data_len))
            if flags & codes.EC_FLAG_ZLIB:
                packet_data = zlib.decompress(packet_data)
        return ReadPacketData(packet_data, bool(flags & codes.EC_FLAG_UTF8_NUMBERS))

    def send(self, data, socket=None):
        with (socket or self._pool.socket) as sock:
            sock.send(data)

    validate_outgoing_data = False
    def communicate(self, data, raise_on_fail=True, socket=None):
        if self.validate_outgoing_data:
            flags, data_len = self._header_struct.unpack(data[:8])
            packet_data = data[8:data_len+8]
            assert len(packet_data) == data_len, "Wrong data size"
            if flags & codes.EC_FLAG_ZLIB:
                packet_data = zlib.decompress(packet_data)
            op, debug_data = ReadPacketData(packet_data, bool(flags & codes.EC_FLAG_UTF8_NUMBERS))
            logging.debug((codes.reverse_ops[op], debug_data))
        with (socket or self._pool.socket) as sock:
            self.send(data, socket=sock)
            r = self.recv(socket=sock)
            if r[0] == codes.EC_OP_FAILED and raise_on_fail:
                flags, data_len = self._header_struct.unpack(data[:8])
                raise OperationFailedError(codes.reverse_ops[flags])
        if self.validate_outgoing_data:
            logging.debug((codes.reverse_ops[r[0]], r[1:]))
        return r

    def get_status(self):
        """Get status information from remote core.

        Returns a dictionary with the following keys:
        - "ul_speed": upload speed in Bytes/s
        - "dl_speed": download speed in Bytes/s
        - "ul_limit": upload limit, 0 is unlimited
        - "dl_limit": download limit, 0 is unlimited
        - "queue_len": number of clients waiting in the upload queue
        - "src_count": number of download sources
        - "ed2k_users": users in the eD2k network
        - "kad_users": users in the kademlia network
        - "ed2k_files": files in the eD2k network
        - "kad_files": files in the kademlia network
        - "connstate": connection status, dictionary with the following keys:
            - "ed2k": ed2k network status. possible values: "connected", "connecting", "Not connected"
            - "kad": kademlia network status. possible values: "connected", "Not connected", "Not running"
            - "server_addr": server address in ip:port format
            - "ed2k_id": identification number for the ed2k network
            - "client_id": identification number for the kademlia network
            - "id": connection status. possible values: "LowID", "HighID", ""
            - "kad_firewall": kademlia status. possible values: "ok", "firewalled", ""

        """
        data = ECPacket((codes.EC_OP_STAT_REQ, []))
        response = self.communicate(data)
        # structure: (op['stats'], [(tag['stats_ul_speed'], 0), (tag['stats_dl_speed'], 0), (tag['stats_ul_speed_limit'], 0), (tag['stats_dl_speed_limit'], 0), (tag['stats_ul_queue_len'], 0), (tag['stats_total_src_count'], 0), (tag['stats_ed2k_users'], 3270680), (tag['stats_kad_users'], 0), (tag['stats_ed2k_files'], 279482794), (tag['stats_kad_files'], 0), (tag['connstate'], ((connstate, [subtags])))])
        return response[1]

    def get_short_status(self):
        data = ECPacket((codes.EC_OP_STAT_REQ, codes.EC_DETAIL_CMD, []))
        response = self.communicate(data)
        return response[1]

    def get_connstate(self):
        """Get connection status information from remore core.

        Returns a dictionary with the following keys:
        - "ed2k": ed2k network status. possible values: "connected", "connecting", "Not connected"
        - "kad": kademlia network status. possible values: "connected", "Not connected", "Not running"
        - "server_addr": server address in ip:port format
        - "ed2k_id": identification number for the ed2k network
        - "client_id": identification number for the kademlia network
        - "id": connection status. possible values: "LowID", "HighID", ""
        - "kad_firewall": kademlia status. possible values: "ok", "firewalled", ""
        """
        data = ECPacket((codes.EC_OP_GET_CONNSTATE, [(codes.EC_TAG_DETAIL_LEVEL, codes.EC_DETAIL_CMD)]))
        opcode, tags = self.communicate(data)
        # structure: (op['misc_data'], [(tag['connstate'], (connstate, [subtags]))])
        connstate = tags['connstate'][0]
        status = tags['connstate'][1]
        if (connstate & 0x01): # ed2k connected
            status["ed2k"] = "connected"
            highest_lowid_ed2k_kad = 16777216
            status["id"] = "HighID" if (status["client_id"] > highest_lowid_ed2k_kad) else "LowID"
        elif (connstate & 0x02): # ed2k connecting
            status["ed2k"] = "connecting"
        else:
            status["ed2k"] = "Not connected"
        if (connstate & 0x10): # kad running
            if (connstate & 0x04): # kad connected
                status["kad"] = "connected"
                if (connstate & 0x08): # kad firewalled
                    status["kad_firewall"] = "firewalled"
                else:
                    status["kad_firewall"] = "ok"
            else:
                status["kad"] = "Not connected"
        else:
            status["kad"] = "Not running"
        return status

    def shutdown(self):
        '''
        Shutdown remote core

        For consistent behaviour between official EC client, you should
        call stop_paused_downloads method prior to this. Otherwise
        paused downloads will be resumed at next session startup.
        '''
        data = ECPacket((codes.EC_OP_SHUTDOWN,[]))
        self.send(data)

    def connect(self):
        '''
        Connect remote core to enabled networks in config file.

        Returns a tuple with a boolean indicating success and a list of strings
        with status messages.
        '''
        data = ECPacket((codes.EC_OP_CONNECT,[]))
        opcode, tags = self.communicate(data, False)
        # (op['failed'], [(tag['string'], u'All networks are disabled.')])
        # (op['strings'], [(tag['string'], u'Connecting to eD2k...'), (tag['string'], u'Connecting to Kad...')])
        return (opcode != codes.EC_OP_FAILED, tags.values())

    def server_list(self):
        data = ECPacket((codes.EC_OP_GET_SERVER_LIST, []))
        response = self.communicate(data, False)
        return response[1]

    def update_servers(self, ed2k=None, kad=None):
        if ed2k:
            tags = [(codes.EC_TAG_SERVERS_UPDATE_URL, unicode(ed2k))]
            self.communicate(ECPacket((codes.EC_OP_SERVER_UPDATE_FROM_URL, tags)))
        if kad:
            tags = [(codes.EC_TAG_KADEMLIA_UPDATE_URL, unicode(kad))]
            self.communicate(ECPacket((codes.EC_OP_KAD_UPDATE_FROM_URL, tags)))

    def connect_all(self):
        self.connect_ed2k()
        self.connect_kad()

    def connect_ed2k(self):
        """Connect remote core to eD2k network.

        Returns a boolean indicating success."""
        data = ECPacket((codes.EC_OP_SERVER_CONNECT,[]))
        self.communicate(data)

    def connect_kad(self):
        """Connect remote core to kademlia network.

        Returns a boolean indicating success."""
        data = ECPacket((codes.EC_OP_KAD_START,[]))
        self.communicate(data)

    def disconnect(self):
        """Disconnect remote core from networks.

        Returns a tuple with a boolean indicating success and a list of strings
         with status messages."""
        # (op['noop'], [])
        # (op['strings'], [(tag['string'], u'Disconnected from eD2k.'), (tag['string'], u'Disconnected from Kad.')])
        data = ECPacket((codes.EC_OP_DISCONNECT,[]))
        opcode, tags = self.communicate(data)
        return (opcode == codes.EC_OP_STRINGS, tags.values())

    def stop_paused_downloads(self):
        """
        Stops all paused download
        """
        tags = [
            (codes.EC_TAG_PARTFILE, str(download["partfile_hash"]))
            for download in self.show_dl().itervalues()
            if download["partfile_status"] == 7
            ]
        data = ECPacket((codes.EC_OP_PARTFILE_STOP, tags))
        self.communicate(data)

    def disconnect_server(self):
        """Disconnect remote core from eD2k network."""
        data = ECPacket((codes.EC_OP_SERVER_DISCONNECT,[]))
        response = self.communicate(data)

    def disconnect_kad(self):
        """Disconnect remote core from kademlia network."""
        data = ECPacket((codes.EC_OP_KAD_STOP,[]))
        response = self.communicate(data)

    def reload_shared(self):
        """Reload shared files on remote core."""
        data = ECPacket((codes.EC_OP_SHAREDFILES_RELOAD,[]))
        response = self.communicate(data)

    def reload_ipfilter(self):
        """Reload ipfilter on remote core."""
        data = ECPacket((codes.EC_OP_IPFILTER_RELOAD,[]))
        response = self.communicate(data)

    def get_shared(self):
        """Get list of shared files.

        Returns a list of shared files. The data for a file is stored in a
         dictionary with the following keys:
        - "name": file name
        - "size": size in Bytes
        - "link": eD2k link to the file
        - "hash": file hash stored in 16 Byte
        - "prio": upload priority, Auto is prefixed by 1, e.g. 12 is Auto (High)
            - 4: Very Low
            - 0: Low
            - 1: Normal
            - 2: High
            - 3: Very High
            - 6: Release
        - "aich": file's AICH hash (see: http://wiki.amule.org/index.php/AICH)
        - "part_status": unknown
        - "uploaded": Bytes uploaded during the current session
        - "uploaded_total": total Bytes uploaded
        - "requests": number of requests for this file during the current session
        - "requests_total": total number of requests for this file
        - "accepted": number of accepted requests for this file during the current session
        - "accepted_total": total number of accepted requests for this file
        """
        data = ECPacket((codes.EC_OP_GET_SHARED_FILES, []))
        response = self.communicate(data)
        return response[1]

    def search_local(self, keywords):
        """Start a kad search.

        See function "search" for further details."""
        return self.search(codes.EC_SEARCH_LOCAL, keywords)

    def search_global(self, keywords):
        """Start a kad search.

        See function "search" for further details."""
        return self.search(codes.EC_SEARCH_GLOBAL, keywords)

    def search_kad(self, keywords):
        """Start a kad search.

        See function "search" for further details."""
        return self.search(codes.EC_SEARCH_KAD, keywords)

    def search(self, type, keywords):
        """Start a search.

        Returns a tuple consisting of a boolean value indicating success and
        a string with aMule's answer.

        Type is one of local (0x00), global (0x01) and kad (0x02), denoting the
         scope of the search.
        "local" queries only the connected server, "global" all servers in the
         server list and "kad" starts a search in the kad network.
        Usage of the helper functions "search_local", "search_global" and
         "search_kad" is recommended.

        Keywords is a string of words for which to search.
        """
        packet = (
            codes.EC_OP_SEARCH_START,

            [(codes.EC_TAG_SEARCH_TYPE,
                (type, [(codes.EC_TAG_SEARCH_NAME, unicode(keywords))])
                )
            ])
        data = ECPacket(packet)
        opcode, tags = self.communicate(data)
        not_connected = "progress" in tags["search_status"]
        return (not_connected, tags)

    def search_progress(self):
        """Doesn't work correctly, don't use it.
        """
        data = ECPacket((codes.EC_OP_SEARCH_PROGRESS,[]))
        response = self.communicate(data)
        return response

    def search_results(self):
        """Get results of last search.

        Returns a list of search results. The data for a search result is
         stored in a dictionary with the following keys:
        - "name": file name
        - "size": size in Bytes
        - "hash": file hash stored in 16 Byte
        - "sources": number of clients sharing the file
        - "sources_complete": number of clients sharing all parts of the file
        """
        data = ECPacket((codes.EC_OP_SEARCH_RESULTS, []))
        response = self.communicate(data)
        return response[1]

    def add_link(self, link):
        """Add link to aMule core.

        Returns True when the link was added and False if the link is invalid.
        """
        data = ECPacket((codes.EC_OP_ADD_LINK, [(codes.EC_TAG_STRING, unicode(link))]))
        response = self.communicate(data, False)
        return response[0] == codes.EC_OP_NOOP

    def pause_all(self):
        tags = [
            (codes.EC_TAG_PARTFILE, str(v["partfile_hash"]))
            for v in self.show_dl().itervalues()
            ]
        data = ECPacket((codes.EC_OP_PARTFILE_PAUSE, tags))
        self.communicate(data)

    def resume_all(self):
        tags = [
            (codes.EC_TAG_PARTFILE, str(v["partfile_hash"]))
            for v in self.show_dl().itervalues()
            ]
        data = ECPacket((codes.EC_OP_PARTFILE_RESUME, tags))
        self.communicate(data)

    def set_directory_incoming(self, path):
        data = ECPacket((codes.EC_OP_SET_PREFERENCES, [(codes.EC_TAG_DIRECTORIES_INCOMING, unicode(path))]))
        self.communicate(data)

    def resume_hash(self, dhash):
        data = ECPacket((codes.EC_OP_PARTFILE_RESUME, [(codes.EC_TAG_PARTFILE, str(dhash))]))
        self.communicate(data)

    def pause_hash(self, dhash):
        data = ECPacket((codes.EC_OP_PARTFILE_PAUSE, [(codes.EC_TAG_PARTFILE, str(dhash))]))
        self.communicate(data)

    def remove_hash(self, dhash):
        data = ECPacket((codes.EC_OP_PARTFILE_DELETE, [(codes.EC_TAG_PARTFILE, str(dhash))]))
        response = self.communicate(data, False)
        return response[0] == codes.EC_OP_NOOP

    def show_dl(self):
        data = ECPacket((codes.EC_OP_GET_DLOAD_QUEUE, []))
        response = self.communicate(data, False)
        return response[1].get("partfile", {})

    def show_ul(self):
        data = ECPacket((codes.EC_OP_GET_ULOAD_QUEUE, []))
        response = self.communicate(data, False)
        return response[1].get("partfile", {})

    def show_shared(self):
        data = ECPacket((codes.EC_OP_GET_SHARED_FILES, []))
        response = self.communicate(data, False)
        return response[1].get("knownfile", {})
