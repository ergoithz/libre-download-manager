# -*- coding: utf-8 -*-

"""
Linux-specific functions.

All the functionality that is system-dependent should appear here,
implemented for a linux system.
"""

import sys
import os.path
import atexit
import subprocess
import logging
import shutil

import dbus


# Global State.
#
# These variables get initialized when calling init(), which happens
# at the very beginning in front.py
class state:
    global_options_changed = set()  # options changed with gsettings
    screensaver_cookie = None
    prevent_screensaver = False
    exename = ''        # name of the application executable
    autostart_dir = ''  # directory with .desktop files that get run at startup
    is_frozen = False   # are we running an executable made with pyinstaller?



def init(appname, is_frozen):
    "Initialize the global variables that will be often used"

    state.exename = appname.lower().replace(' ', '-')  # Foo Bar -> foo-bar
    state.is_frozen = is_frozen

    # Find autostart directory following XDG conventions
    cdir = os.environ.get('XDG_CONFIG_HOME', os.environ['HOME'] + '/.config')
    state.autostart_dir = cdir + '/autostart'

    # Get the path to the base directory where all the resources are
    # (similar to config/__init__.py:RESOURCESDIR but we cannot
    # "import config" here).
    if is_frozen:
        state.RESOURCESDIR = sys._MEIPASS
    elif ('/site-packages' in __file__ or
          '/dist-packages' in __file__):  # we have python setup.py install-ed
        state.RESOURCESDIR = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../..'))
    else:
        state.RESOURCESDIR = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..'))



def change_desktop_option(option):
    "Set a desktop option and put it back when exiting if changed"

    # For example, option can be:
    #   org.gnome.desktop.screensaver idle-activation-enabled false
    #   org.gnome.desktop.session idle-delay 0
    #   org.gnome.settings-daemon.plugins.power active false

    try:
        schema, key, new_value = option.split()
        old_value = subprocess.check_output(
            ["gsettings", "get", schema, key]).strip().lower()
        if old_value != new_value:
            if (schema, key) not in state.global_options_changed:
                # Prepare it so that on exit it puts back its old value
                state.global_options_changed.add( (schema, key) )
                atexit.register(lambda: subprocess.call([
                    "gsettings", "set", schema, key, old_value]))
            subprocess.check_call(["gsettings", "set", schema, key, new_value])
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        logging.warning("Trying to set %s, did not work: %s" % (option, e))
        return False



def set_sleep_mode(active, reason):
    "Sets or unsets the sleep mode"

    # This would work in gnome
    return change_desktop_option(
        "org.gnome.settings-daemon.plugins.power active false")



def set_screensaver_mode(active, reason):
    "Sets or unsets the screensaver and return True if it worked, False if not"

    try:
        # Do it in a general way that works in any xdg-compliant desktop.
        bus = dbus.SessionBus()
        iface = dbus.Interface(
            bus.get_object('org.freedesktop.ScreenSaver',
                           '/org/freedesktop/ScreenSaver'),
            'org.freedesktop.ScreenSaver')
        if active:
            # We want it active
            state.prevent_screensaver = False
            if state.screensaver_cookie != None:
                # But we had inhibited it, so uninhibit!
                iface.UnInhibit(state.screensaver_cookie)
                state.screensaver_cookie = None
            # Else, nothing to do, it was not inhibited
        else:
            # We want the screensaver inhibited
            state.prevent_screensaver = True
            if not state.screensaver_cookie:
                # But we have not inhibited it yet
                state.screensaver_cookie = iface.Inhibit(
                    "downloader", reason)
            # Else, nothing to do, it was already inhibited
    except Exception as e:
        # This would work in gnome
        change_desktop_option("org.gnome.desktop.session idle-delay 0")
        change_desktop_option("org.gnome.desktop.screensaver "
                              "idle-activation-enabled false")
    return True



def idleness_tick():
    "Try to do something if we are preventing the screensaver from starting"

    if state.prevent_screensaver:
        try:  # simulate user pressing a key (the shift key)
            subprocess.check_call(["xdotool", "key", "shift"])
        except (subprocess.CalledProcessError, OSError) as e:
            pass  # well, at least we tried



def get_default_for_torrent():
    "Is the app the default handler for torrents?"

    try:
        prog_bt = subprocess.check_output(['xdg-mime', 'query', 'default',
                                           'application/x-bittorrent']).strip()
        prog_mag = subprocess.check_output(['xdg-mime', 'query', 'default',
                                            'x-scheme-handler/magnet']).strip()
        return (prog_bt == state.exename and prog_mag == state.exename)
    except (subprocess.CalledProcessError, OSError) as e:
        logging.warning("Trying to query with xdg-mime did not work: %s" % e)
        return False  # assume that it is not, what can we do?



def set_default_for_torrent():
    "Set the app as the default handler for torrents and mangets"

    try:
        desktop_f = '%s/data/%s.desktop' % (state.RESOURCESDIR, state.exename)
        for mime in ["x-scheme-handler/magnet", "application/x-bittorrent"]:
            subprocess.call(["xdg-mime", "default", desktop_f, mime])
    except (subprocess.CalledProcessError, OSError) as e:
        logging.warning("Trying to use xdg-mime did not work: %s" % e)



def get_run_startup():
    "Is the app started at startup?"

    # See http://standards.freedesktop.org/autostart-spec/autostart-spec-latest.html
    desktop_name = '%s.desktop' % state.exename
    return (desktop_name in os.listdir(state.autostart_dir))



def set_run_startup(value):
    "Enables/disables starting automatically the app (for value=True/False)"

    if value:
        # Copy the .desktop file in the autostart directory
        desktop_f = '%s/data/%s.desktop' % (state.RESOURCESDIR, state.exename)
        shutil.copy(desktop_f, state.autostart_dir)
    else:
        path = state.autostart_dir + '/%s.desktop' % state.exename
        if os.path.exists(path):
            os.remove(path)
