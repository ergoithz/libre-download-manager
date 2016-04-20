#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import os.path

import hashlib
import random
import time
import logging
import urlparse
import struct
import threading

import shutil

try:
    import cStringIO as StringIO
except ImportError:
    import StringIO

logger = logging.getLogger(__name__)

try:
    import ec
except ImportError as e:
    logger.exception(e)
    ec = None

import my_env

if not my_env.is_windows:
    import subprocess

from .base import Backend as BackendBase, Download as DownloadBase, choose_port, faster_url
from utils import attribute

import config
import utils

COLLECTION_FILE_VERSION1_INITIAL = 0x01
COLLECTION_FILE_VERSION2_LARGEFILES = 0x02
# version 2 files support files bigger than 4GB (uint64_t file sizes)

uint32_t = struct.Struct("I")
uint16_t = struct.Struct("H")
uint8_t = struct.Struct("B")

'''
uint32_t emulecollection version
values: COLLECTION_FILE_VERSION1_INITIAL                0x01
        COLLECTION_FILE_VERSION2_LARGEFILES             0x02

        version 2 files support files bigger than 4GB (uint64_t file sizes)

uint32_t header tag count

header tags:

        TAGTYPE_STRING                                  0x02
                uint16_t                                        0x0001
                FT_FILENAME                                     0x01
                uint16_t                                        string length
                std::string                                     string value
        TAGTYPE_STRING                                  0x02
                uint16_t                                        0x0001
                FT_COLLECTIONAUTHOR                             0x31
                uint16_t                                        string length
                std::string                                     string value
        TAGTYPE_BLOB                                    0x07
                uint16_t                                        0x0001
                FT_COLLECTIONAUTHORKEY                          0x32
                uint32_t                                        blob size
                (notype)                                        blob data

uint32_t collection file count

uint32_t file tag count

        at this point the TAGTYPE 0x01 will appear as 0x81 (uType | 0x80)
        -> see eMule packets.cpp
        FT_FILERATING and FT_FILECOMMENT are optional tags

        TAGTYPE_HASH                                    0x01
                FT_FILEHASH                                     0x28
                (notype)[16]                                    hash data

        TAGTYPE_UINT32                                  0x03
                FT_FILESIZE                                     0x02
                uint32_t                                        file size
        TAGTYPE_UINT16                                  0x08
                FT_FILESIZE                                     0x02
                uint16_t                                        file size
        TAGTYPE_UINT8                                   0x09
                FT_FILESIZE                                     0x02
                uint8_t                                         file size
        TAGTYPE_UINT64                                  0x0B
                FT_FILESIZE                                     0x02
                uint64_t                                        file size

        TAGTYPE_STR1 to 16                                      0x11 to 0x20
                FT_FILENAME                                     0x01
                std::string                                     file name

        string length is TAGTYPE_STRx - 0x11 + 0x01 [1 to 16]

        TAGTYPE_STRING                                  0x02
                FT_FILENAME                                     0x01
                uint16_t                                        string length
                std::string                                     string value

        TAGTYPE_STRING                                  0x02
                FT_FILECOMMENT                                  0xF6
                uint16_t                                        string length
                std::string                                     string value

        TAGTYPE_UINT8                                   0x09
                FT_FILERATING                                   0xF7
                uint8_t                                         file rating

'''

