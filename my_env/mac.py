#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os.path
import plistlib
import ctypes
import CoreFoundation as CF
import objc
import logging

class state:
    framework = None
    prevent_sleep_assertion = None

def init(is_frozen):
    # init the IOKit framework for sleep assertions
    state.framework = SetUpIOFramework()
    
    if is_frozen:
        global CF
        CF = CF.CoreFoundation

def prevent_sleep(reason):
    # do nothing if it is already preventing sleep
    if state.prevent_sleep_assertion:
        return

    # create the assertion and save the ID
    ret, a_id = AssertionCreateWithName(state.framework, 'NoIdleSleepAssertion', 255, reason)
    if ret:
        state.prevent_sleep_assertion = a_id

def unprevent_sleep():
    # Do nothing if it is not preventing sleep
    if not state.prevent_sleep_assertion:
        return

    # finally, release the assertion of the ID we saved earlier
    AssertionRelease(state.framework, state.prevent_sleep_assertion)
    state.prevent_sleep_assertion = None

def get_run_startup():
    try:
        pl = plistlib.readPlist(os.path.expanduser("~/Library/LaunchAgents/" + os.path.basename(sys.executable) + ".plist"))
        return pl.get("RunAtLoad", False)
    except IOError: # File does not exist
        return False

def set_run_startup(appname, value):
    plist_path = os.path.expanduser("~/Library/LaunchAgents/" + os.path.basename(sys.executable) + ".plist")
    try:
        pl = plistlib.readPlist(plist_path)
        pl["RunAtLoad"] = value
    except IOError: # File does not exist
        pl = {"Label": appname,
              "ProgramArguments": [ sys.executable ],
              "LimitLoadToSessionType": "Aqua",
              "RunAtLoad": value,
              "StandardErrorPath": "/dev/null",
              "StandardOutPath": "/dev/null",
             }
    plistlib.writePlist(pl, plist_path)

def SetUpIOFramework():
    # load the IOKit library
    framework = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/IOKit.framework/IOKit')

    # declare parameters as described in IOPMLib.h
    framework.IOPMAssertionCreateWithName.argtypes = [
        ctypes.c_void_p,  # CFStringRef
        ctypes.c_uint32,  # IOPMAssertionLevel
        ctypes.c_void_p,  # CFStringRef
        ctypes.POINTER(ctypes.c_uint32)]  # IOPMAssertionID
    framework.IOPMAssertionRelease.argtypes = [
        ctypes.c_uint32]  # IOPMAssertionID
    return framework

def StringToCFString(string):
    # we'll need to convert our strings before use
    return objc.pyobjc_id(
        CF.CFStringCreateWithCString(None, string,
            CF.kCFStringEncodingASCII).nsstring())

def AssertionCreateWithName(framework, a_type,
                            a_level, a_reason):
    # this method will create an assertion using the IOKit library
    # several parameters
    a_id = ctypes.c_uint32(0)
    a_type = StringToCFString(a_type)
    a_reason = StringToCFString(a_reason)
    a_error = framework.IOPMAssertionCreateWithName(
                        a_type, a_level, a_reason, ctypes.byref(a_id))

    # we get back a 0 or stderr, along with a unique c_uint
    # representing the assertion ID so we can release it later
    return a_error==0, a_id

def AssertionRelease(framework, assertion_id):
    # releasing the assertion is easy, and also returns a 0 on
    # success, or stderr otherwise
    return framework.IOPMAssertionRelease(assertion_id)
