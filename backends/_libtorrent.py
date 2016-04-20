#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import os.path
import urlparse
import logging
import urllib2
import itertools
import threading
import shutil

import libtorrent as lt

import utils

from .base import Backend as BackendBase, Download as DownloadBase, choose_port, old_download_dir

logger = logging.getLogger(__name__)

def check_if_torrent_url(url):
    '''torrent files are bencoded dictionaries. That means they starts
    with dN: being N the number of characters of first key.'''
    d = utils.GetURL(url)
    head = d.read(10)
    d.close()
    return head.startswith("d") and head[1:].split(":", 1)[0].isdigit()

class Download(DownloadBase):
    _states = (
        u'queued for checking', u'checking files', u'downloading metadata',
        u'downloading', u'finished', u'seeding', u'allocating',
        u'checking resume data'
        )
    _info = None
    _status = None
    def __init__(self, backend, data, resume_data=None):
        DownloadBase.__init__(self, backend, resume_data)
        self.data = data
        if resume_data:
            self._blacklist_cache = None

    def refresh(self):
        self._status = self.data.status()
        if self._info is None and self.data.has_metadata():
            self._info = self.data.get_torrent_info()
        DownloadBase.refresh(self)

    def resume(self):
        self.backend.outdated_downloads.add(self)
        self.data.auto_managed(False)
        self.data.resume()

    def pause(self):
        self.backend.outdated_downloads.add(self)
        self.data.auto_managed(False)
        self.data.pause()

    def remove(self):
        self.backend.remove_list.append(self)
        self.backend.outdated_downloads.discard(self)

    def recheck(self):
        self.backend.outdated_downloads.add(self)
        self.data.force_recheck()

    def has_metadata(self):
        return self.data.has_metadata()

    def remove_file(self, path):
        if self.has_metadata():
            if not path.startswith(self.download_dir):
                path = os.path.join(self.download_dir, path)
            files = self._info.files()
            if path in files:
                if self._status.upload_mode and not self._status.auto_managed:
                    if not os.path.exists(path):
                        return False
                    if os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                    else:
                        logger.exception("Uncaught remove case: %s %s" % (path, os.stat(path)))
                else:
                    self.data.file_priority(files.index(path))
                self._blacklist_cache = None
                return True
            else:
                prefix = path + os.sep
                if any(i.startswith(prefix) for i in files):
                    for subpath in self.filenames:
                        if subpath.startswith(prefix):
                            self.remove_file(subpath)
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    return True
        return False

    _blacklist_cache = frozenset()
    @property
    def removed_files(self):
        if self._blacklist_cache is None:
            if self.has_metadata():
                self._blacklist_cache = frozenset(
                    unicode(f.path, "utf-8")
                    for f, prio in itertools.izip(self._info.files(), self.data.file_priorities())
                    if prio == 0
                    )
            else:
                self._blacklist_cache = frozenset()
        return self._blacklist_cache

    @property
    def availability(self):
        '''
        How many times file is complete in shard
        '''
        av = self.data.piece_availability()
        if av:
            min_disp = min(av)
            return min_disp + sum((1 for i in av if i > min_disp), 0)/float(len(av))
        return 0

    @property
    def available_peers(self):
        return self._status.num_complete, self._status.num_incomplete

    @property
    def eta(self):
        if self._status:
            rate = self._status.download_payload_rate
            if rate > 0:
                return float(self._status.total_wanted - self._status.total_wanted_done)/rate
        return None

    @property
    def processing(self):
        return self._status.state in (1, 2, 6, 7)

    @property
    def properties(self):
        prop = [
            (_("link"), lt.make_magnet_uri(self.data)),
            (_("hash"), str(self.data.info_hash()).upper()),
            (_("location"), self.download_dir),
            (_("pieces"), self._status.pieces if self._status else []),
            (_("availability"), self.availability),
            (_("state"), self.state),
            ]
        if not self._info is None:
            comment =  self._info.comment()
            if comment:
                prop.append((_("comments"), comment))
            trackers = frozenset(self._info.trackers())
            if trackers:
                prop.append((_("trackers"), "\n".join(i.url for i in trackers).decode("utf8")))
            prop.append((_("files"), "\n".join(sorted(i.path for i in self._info.files())).decode("utf8")))

        return prop

    @property
    def download_dir(self):
        return unicode(self.data.save_path(), "utf-8")

    @download_dir.setter
    def download_dir(self, path):
        if path != self.download_dir:
            self.data.move_storage(path.encode("utf-8"))

    @property
    def filenames(self):
        if self._info is None:
            return []
        return sorted(
            unicode(f.path, "utf-8")
            for f, prio in itertools.izip(self._info.files(), self.data.file_priorities())
            if prio != 0)

    @property
    def original_filenames(self):
        if self._info is None:
            return []
        return sorted(unicode(f.path, "utf-8") for f in self._info.orig_files())

    @property
    def name(self):
        return unicode(self.data.name(), "utf-8")

    @property
    def size(self):
        return self._status.total_wanted

    @property
    def downloaded(self):
        return self._status.total_wanted_done #self._status.total_wanted_done

    @property
    def downloading(self):
        if self._status.paused:
            # Sometimes status is paused and state is outdated
            return False
        return self._status.state in (2, 3)

    @property
    def state(self):
        state = self._status.state
        if self.backend.session.is_paused():
            return u"paused"
        elif self._status.paused:
            return u"queued" if self._status.auto_managed else u"paused"
        elif state == 3 and self._status.num_peers == 0:
            return u"looking for peers"
        elif state in (2,3):
            return u"%s from %d peers" % (self._states[state], self._status.num_peers)
        elif state == 5:
            if self._status.num_peers == 0:
                return u"seeding"
            else:
                return u"seeding %d peers" % (self._status.num_peers)
        return self._states[state]

    @property
    def queued(self):
        if self._status.auto_managed:
            return self._status.paused or self._status.state == 0
        return False

    @property
    def paused(self):
        if self._status.auto_managed:
            return False
        return self._status.paused or self._status.state == 0 or self.backend.session.is_paused()

    @property
    def finished(self):
        return self._status.is_finished

    @property
    def downspeed(self):
        if self._status.num_peers == 0:
            # No peers means downspeed 0
            return 0
        return self._status.download_payload_rate

    @property
    def upspeed(self):
        if self._status.num_peers == 0:
            # No peers means upspeed 0
            return 0
        return self._status.upload_payload_rate

    _files_progress_cache = (0, None)
    @property
    def files_progress(self):
        if self._info is None:
            return {}
        new_progress = self.progress
        old_progress, old_files_progress = self._files_progress_cache
        if old_progress == new_progress:
            if not old_files_progress is None:
                return old_files_progress
            new_files_progress = {
                unicode(f.path, "utf-8"): (0, 0)
                for f in self._info.files()
                }
        else:
            # Expensive operation
            # http://www.rasterbar.com/products/libtorrent/manual.html#file-progress
            progress = self.data.file_progress()
            new_files_progress = {
                unicode(f.path, "utf-8"): (progress[n], f.size)
                for n, f in enumerate(self._info.files())
                }
        self._files_progress_cache = (new_progress, new_files_progress)
        return new_files_progress

    @property
    def progress(self):
        return self._status.progress

    @property
    def sources(self):
        return self._status.num_peers

    def get_state(self):
        handle = self.data
        info = handle.get_torrent_info()
        status = handle.status()
        return {
            "download_dir": self.download_dir,
            "position": self.position,
            "paused": (
                status.paused and
                not status.auto_managed and
                not status.state == 2 # Downloading metadata is paused for libtorrent
                ),
            "checking": status.state == 1,
            "resume_data": lt.bencode(handle.write_resume_data()),
            "torrent": lt.bencode(lt.create_torrent(info).generate()),
            "user_data": self.user_data,
            "hidden": self.hidden,
            "finished": self.finished,
            "filenames": self.filenames,
            }