class Download(DownloadBase):
    _custom_status = (
        "connecting", "looking for peers", "downloading from %d peers"
        )
    _status = (
        "ready", "empty", "waiting for hash", "hashing", "error",
        "insufficient", "unknown", "paused", "completing", "finished",
        "allocationg"
        )
    _priority = (
        "Low", "Normal", "High", "Very high", "Very low", "Auto",
        "Powershare",
        "", "", "", # UNUSED
        "Auto - Low", "Auto - Normal", "Auto - High"
        )

    _has_data = False
    def _update(self, data = None):
        if data is None:
            if self.finished and not all(
              os.path.exists(os.path.join(self.download_dir, i))
              for i in self.filenames):
                self.backend.download(self.ed2k_link)
                self.finished = False
            return
        self._has_data = True

        partfile = data.partfile

        self.last_update = time.time()
        self.hash = partfile.hash.encode("hex")
        self.name = partfile.name
        self.filenames = [partfile.name]
        self.size = partfile.size.full
        self.comments = partfile.comments.values() if hasattr(partfile, "comments") and partfile.comments else []
        self.ed2k_link = partfile.ed2k_link

        '''
        if hasattr(partfile, "part_status"):
            self._parts = [
                b == "1"
                for i in partfile.part_status
                for b in bin(ord(i))[2:].rjust(8, "0")
                ]
        elif self.finished:
            self._parts = [True]
        '''

        if data.is_downloading:
            self.finished = False
            self.progress = float(partfile.size.done) / partfile.size.full
            self.paused = partfile.status == 7
            self.downloaded = partfile.size.done
            self.downspeed = partfile.speed if hasattr(partfile, "speed") else 0
            self.upspeed = partfile.size_xfer_up if hasattr(partfile, "size_xfer_up") else 0

            self.sources = partfile.source_count_xfer
            state_code = partfile.status
            downloading = False
            if state_code in (2, 3):
                state = self._status[3]
            elif state_code in (4, 7, 8, 9):
                state = self._status[state_code]
            elif self.sources > 0:
                state = self._custom_status[2] % self.sources
                downloading = True
            else:
                state = self._custom_status[1]

            self.state = state
            self.downloading = downloading
        elif not self.finished:
            self.finished = True
            logger.debug("Finishing download %s" % self.name)
            self.state = self._status[9]
            self.progress = 1
            self.downloaded = self.size
            self.downspeed = 0
            self.downloading = False
            old_dir = self.backend.amule_download_dir
            logger.debug("Removing %s from queue" % self.name)
            self.backend.client.remove_hash(self.hash)
            logger.debug("Moving files of %s to download folder." % self.name)
            # Ensure download_dir exists
            if not os.path.isdir(self.download_dir):
                os.makedirs(self.download_dir)
            # Move download files to download_dir
            for n, i in enumerate(self.filenames):
                p = os.path.join(old_dir, i)
                if os.path.exists(p):
                    d = os.path.join(self.download_dir, i)
                    if os.path.exists("%s" % d):
                        g, ext = d.rsplit(".", 1)
                        for j in xrange(sys.maxint):
                            aux = "%s - %d.%s" % (g, j, ext)
                            if not os.path.exists(aux):
                                d = aux
                                break
                        self.filenames[n] = d
                    shutil.move(p, d)
                else:
                    logger.error("File %s does not exists." % p)
            logger.debug("Download %s finished." % self.name)

    def refresh(self):
        self._update(self.backend._data[self.hash])
        DownloadBase.refresh()

    def has_metadata(self):
        return self._has_data

    filenames = None # Override parent getter-setter
    finished = False
    ed2k_link = None
    comments = None
    hash = None
    def __init__(self, backend, data, resume_data=None):
        DownloadBase.__init__(self, backend, resume_data)

        self.download_dir = self.backend.download_dir
        self._parts = [False]

        if resume_data:
            self.download_dir = resume_data.get("download_dir", self.backend.download_dir)
            self.position = resume_data.get("position", -1)
            self.downloaded = resume_data.get("downloaded", 0)
            self.size = resume_data.get("size", 0)
            self.progress = resume_data.get("progress", 0)
            self.finished = resume_data.get("finished", False)
            self.hash = resume_data.get("hash", None)
            self.name = resume_data.get("name", "")
            self.filenames = resume_data.get("filenames", [])
            self.comments = resume_data.get("comments", [])
            self.ed2k_link = resume_data.get("link", None)
            self.paused = resume_data.get("paused", False)
            self.state = self._status[7] if self.paused else self._custom_status[0]
            self.hidden = resume_data["hidden"] if "hidden" in resume_data else resume_data.get("finished", False)
        else:
            self.state = self._custom_status[0]
            self.comments = []

        if self.finished:
            self.state = self._status[9]

        self._update(data)

    @property
    def files_progress(self):
        return {self.filenames[0]: (self.size*self.progress, self.size)}

    @property
    def eta(self):
        return (self.size-self.downloaded)/self.downspeed if self.downspeed > 0 else 0

    @property
    def resume_data(self):
        return {
            "link": self.ed2k_link,
            "position": self.position,
            "downloaded": self.downloaded,
            "size": self.size,
            "progress": self.progress,
            "finished": self.finished,
            "hash": self.hash,
            "name": self.name,
            "filenames": self.filenames,
            "download_dir": self.download_dir,
            "paused": self.paused,
            "user_data": self.user_data,
            "hidden": self.hidden,
            }

    @resume_data.setter
    def resume_data(self, v):
        self._rdata = v or {}

    def remove(self):
        if not self.finished:
            self.backend.client.remove_hash(self.hash.decode("hex"))

        if self.hash in self.backend._downloads:
            del self.backend._downloads[self.hash]

    def pause(self):
        if self.finished:
            self.paused = True
        else:
            self.backend.client.pause_hash(self.hash.decode("hex"))

    def resume(self):
        if self.finished:
            self.paused = False
        else:
            self.backend.client.resume_hash(self.hash.decode("hex"))

    @property
    def properties(self):
        r = [
            ("link", self.ed2k_link),
            ("hash", self.hash),
            #("pieces", self._parts),
            ("state", self.state),
            ("location", self.download_dir),
            ("files", "\n".join(self.filenames))
            ]
        if self.comments:
            r.append(("comments", "\n".join(self.comments)))
        return r

class PosixDaemon(object):
    '''
    Daemon handler for nice OSes where amuled can fork.
    '''
    @property
    def pid(self):
        try:
            if self.pidfile:
                if os.path.isfile(self.pidfile):
                    with open(self.pidfile, "r") as f:
                        return int(f.read().strip())
        except BaseException as e:
            logger.exception(e)
        return 0

    @property
    def running(self):
        pid = self.pid
        return pid > 0 and my_env.get_running(pid)

    def __init__(self, amulepath, configfile, pidfile):
        self.cmd = (amulepath, "--config-dir=\"%s\"" % configfile, "--full-daemon", "--pid-file=\"%s\"" % pidfile)
        self.pidfile = pidfile
        self.run()

    def run(self):
        self.terminate()
        popen = subprocess.Popen(self.cmd)
        popen.wait()

    def terminate(self):
        while self.running:
            my_env.kill_process(self.pid)
            time.sleep(0.001)
        if os.path.isfile(self.pidfile):
            os.remove(self.pidfile)

class WindowsDaemon(object):
    '''
    Daemon handler for bad OSes where amuled cannot fork, let's spoon!
    '''
    @property
    def running(self):
        return my_env.get_running_pidfile(self.pidfile)

    def __init__(self, amulepath, configfile, pidfile):
        self.cmd = (amulepath, "--config-dir=\"%s\"" % configfile)
        self.amulepath = amulepath
        self.pidfile = pidfile
        self.run()

    def run(self):
        my_env.kill_process_pidfile(self.pidfile)
        # Python developers do not want to fix a huge bug with
        # subprocess.Popen and encodings on windows
        # ( http://bugs.python.org/issue1759845 ), so we need to
        # workaround this issue.
        self._pid = my_env.call(self.cmd, shell=True, show=False)
        if self._pid:
            with open(self.pidfile, "w") as f:
                f.write(str(self._pid))

    def terminate(self):
        if self.running:
            my_env.kill_process_pidfile(self.pidfile)
            os.remove(self.pidfile)