class Backend(BackendBase):

    @classmethod
    def is_available(cls):
        return not lt is None

    def __init__(self, config, app=None, version=None, manager=None):
        BackendBase.__init__(self, config, app, version, manager)
        self.session = lt.session()
        self.tmp_resume_data = {}
        self.handler_cache = {}
        self.process_lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.state_cache = {}
        self.remove_list = []
        self.force_update = set()

    _status = None

    _version = tuple(int(i) if i.isdigit() else i for i in lt.version.split("."))
    def version(self):
        return self._version

    # Not available yet in 0.16.10
    _savedictflag = lt.save_resume_flags_t.save_info_dict if hasattr(lt.save_resume_flags_t, "save_info_dict") else 0
    _getting_state = False
    def _get_state(self, flush=False):
        if flush:
            self.session.pause() # Pause session
        self._process_alert() # Process alerts (speed up resume data's _process_alert and remove downloads)
        self._getting_state = True
        # Flush and wait for flushes
        with self.save_lock:

            nts = 0
            flushflag = lt.save_resume_flags_t.flush_disk_cache if flush else 0
            downloads = self.downloads[:]
            for download in downloads:
                cacheid = id(download)
                if cacheid in self.state_cache and self.state_cache[cacheid][0] == download.last_update:
                    # We cache resume data for unmodified torrents
                    # (low cache hits with few downloading torrents, but
                    # a lot of hits with a bunch of finished ones)
                    self.torrent_resume_data.append(self.state_cache[cacheid][1])
                else:
                    download.data.save_resume_data( flushflag | self._savedictflag)
                nts += 1
            while nts > len(self.torrent_resume_data):
                self._process_alert()
            session_state = self.session.save_state()
            torrent_resume_data = self.torrent_resume_data[:]
            del self.torrent_resume_data[:] # Clear old resume_data
        self._getting_state = False
        return {
            "session": session_state,
            "torrents": torrent_resume_data
            }

    def get_state(self):
        return self._get_state(True)

    def get_run_state(self):
        return self._get_state()

    def set_state(self, state):
        self.session.load_state(state["session"])
        for resume_data in state["torrents"]:
            if resume_data is None:
                continue
            self.download(resume_data=resume_data)

    _subsystems = ("upnp", "lsd", "natpmp", "dht")
    _extensions = ("ut_metadata", "ut_pex", "smart_ban")
    _port = -1
    def run(self):
        if self.session is None:
            self.session = lt.session()
        self.session.set_alert_mask(lt.alert.category_t.all_categories)

        #self.session.set_dht_settings()
        for i in self._subsystems:
            getattr(self.session, "start_%s" % i)()

        for i in self._extensions:
            self.session.add_extension(getattr(lt, "create_%s_plugin" % i))

        settings = lt.session_settings()
        settings.use_parole_mode = True
        settings.prioritize_partial_pieces = True
        settings.prefer_udp_trackers = True
        settings.user_agent = '%s/%s libtorrent/%d.%d' % (
            self.appname, self.appversion, lt.version_major, lt.version_minor)
        # settings.share_ratio_limit = float(self.manager.get_setting('upload_ratio', 0))

        settings.use_dht_as_fallback = False # Use DHT for tracker torrent too

        settings.ignore_resume_timestamps  = True # Allow resume
        settings.announce_to_all_trackers = True # Announce to all trackers by tier
        settings.announce_to_all_tiers = True # like uTorrent

        self.session.set_settings(settings)

        self.config.on("max_downspeed", lambda k, v: self._set_max_downspeed(v))
        self.config.on("max_upspeed", lambda k, v: self._set_max_upspeed(v))
        self.config.on("max_active_downloads", lambda k, v: self._set_max_active_downloads(v))
        self.config.on("max_connections", lambda k, v: self._set_max_connections(v))
        self.config.on("max_half_open_connections", lambda k, v: self._set_max_half_open_connections(v))
        self.config.on("port_%s_0" % self.name, lambda k, v: self.set_port(0, v))

        self.torrent_resume_data = []
        self.num_flushes = 0
        self.set_port(0, self._port)

    def stop(self):
        for i in self._subsystems:
            getattr(self.session, "stop_%s" % i)()

        if hasattr(self.session, "close"): # 0.16+
            self.session.close()
            self.session = None
        else:
            self.session.pause()

    def pause(self):
        for i in self.downloads:
            i.pause()

    def resume(self):
        if self.session is None:
            self.run()
        #self.session.resume()
        for i in self.downloads:
            i.resume()

    def can_download(self, url):
        if (
          url.startswith('magnet:?xt=urn:btih:') or
         (url.startswith('magnet:?') and "&xt=urn:btih:" in url) or
          url.startswith('http://') or
          url.startswith('https://')):
            return True
        elif url.startswith("file://") and url.endswith(".torrent"):
            return True
        return False

    _html_url_unescape = {
        "&amp;": "&"
        }
    def download(self, url=None, user_data=None, resume_data=None):
        atp = {
            "save_path": self.download_dir.encode("utf-8"),
            "storage_mode": lt.storage_mode_t.storage_mode_sparse, #lt.storage_mode_t.storage_mode_allocate,
            "paused": False,
            "auto_managed": True,
            "duplicate_is_error": False,
            "override_resume_data": True, # for manual pause handling
            }
        if resume_data:
            atp["save_path"] = resume_data.get("download_dir", old_download_dir).encode("utf-8")
            if "resume_data" in resume_data:
                atp["resume_data"] = resume_data["resume_data"]
            if "url" in resume_data:
                atp["url"] = resume_data["url"]
            if "torrent" in resume_data:
                atp["ti"] = lt.torrent_info(lt.bdecode(resume_data["torrent"]))
            if "paused" in resume_data:
                atp["paused"] = resume_data["paused"]
                atp["auto_managed"] = not resume_data["paused"]
            if resume_data.get("finished", False) or resume_data.get("hidden", False):
                atp["upload_mode"] = True
                atp["auto_managed"] = False # prevents libtorrent from change upload_mode
                atp["storage_mode"] = lt.storage_mode_t.storage_mode_sparse # otherwise libtorrent generates null files
                resume_data["hidden"] = True
        elif self.can_download(url):
            if not url.startswith("magnet:?"):
                if not check_if_torrent_url(url):
                    return False
            for k, v in self._html_url_unescape.iteritems():
                url = url.replace(k, v)
            atp["url"] = str(url)
            resume_data = {"url": url.encode("utf-8"), "user_data": user_data}
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
                try:
                    atp["ti"] = lt.torrent_info(lt.bdecode(data))
                except BaseException:
                    return False
                resume_data = {"torrent": data, "user_data": user_data}
        if "url" in atp or "ti" in atp: # is atp valid?
            try:
                resume_data_id = str(atp["ti"].info_hash()) if "ti" in atp else atp["url"]
                self.tmp_resume_data[resume_data_id] = resume_data
                self.session.async_add_torrent(atp)
                return True
            except RuntimeError as e:
                # Torrent already in session
                logger.warn(e)
        return False

    def get_download_for_handle(self, torrent_handle):
        for download in self.downloads:
            if download.data == torrent_handle:
                return download
        return None

    _vpiece = {
        ("\0","\0"):"\0",
        ("\0","\1"):"\2",
        ("\1","\0"):"\1",
        ("\1","\1"):"\2",
        }
    def handle_save_resume_data_alert(self, alert):
        download = self.get_download_for_handle(alert.handle)
        if download:
            resume_data = download.get_state()
            self.state_cache[id(download)] = (download.last_update, resume_data)
            self.torrent_resume_data.append(resume_data)
        else:
            logger.error("Failed to save data for unhandled torrent.")

    def handle_save_resume_data_failed_alert(self, alert):
        handle = alert.handle
        status = handle.status()
        download = self.get_download_for_handle(handle)
        if download:
            logger.debug("Failed to save data for torrent. Using old resume data.")
            resume_data = download.resume_data
            resume_data["download_dir"] = download.download_dir
            resume_data["position"] = download.position
            resume_data["paused"] = status.paused and not status.auto_managed and not status.state == 3
            resume_data["user_data"] = download.user_data
            self.state_cache[id(download)] = (download.last_update, resume_data)
            self.torrent_resume_data.append(resume_data)
        else:
            logger.error("Failed to save data for unhandled torrent.")

    # FIXME(felipe): never sent as cannot find flush_cache on torrent_handle
    def handle_flushed_cache_alert(self, alert):
        self.num_flushes += 1

    @classmethod
    def get_trackers_from_resume_data(cls, resume_data, old_trackers):
        old_urls = frozenset(
            tracker["url"] + (":80" if not ":" in tracker["url"].rsplit(".", 1)[-1] else "")
            for tracker in old_trackers
            )
        if resume_data:
            if "ti" in resume_data:
                for tracker in resume_data["ti"].trackers:
                    url = urllib2.unquote(tracker[3:])
                    if not ":" in url.rsplit(".", 1)[-1]:
                        url += ":80"
                    if not url in old_urls:
                        yield url
            #magnet:?xt=urn:btih:{ 40 or 32 bytes }&dn={ torrent name }&tr=udp%3A%2F%2Ftracker.example1.com%3A80&tr=udp%3A%2F%2Ftracker.example2.com%3A80
            elif "url" in resume_data:
                url = resume_data["url"]
                if url.startswith('magnet:?xt=urn:btih:') and "&tr" in url:
                    for i in url[20:].split("&"):
                        if i.startswith("tr="):
                            url = urllib2.unquote(i[3:])
                            if not ":" in url.rsplit(".", 1)[-1]:
                                url += ":80" # adds default port if no port is added
                            if not url in old_urls:
                                yield url

    def handle_add_torrent_alert(self, alert):
        error_code = alert.error.value()

        # Try to get custom resume data from tmp for preserving it
        # between sessions.
        resume_data_ids = []
        if "ti" in alert.params and alert.params["ti"]:
            resume_data_ids.append(str(alert.params["ti"].info_hash()))
        if "url" in alert.params:
            resume_data_ids.append(alert.params["url"])
        if "info_hash" in alert.params:
            resume_data_ids.append(str(alert.params["info_hash"]))
        for i in resume_data_ids:
            if i and i in self.tmp_resume_data:
                resume_data = self.tmp_resume_data.pop(i)
                break
        else:
            #logger.warn("No resume data for %s" % resume_data_ids)
            resume_data = {}

        if error_code == 0:
            torrent_handle = alert.handle
            torrent_handle.scrape_tracker() # Scrape tracker for data (obviously async)
            download = self.get_download_for_handle(torrent_handle)
            if download:
                # Skip duplicated torrents add update its trackers
                if torrent_handle.is_valid() and torrent_handle.has_metadata():
                    # tracker update
                    info = torrent_handle.get_torrent_info()
                    for i in self.get_trackers_from_resume_data(resume_data, torrent_handle.trackers()):
                        info.add_tracker(i, 0)
                # Updating user data
                if "user_data" in resume_data:
                    download.user_data = resume_data["user_data"]
                # reannounce on new trackers
                torrent_handle.force_reannounce()
                torrent_handle.force_dht_announce()
                self.outdated_downloads.add(download)
            else:
                if "position" in resume_data and (
                  resume_data["position"] < 0 or
                  not isinstance(resume_data["position"], int)
                  ):
                    del resume_data["position"]
                if resume_data.get("checking", False):
                    torrent_handle.force_recheck()
                #torrent_handle.set_max_connections(60)
                #torrent_handle.set_max_uploads(-1)
                download = Download(self, torrent_handle, resume_data)
                download.refresh()
                self.downloads.append(download)
                self.emit("download_new", download)

    def handle_torrent_alert(self, alert):
        # convenience handler for torrent alerts
        download = self.get_download_for_handle(alert.handle)
        if download:
            self.outdated_downloads.add(download)

    def handle_torrent_finished_alert(self, alert):
        alert.handle.auto_managed(False)
        alert.handle.set_upload_mode(True)
        self.handle_torrent_alert(alert)

    def handle_scrape_reply_alert(self, alert):
        download = self.get_download_for_handle(alert.handle)
        if download:
            self.outdated_downloads.add(download)

    def handle_torrent_paused_alert(self, alert):
        status = alert.handle.status()
        if status.auto_managed:
            # libtorrent pause when automanaged uses graceful_pause, it means
            # peers are not disconnected inmedatelu but sharing until finished.
            # The problem is libtorrent do not emit update events once paused
            # so we need to keep emiting updates for this files
            # https://code.google.com/p/libtorrent/issues/detail?id=524
            if status.download_payload_rate or status.upload_payload_rate:
                self.force_update.add(self.get_download_for_handle(alert.handle))
        self.handle_torrent_alert(alert)

    def handle_scrape_failed_alert(self, alert):
        if hasattr(alert, "msg"): # documented way
            logger.debug("Scrape failed: %s" % alert.msg)
        else: # inherited from base alert
            logger.debug("Scrape failed: %s" % alert.message())

    handle_stats_alert = handle_torrent_alert # every second approx.
    handle_state_changed_alert = handle_torrent_alert
    handle_torrent_resumed_alert = handle_torrent_alert
    handle_storage_moved_alert = handle_torrent_alert
    #handle_block_finished_alert = handle_torrent_alert
    #handle_metadata_received_alert = handle_torrent_alert

    def _process_alert_tasks(self):
        alert = self.session.pop_alert()
        while alert:
            name = "handle_%s" % type(alert).__name__
            try:
                if self.handler_cache[name]:
                    yield (self.handler_cache[name], (alert,))
            except KeyError:
                if hasattr(self, name):
                    handler = getattr(self, name)
                    self.handler_cache[name] = handler
                    yield (handler, (alert,))
                else:
                    self.handler_cache[name] = None
            else:
                alert = self.session.pop_alert()

    def _process_alert(self):
        with self.process_lock:
            # Alert processing
            for fnc, args in self._process_alert_tasks():
                fnc(*args)

            # Deferred download remove
            if self.remove_list and not self._getting_state:
                rmcp = frozenset(self.remove_list)
                self.remove_list[:] = ()

                if self.manager is self:
                    download_lists = (self.downloads,)
                else:
                    download_lists = (self.downloads, self.manager.downloads)

                for download in rmcp.intersection(self.downloads):
                    self.emit("download_remove", download)
                    for download_list in download_lists:
                        if download in download_list:
                            download_list.remove(download)
                    if download in self.outdated_downloads:
                        self.outdated_downloads.remove(download)
                    self.session.remove_torrent(download.data, lt.options_t.delete_files)

    def refresh(self):
        # Update status
        self._status = self.session.status()

        # Forced updated
        self.outdated_downloads.update(self.force_update)
        for download in self.force_update:
            status = download.data.status()
            if status.download_payload_rate == status.upload_payload_rate == 0:
                # Once download_payload_rate and upload_payload_rate value 0
                # is raised, forcing update is no longer needed
                self.force_update.remove(download)

        # Processing events
        self._process_alert()

        # We only have
        if self.outdated_downloads:
            # unowned download list sort
            if not self is self.manager:
                self.downloads.sort(key=lambda d: d.position)

            # libtorrent queue position adjustement
            for n, download in enumerate(self.downloads):
                queue_position = download.data.queue_position()
                if n > queue_position:
                    for i in xrange(queue_position, n):
                        download.data.queue_position_down()
                else:
                    for i in xrange(n, queue_position):
                        download.data.queue_position_up()

        BackendBase.refresh(self) # Call downloads refresh and emit updates

    @property
    def downspeed(self):
        return self._status.payload_download_rate

    @property
    def upspeed(self):
        return self._status.payload_upload_rate

    def _set_max_upspeed(self, v):
        s = self.session.settings()
        s.upload_rate_limit = max(v, 0) # zero means unlimited
        self.session.set_settings(s)

    def _set_max_downspeed(self, v):
        s = self.session.settings()
        s.download_rate_limit = max(v, 0) # zero means unlimited
        self.session.set_settings(s)

    def _set_max_active_downloads(self, v):
        # TODO(felipe): test if resetting all active torrents to
        #               automanaged state is an expected behavior
        #
        s = self.session.settings()
        s.active_downloads = max(v, -1) # -1 means unlimited
        self.session.set_settings(s)

    def _set_max_connections(self, v):
        s = self.session.settings()
        s.connections_limit = max(v, -1) # -1 means unlimited
        self.session.set_settings(s)

    def _set_max_half_open_connections(self, v):
        s = self.session.settings()
        s.half_open_limit = max(v, -1) # -1 means unlimited
        self.session.set_settings(s)

    @property
    def ports(self):
        return (
            ("TCP/UDP", self.session.listen_port() if self.session else -1),
            )

    def set_port(self, i, v):
        if i == 0:
            self._port = choose_port() if v == -1 else v
            if self.session:
                self.session.listen_on(self._port, 65535)