class Backend(BackendBase):
    _passwordchars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ01234569"
    _passwordchars_max = len(_passwordchars)-1
    _amuleconf = u'''
        [eMule]
        AppVersion=%(appversion)s
        Nick=%(appname)s
        QueueSizePref=50
        MaxUpload=0
        MaxDownload=0
        SlotAllocation=2
        Port=%(e_port)d
        UDPPort=%(e_udp_port)d
        UDPEnable=1
        Address=
        Autoconnect=1
        MaxSourcesPerFile=300
        MaxConnections=480
        MaxConnectionsPerFiveSeconds=20
        RemoveDeadServer=1
        DeadServerRetry=3
        ServerKeepAliveTimeout=0
        Reconnect=1
        Scoresystem=1
        Serverlist=0
        AddServerListFromServer=1
        AddServerListFromClient=1
        SafeServerConnect=0
        AutoConnectStaticOnly=0
        UPnPEnabled=1
        UPnPTCPPort=50000
        SmartIdCheck=1
        ConnectToKad=%(connect_to_kad)d
        ConnectToED2K=%(connect_to_ed2k)d
        TempDir=%(temp_dir)s
        IncomingDir=%(download_dir)s
        ICH=1
        AICHTrust=0
        CheckDiskspace=1
        MinFreeDiskSpace=1
        AddNewFilesPaused=0
        PreviewPrio=0
        ManualHighPrio=0
        StartNextFile=0
        StartNextFileSameCat=0
        StartNextFileAlpha=0
        FileBufferSizePref=16
        DAPPref=1
        UAPPref=1
        AllocateFullFile=0
        OSDirectory=%(config_dir)s
        OnlineSignature=0
        OnlineSignatureUpdate=5
        EnableTrayIcon=0
        MinToTray=0
        ConfirmExit=1
        StartupMinimized=0
        3DDepth=10
        ToolTipDelay=1
        ShowOverhead=0
        ShowInfoOnCatTabs=1
        VerticalToolbar=0
        GeoIPEnabled=1
        ShowVersionOnTitle=0
        VideoPlayer=
        StatGraphsInterval=3
        statsInterval=30
        DownloadCapacity=300
        UploadCapacity=100
        StatsAverageMinutes=5
        VariousStatisticsMaxValue=100
        SeeShare=2
        FilterLanIPs=1
        ParanoidFiltering=1
        IPFilterAutoLoad=1
        IPFilterURL=
        FilterLevel=127
        IPFilterSystem=0
        FilterMessages=1
        FilterAllMessages=0
        MessagesFromFriendsOnly=0
        MessageFromValidSourcesOnly=1
        FilterWordMessages=0
        MessageFilter=
        ShowMessagesInLog=1
        FilterComments=0
        CommentFilter=
        ShareHiddenFiles=0
        AutoSortDownloads=0
        NewVersionCheck=1
        AdvancedSpamFilter=1
        MessageUseCaptchas=1
        Language=
        SplitterbarPosition=75
        YourHostname=
        DateTimeFormat=%A, %x, %X
        AllcatType=0
        ShowAllNotCats=0
        SmartIdState=0
        DropSlowSources=0
        KadNodesUrl=http://download.tuxfamily.org/technosalad/utils/nodes.dat
        Ed2kServersUrl=
        ShowRatesOnTitle=0
        GeoLiteCountryUpdateUrl=http://geolite.maxmind.com/download/geoip/database/GeoLiteCountry/GeoIP.dat.gz
        StatsServerName=Shorty's ED2K stats
        StatsServerURL=http://ed2k.shortypower.dyndns.org/?hash=
        [Browser]
        OpenPageInTab=1
        CustomBrowserString=
        [Proxy]
        ProxyEnableProxy=0
        ProxyType=0
        ProxyName=
        ProxyPort=1080
        ProxyEnablePassword=0
        ProxyUser=
        ProxyPassword=
        [ExternalConnect]
        UseSrcSeeds=0
        AcceptExternalConnections=1
        ECAddress=%(ec_address)s
        ECPort=%(ec_port)d
        ECPassword=%(ec_password)s
        UPnPECEnabled=0
        ShowProgressBar=1
        ShowPercent=1
        UseSecIdent=1
        IpFilterClients=1
        IpFilterServers=1
        TransmitOnlyUploadingClients=0
        [WebServer]
        Enabled=0
        Password=
        PasswordLow=
        Port=5000
        WebUPnPTCPPort=50001
        UPnPWebServerEnabled=0
        UseGzip=0
        UseLowRightsUser=1
        PageRefreshTime=120
        Template=
        Path=amuleweb
        [GUI]
        HideOnClose=0
        [Razor_Preferences]
        FastED2KLinksHandler=1
        [SkinGUIOptions]
        Skin=
        [Statistics]
        MaxClientVersions=0
        [Obfuscation]
        IsClientCryptLayerSupported=1
        IsCryptLayerRequested=1
        IsClientCryptLayerRequired=0
        CryptoPaddingLenght=254
        CryptoKadUDPKey=%(kadcryptkey)d
        [PowerManagement]
        PreventSleepWhileDownloading=0
        [UserEvents]
        [UserEvents/DownloadCompleted]
        CoreEnabled=0
        CoreCommand=
        GUIEnabled=0
        GUICommand=
        [UserEvents/NewChatSession]
        CoreEnabled=0
        CoreCommand=
        GUIEnabled=0
        GUICommand=
        [UserEvents/OutOfDiskSpace]
        CoreEnabled=0
        CoreCommand=
        GUIEnabled=0
        GUICommand=
        [UserEvents/ErrorOnCompletion]
        CoreEnabled=0
        CoreCommand=
        GUIEnabled=0
        GUICommand=
        [HTTPDownload]
        URL_1=
        ''' .strip() \
            .replace("%(", "\0") \
            .replace("%", "%%")  \
            .replace("\0", "%(") \
            .replace("\n        ", "\n")

    amule_config_dir = "."

    @classmethod
    def is_available(cls):
        return (
            (not ec is None) and
            "AMULE_DAEMON_PATH" in os.environ and
            os.path.isfile(os.environ["AMULE_DAEMON_PATH"])
            )

    @attribute
    def config_dir(self):
        return my_env.get_config_dir()

    @attribute
    def amule_config_dir(self):
        return os.path.abspath(os.path.join(self.config_dir, "amule"))

    @attribute
    def amule_temp_dir(self):
        return os.path.abspath(os.path.join(self.config_dir, "amule_temp"))

    @property
    def amule_pidfile(self):
        return os.path.abspath(os.path.join(self.config_dir, "amule.pid"))

    @attribute
    def amule_download_dir(self):
        return os.path.abspath(os.path.join(self.config_dir,  "amule_finished"))

    _download_dir = None
    @property
    def download_dir(self):
        return self._download_dir

    @download_dir.setter
    def download_dir(self, v):
        self._download_dir = v
        if self.ready:
            # If no daemon is running incoming dir will be taken from
            # config file when fired up, but if is running, must be
            # updated manually
            self.client.set_directory_incoming(self.amule_download_dir)

    _status_cache = None
    @property
    def status(self):
        return self._status_cache

    @property
    def ports(self):
        return (
            ("TCP", -1),
            ("UDP", -1),
            )

    def set_port(self, i, v):
        pass

    _ed2kserversurl = (
        "http://www.shortypower.org/server.met.gz",
        "http://gruk.org/server.met.gz",
        "http://www.peerates.net/servers.met",
        )
    _kadnodesurl = (
        # "http://www.nodes-dat.com/dl.php?load=nodes&trace=%.4f" % ((378350524.167 + time.time() - 1362054700)/10,),
        )
    _connecting_to_kad = False
    def start_daemon(self, kad=True):
        # Auth
        self.ec_port = choose_port()
        self.ec_password = "".join(
            self._passwordchars[random.randint(0, self._passwordchars_max)]
            for i in xrange(256))

        tcp_port, udp_port = [i[1] for i in self.ports]

        # Config vars
        aconfig = {
            "download_dir" : self.amule_download_dir,
            "config_dir": self.amule_temp_dir,
            "temp_dir": self.amule_temp_dir,
            "appname": self.appname,
            "appversion": self.appversion,
            "e_port": choose_port() if tcp_port < 1 else tcp_port,
            "e_udp_port": choose_port() if udp_port < 1 else udp_port,
            "ec_address": "127.0.0.1",
            "ec_port": self.ec_port,
            "ec_password": hashlib.md5(self.ec_password).hexdigest(),
            "kadcryptkey": random.randint(0, 0xFFFFFFFF), # uint32
            "connect_to_kad": True,
            "connect_to_ed2k": True
            }
        # Config value fixing
        for k, v in aconfig.iteritems():
            if isinstance(v, basestring):
                aconfig[k] = v.replace("\\","\\\\")
        if not os.path.isdir(self.amule_config_dir):
            os.makedirs(self.amule_config_dir)
        # Write config file
        f = open(os.path.join(self.amule_config_dir, "amule.conf"), "wb")
        f.write((self._amuleconf % aconfig).encode("utf-8"))
        f.close()
        # Daemon server start
        if my_env.is_windows:
            self.server = WindowsDaemon(self._amuled, self.amule_config_dir, self.amule_pidfile)
        else:
            self.server = PosixDaemon(self._amuled, self.amule_config_dir, self.amule_pidfile)

        if not self.server.pid:
            logger.error("Daemon couldn't be initialized.")
            self.invalidate()
            return

        self.client = ec.Connection(self.ec_password, "localhost", self.ec_port, self.appname, self.appversion)

        for i in xrange(5):
            if self._stopped:
                logger.debug("Daemon backend stopped, cancel connecting")
                return
            try:
                self.client.connect()
                break
            except ec.ConnectionFailedError:
                pass
            except BaseException as e:
                logger.exception(e)
            time.sleep(1)
        else:
            logger.error("Cannot connect to daemon.")
            self.invalidate()
            return

        logger.debug("Amule daemon server initialized.")

        # Network connections requires some work and time due server
        # list updates, so is deferred until now


        #serversurl, nodesurl = faster_url(self._ed2kserversurl, self._kadnodesurl)
        #logger.debug("Using %s and %s" % (serversurl, nodesurl))
        #self.client.update_servers(serversurl, nodesurl)
        #
        logger.debug("Kademlia nodes.dat deactivated.")
        serversurl = faster_url(self._ed2kserversurl)
        self.client.update_servers(serversurl)
        logger.debug("Using %s." % (serversurl, ))

        # Wait for server update
        ed2k_servers = self.client.server_list()
        while not ed2k_servers:
            if self._stopped:
                logger.debug("Daemon backend stopped, cancel ed2k connect")
                return
            time.sleep(0.1)
            ed2k_servers = self.client.server_list()

        # Connect
        self.client.connect_ed2k()
        logger.debug("ed2k connected.")
        # Sometimes, the daemon freezes due KAD network support bugs,
        # so we deactivate
        if kad:
            self._connecting_to_kad = True
            self.client.connect_kad()
        else:
            logger.debug("Kad deactivated.")
        self.ready = True
        if self._connecting_to_kad:
            t = 10
            while t > 0 and not self._stopped:
                time.sleep(0.5) # Security timeout due KAD problems
                t -= 0.5
            self._connecting_to_kad = False

        if self._download_queue: # This must by after self.ready = True
            logger.debug("Adding downloads on queue...")
            while self._download_queue:
                self.download(*self._download_queue.pop())

    _sync_worked_once = True
    _sync_max_numfails = 2
    _sync_numfails = 0
    _sync_restarting_daemon = False

    _last_hashes = frozenset()
    _last_hash = None
    def refresh(self):
        try:
            if self.ready:
                status, dlq, ulq, shd = r = utils.parallelize(
                    self.client.get_status,
                    self.client.show_dl,
                    self.client.show_ul,
                    self.client.show_shared
                    )
                for i in r:
                    if isinstance(i, BaseException):
                        raise i

                # Queue merge (one file can be in two queues)
                downloads = {}
                for queue in (dlq, ulq, shd):
                    is_downloading = queue is dlq
                    for download in queue.itervalues():
                        dhash = download.partfile_hash.encode("hex")
                        if dhash in downloads:
                            downloads[dhash].update(download)
                            downloads[dhash]["is_downloading"] |= is_downloading
                        else:
                            downloads[dhash] = download
                            downloads[dhash]["is_downloading"] = is_downloading

                downloads_changed = downloads != self._data #frozen_cmp(downloads, self._data) != 0

                self._status.update(status)
                self._data = downloads

                if downloads_changed:
                    # Download updates
                    for dhash, download in downloads.iteritems():
                        if dhash in self._downloads:
                            self.outdated_downloads.add(self._downloads[dhash])
                        else:
                            self._downloads[dhash] = Download(self, download, None)
                            self.emit("download_new", self._downloads[dhash])

                    # Removing deleted downloads
                    unowned = not self.manager is self
                    for dhash in frozenset(downloads).symmetric_difference(self._downloads):
                        if self._downloads[dhash].finished:
                            self.outdated_downloads.add(self._downloads[dhash])
                        else:
                            self.emit("download_remove", self._downloads[dhash])
                            if unowned:
                                self.manager.remove(self._downloads[dhash])
                            del self._downloads[dhash]

                self._status_cache = ("",)
            else:
                self._status_cache = ("backend not ready",)
        except ec.ConnectionFailedError as e:
            # Amule daemon is prone to fail
            logger.exception(e)
            self._sync_numfails += 1
            if not self._sync_restarting_daemon and (
              self._connecting_to_kad or
              self._sync_numfails > self._sync_max_numfails
              ):
                # If connection failed during Kad connection or
                # sync failed more than _sync_numfails
                self.ready = False # Revert ready state
                self._sync_restarting_daemon = True
                logger.debug("Max ConnectionFailedError achieved, restarting daemon.")
                self.start_daemon()
                self._sync_restarting_daemon = False
        except BaseException as e:
            # Unexpected errors shouldn't ever happen
            logger.exception(e)
        else:
            # Once daemon starts to response, it should't fails, so
            # whe lower the fail tolerance
            if not self._sync_worked_once:
                self._sync_worked_once = True
                self._sync_max_numfails = 1
            self._sync_numfails = 0
        BackendBase.refresh(self)

    def can_download(self, url):
        if (
         (url.startswith("ed2k://") and "|" in url) or
          url.startswith("magnet:?xt=urn:ed2k:") or
         (url.startswith('magnet:?') and "&xt=urn:ed2k:" in url)
          ):
            return True
        return False

    def count_downloads(self):
        return len(self._downloads)

    @property
    def downloads(self):
        return self._downloads.values()

    @downloads.setter
    def downloads(self, v):
        pass

    @property
    def downspeed(self):
        if self.ready:
            return self._status.stats.dl_speed
        return 0

    @property
    def upspeed(self):
        if self.ready:
            return self._status.stats.ul_speed
        return 0

    ready = False
    _download_queue = None
    def __init__(self, config, app=None, version=None, manager=None):
        BackendBase.__init__(self, config, app, version, manager)
        self._last_state = {}
        self._amuled = os.environ.get("AMULE_DAEMON_PATH")
        self._status = ec.TagDict()
        self._downloads = {}
        self._data = {}
        self._download_queue = []
        self._status_cache = ("starting backend",)
        self._tmp_user_data = {}

    def get_state(self):
        return {
            "downloads": {
                k: v.resume_data for k, v in self._downloads.iteritems()
                }
            }

    def set_state(self, state):
        self._last_state = state or {}
        if "downloads" in state:
            self._downloads.update(
                (k, Download(self, None, v))
                for k, v in state["downloads"].iteritems()
                )

    def run(self):
        self._stopped = False
        if not os.path.isdir(self.amule_download_dir):
            os.makedirs(self.amule_download_dir)
        if not self.ready:
            threading.Thread(target=self.start_daemon).start()

    def pause(self):
        if self.ready:
            self.client.pause_all()

    def resume(self):
        if self.ready:
            self.client.resume_all()

    def download(self, url="", user_data=None):
        '''
        ed2k://|file|<file name>|<size>|<hash>|[s=<url>|][h=<AICH root hash>|][p=<part1 hash>:<part2 hash>:...|][/|sources,<host>:<port>[,<host>:<port>[,...]]|]/
        '''
        if self.ready:
            if self.can_download(url):
                try:
                    self._tmp_user_data[url] = user_data
                    return self.client.add_link(url)
                except ec.ConnectionFailedError as e:
                    logger.exception(e)
                    return False
            else:
                if url.startswith("file://"):
                    urlp = urlparse.urlparse(url).path
                    path = os.path.join(urlp.netloc, urlp.path)
                else:
                    path = url
                path = os.path.abspath(path)
                if os.path.isfile(path):
                    f = open(path, "rb")
                    data = f.read()
                    f.close()
                    if (
                        len(data) > uint32_t.size and
                        uint32_t.unpack(data[:uint32_t.size]) in (
                            COLLECTION_FILE_VERSION1_INITIAL,
                            COLLECTION_FILE_VERSION2_LARGEFILES )
                        ):
                        # binary emulecollection file
                        f = StringIO(data)
                        version = uint32_t.unpack_from(f)
                        numtags = uint32_t.unpack_from(f)
                        # TODO(felipe): implement
                        logger.warn(u"emulecollection binary format is not implemented yet")
                    else:
                        # ascii emulecollection file
                        r = False
                        for i in data.splitlines():
                            if i.strip().startswith("ed2k://"):
                                r |= self.download(i.strip())
                        return r
        elif self.can_download(url):
            self._download_queue.append((url, user_data))
            return True
        return False

    _stopped = False
    def stop(self):
        self._stopped = True
        if self.ready:
            self.client.stop_paused_downloads()
            self.client.shutdown()
            for i in xrange(50):
                time.sleep(0.1)
                if not self.server.running:
                    break
            else:
                logger.warn("daemon didn't shutdown on time, will be killed")
                self.server.terminate()
            self.ready = False

    def __del__(self):
        self.stop()
