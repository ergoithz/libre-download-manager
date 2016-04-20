#!/usr/bin/env python
# -*- coding: utf-8 -*-

import types
import os
import logging
import functools
import itertools
import re
import math
import random
import threading
import time
import platform
import sys
import urllib
import urlparse

try:
    import simplejson as json
except ImportError:
    import json

# TODO(felipe): uncomment for cairo
import cairo

import wx
import wx.xrc
import wx.stc
import wx.lib.newevent
import wx.lib.wxcairo

import pango
import pangocairo

import utils
import config
import my_env

from constants import theme

import mplayerctrl

if my_env.is_windows:
    try:
        import my_env.win32 as win32
    except:
        win32 = None
    try:
        import webview_ie as html2
    except:
        import wx.html2 as html2
else:
    win32 = None
    import wx.html2 as html2


logger = logging.getLogger(__name__)

# Utility functions (here for classes)
def void(arg, *args, **kwargs):
    return arg

def setextuple(tup, index, value, fill=None):
    '''
    Create a new tuple replacing the element 'index' on tuple by 'value'.
    If tuple is not big enough to set 'value' in 'index', will be filled
    by 'fill' values, which defaults to None.
    '''
    size = len(tup)
    if size < index:
        return tup + (fill, )*(index-size) + (value, )
    return tup[:index] + (value, ) + tup[index+1:]

class rgba(tuple):
    '''
    Internal tuple representation of a colour as given by theme.py
    '''
    def __new__(cls, colour):
        r = g = b = 0
        a = 1
        if isinstance(colour, int):
            r = colour >> 16 & 0xFF
            g = colour >> 8 & 0xFF
            b = colour & 0xFF
        elif isinstance(colour, tuple):
            r = min(max(colour[0], 0), 255)
            g = min(max(colour[1], 0), 255)
            b = min(max(colour[2], 0), 255)
            if len(colour) > 3:
                a = min(max(colour[3], 0), 1)
        return tuple.__new__(cls, (r, g, b, a))

def themeWxColour(colour):
    r, g, b, a = rgba(colour)
    return wx.Colour(r, g, b, a*255)

def themeCairoRGBA(colour):
    r, g, b, a = rgba(colour)
    return (r/255., g/255., b/255., a)

def wxSysCairoRGBA(wx_color_constant):
    return wxColourCairoRGBA(wx.SystemSettings.GetColour(wx_color_constant))

def wxColourCairoRGBA(colour):
    return (colour.Red()/255., colour.Green()/255., colour.Blue()/255., colour.Alpha()/255.)

def wxColourCSS(wx_colour):
    return "rgb(%s)" % ",".join(str(i) for i in wx_colour)

def cairo_fill_path(context, fill=None, border=None, shadow=None, border_width=1, shadow_width=1, preserve=False):

    old_join = context.get_line_join()
    context.set_line_join(cairo.LINE_JOIN_ROUND)

    if shadow and shadow_width > 0:
        for step in xrange(shadow_width, 0, -1):
            context.set_line_width(step*2)
            context.set_source_rgba(border[0], border[1], border[2], border[3]*step/shadow_width)
            context.stroke_preserve()

    if border and border_width > 0:
        context.set_line_width(border_width*2)
        context.set_source_rgba(*border)
        context.stroke_preserve()

    if fill:
        context.set_source_rgba(*fill)
        context.fill_preserve()

    if not preserve:
        context.new_path()

    context.set_line_join(old_join)

_pango_wxwindow_font_bold = {
    wx.FONTWEIGHT_NORMAL: pango.WEIGHT_NORMAL,
    wx.FONTWEIGHT_LIGHT: pango.WEIGHT_NORMAL,
    wx.FONTWEIGHT_BOLD: pango.WEIGHT_BOLD,
    }
_pango_wxwindow_font_style = {
    wx.FONTSTYLE_NORMAL: pango.STYLE_NORMAL,
    wx.FONTSTYLE_SLANT: pango.STYLE_OBLIQUE,
    wx.FONTSTYLE_ITALIC: pango.STYLE_ITALIC,
    }

def get_font_desc(wxwindow, context, size=-1, bold = False):

    font = wxwindow.GetFont()
    if bold:
        font.SetWeight(wx.FONTWEIGHT_BOLD)
    if size != -1:
        font.SetPointSize(size if size > 0 else font.GetPointSize() * abs(size))

    font_desc = pango.FontDescription(font.GetFaceName())
    font_desc.set_style(_pango_wxwindow_font_style[font.GetStyle()])
    font_desc.set_weight(_pango_wxwindow_font_bold[font.GetWeight()])
    font_desc.set_size(font.GetPointSize()*pango.SCALE)

    return font_desc


def get_text_layout(text, context, font_desc, rect, align=wx.ALIGN_LEFT | wx.ALIGN_TOP):

    pangocairo_context = pangocairo.CairoContext(context)

    layout = pangocairo_context.create_layout()
    layout.set_single_paragraph_mode(True)
    layout.set_font_description(font_desc)
    layout.set_text(text)

    x, y, width, height = rect.Get()
    drawing = [i/pango.SCALE for i in layout.get_size()]

    if align & wx.ALIGN_CENTER_VERTICAL:
        y += (height-drawing[1])/2.
    elif align & wx.ALIGN_BOTTOM:
        y += height-drawing[1]

    if align & wx.ALIGN_CENTER_HORIZONTAL:
        x+=(width-drawing[0])/2.
    elif align & wx.ALIGN_RIGHT:
        x+=width-drawing[0]

    return wx.Rect(x, y, drawing[0], drawing[1]), layout, pangocairo_context

def pango_text_path(text, context, font_desc, rect, align=wx.ALIGN_LEFT | wx.ALIGN_TOP):
    rect, layout, pangocairo_context = get_text_layout(text, context, font_desc, rect, align)
    context.move_to(rect[0], rect[1])
    pangocairo_context.set_antialias(cairo.ANTIALIAS_SUBPIXEL)
    pangocairo_context.layout_path(layout)
    return rect


def cairo_rounded_rectangle(context, x, y, width, height, radius=0):
    """ draws rectangles with rounded (circular arc) corners """
    v1 = x
    v2 = x + width
    v3 = y
    v4 = y + height
    hpi = math.pi/2
    radius = min(width/2., height/2., radius)
    context.arc(v1 + radius, v3 + radius, radius, math.pi, 3*hpi)
    context.arc(v2 - radius, v3 + radius, radius, 3*hpi, 2*math.pi)
    context.arc(v2 - radius, v4 - radius, radius, 0, hpi)
    context.arc(v1 + radius, v4 - radius, radius, hpi, math.pi)
    context.close_path()


class WxImpersonator(object):
    def PropagateColours(self, who=None):
        if who is None:
            who = self
        bg = who.GetBackgroundColour()
        fg = who.GetForegroundColour()

        childs = set(who.GetChildren())
        while childs:
            child = childs.pop()
            if child.ShouldInheritColours():
                child.SetBackgroundColour(bg)
                child.SetForegroundColour(fg)
                child.Refresh()
                childs.update(child.GetChildren())

    @classmethod
    def match_base(cls, *bases):
        parents = list(cls.__bases__)
        bases = frozenset(bases)
        while parents:
            intersection = bases.intersection(parents)
            if intersection:
                return iter(intersection).next()
            parents[:] = (gp for p in parents for gp in p.__bases__ if hasattr(p, "__bases__"))
        return None

    @classmethod
    def Impersonate(cls, other, **kwargs):
        if isinstance(other, WxProxy):
            other = WxProxy.unproxize(other)
        base = cls.match_base(wx.StatusBar, wx.Gauge, wx.ToolBar, wx.StaticText, wx.Control, wx.Dialog, wx.Window)

        # Instantiation
        if base is wx.Window:
            new = cls(other.GetParent(), other.GetId(),
                      other.GetPosition(), other.GetSize(),
                      other.GetWindowStyleFlag(), other.GetName(),
                      **kwargs)
            WxToolBarProxy.release(other)

            # Visibility
            if not other.IsShown():
                new.Show(False)

        elif base is wx.Dialog:
            new = cls(other.GetParent(), other.GetId(),
                      other.GetTitle(), other.GetPosition(),
                      other.GetSize(),
                      other.GetWindowStyleFlag(), other.GetName(),
                      **kwargs)
        elif base is wx.StaticText:
            size = other.GetSize() if other.GetWindowStyleFlag() & wx.ST_NO_AUTORESIZE else wx.Size(-1, -1)
            new = cls(other.GetParent(), other.GetId(),
                      other.GetLabel(), other.GetPosition(), size,
                      other.GetWindowStyleFlag(),
                      other.GetName())
        elif base is wx.Control:
            validator = other.GetValidator() if hasattr(other, "GetValidator") else None
            new = cls(other.GetParent(), other.GetId(),
                      other.GetPosition(), other.GetSize(),
                      other.GetWindowStyleFlag(),
                      validator or wx.DefaultValidator, other.GetName(),
                      **kwargs)
        elif base is wx.StatusBar:
            new = cls(other.GetParent(), other.GetId(),
                      other.GetWindowStyleFlag(), other.GetName(),
                      **kwargs)
            new.SetFieldsCount(other.GetFieldsCount())
        else:
            raise NotImplementedError, "Cannot impersonate class %s" % cls.__name__

        # Property replace on top level parent
        parentframe = other.GetTopLevelParent()
        if isinstance(parentframe, (wx.Frame, wx._core.Frame)):
            if  other == parentframe.GetToolBar():
                parentframe.SetToolBar(new if base is wx.ToolBar else None)
            elif other == parentframe.GetStatusBar():
                parentframe.SetStatusBar(new if base is wx.StatusBar else None)

        # Other properties
        new.SetMinSize([max(i) for i in zip(new.GetMinSize(), other.GetMinSize())])
        new.SetExtraStyle(other.GetExtraStyle())
        new.SetFont(other.GetFont())

        if other.ShouldInheritColours() and not hasattr(new, "ShouldInheritColours"):
            new.ShouldInheritColours = lambda: True

        #new.SetBackgroundColour(other.GetBackgroundColour())
        new.SetToolTipString(other.GetToolTipString() or "")
        #new.SetForegroundColour(other.GetForegroundColour())

        if isinstance(other, (wx.Gauge, wx._core.Gauge)):
            new.SetRange(other.GetRange())
            new.SetValue(other.GetValue())
        elif isinstance(other, (wx.BitmapButton, wx._core.BitmapButton)):
            new.SetBitmap(other.GetBitmap())
            new.SetBitmapDisabled(other.GetBitmapDisabled())
            new.SetBitmapFocus(other.GetBitmapFocus())
            new.SetBitmapHover(other.GetBitmapHover())
            new.SetBitmapLabel(other.GetBitmapLabel())
            new.SetBitmapSelected(other.GetBitmapSelected())

        # Remove other from parent
        parent = other.GetParent()
        if parent:
            parent.RemoveChild(other)
        wx.CallAfter(other.Destroy)

        # Replacing on parent sizer
        parent_sizer = other.GetContainingSizer()
        if parent_sizer:
            parent_sizer.Replace(other, new)

        # Adding other sizer content to new
        sizer = other.GetSizer()
        if sizer:
            other.SetSizer(None, False)
            boxes = {sizer}
            while boxes:
                for sizeritem in boxes.pop().GetChildren():
                    if sizeritem.IsWindow():
                        sizeritem.GetWindow().Reparent(new)
                    elif sizeritem.IsSizer():
                        boxes.add(sizeritem.GetSizer())
            new.SetSizer(sizer)

        # Get extra attributes from parent
        new.InheritAttributes()

        # Impersonation event
        new.ProcessEvent(ImpersonateEvent(new=new, other=other))
        return new


class WxDragger(object):
    def __init__(self, target=None, border=5):
        self.__dbinded = set()
        self.__rbinded = set()
        self.__dtimer = wx.Timer(self, wx.ID_ANY)
        self.__rtimer = wx.Timer(self, wx.ID_ANY)
        self.__ctimer = wx.Timer(self, wx.ID_ANY)
        self.__border = border
        self.Bind(wx.EVT_TIMER, self.__ondtimer, None, self.__dtimer.GetId())
        self.Bind(wx.EVT_TIMER, self.__onrtimer, None, self.__rtimer.GetId())
        self.Bind(wx.EVT_TIMER, self.__onctimer, None, self.__ctimer.GetId())
        self.Bind(wx.EVT_SIZE, self.__onsize)
        self.SetTarget(target or self)
        self.AddDragger(self)

    __enabled = False
    def DraggingEnabled(self, v):
        self.__enabled = v
        if v:
            self.__resized()
        elif self.GetDragging():
            self.StopDragging()

    def IsDraggingEnabled(self):
        return self.__enabled

    __resizable = False
    def ResizingEnabled(self, v):
        self.__resizable = v
        if v:
            self.__resized()
        elif self.GetResizing():
            self.StopResizing()

    def IsResizingEnabled(self):
        return self.__resizable

    def __unmaximized_horizontal_offset(self, tw, rx):
        '''
        When a maximized window is dragged, mouse coordinates
        must be rearraged into the new unmaximized size.

        If original coordinate from left or right is beyond unmaximized
        horizontal center, new coordinate is relatived to size. If not,
        original coordinate (from window left or right) is honored.
        '''
        if self.__target.IsMaximized():
            bw, bh = self.__size_before
            w2 = bw/2
            if rx > w2:
                return w2 if rx < tw-w2 else bw-tw+rx
        return rx

    __last_pos = (0, 0)
    __start_drag_pos = (0, 0)
    def StartDragging(self):
        if not self.GetDragging() and self.__enabled:
            evt = DragStartEvent()
            evt.SetEventObject(self)
            self.ProcessEvent(evt)

            tx, ty = self.__target.GetScreenPosition() # Absolute
            tw, th = self.__target.GetSize() # Include borders

            mx, my = wx.GetMousePosition() # Absolute coords
            rx, ry = (mx-tx, my-ty) # Mouse coords relative to position (not to client area)
            rx = self.__unmaximized_horizontal_offset(tw, rx)

            self.__last_pos = (mx, my) # Skip dragging on click with no move
            self.__start_drag_offset = (rx, ry)

            self.__dtimer.Start(100)

    def StopDragging(self):
        if self.GetDragging():
            evt = DragStopEvent()
            evt.SetEventObject(self)
            self.ProcessEvent(evt)
            self.__dtimer.Stop()

    def StartResizing(self):
        if not self.GetResizing() and self.__resizable:
            evt = ResizeStartEvent()
            evt.SetEventObject(self)
            self.ProcessEvent(evt)

            tx, ty = self.__target.GetScreenPosition() # Absolute
            tw, th = self.__target.GetSize() # Include borders

            mx, my = wx.GetMousePosition() # Absolute coords
            rx, ry = (mx-tx, my-ty) # Mouse coords relative to position (not to client area)
            cx, cy = self.__target.ScreenToClientXY(mx, my)

            mw, mh = self.__target.GetMinSize()
            xw, xh = self.__target.GetMaxSize()

            b2 = self.__border*2

            rx = self.__unmaximized_horizontal_offset(tw, rx)

            self.__last_pos = (mx, my) # Skip dragging on click with no move
            self.__start_resize_offset = (rx, ry)
            self.__start_resize_pos = (tx, ty)
            self.__start_resize_size = (tw, th)
            self.__start_resize_zone = self.__resize_zone((cx, cy))
            self.__start_resize_minsize = (max(mw, b2), max(mh, b2))
            self.__start_resize_maxsize = (sys.maxint if xw < 0 else xw, sys.maxint if xh < 0 else xh)

            self.__rtimer.Start(50) # Mouse is outside window during resizing more often than during dragging

            wx.SetCursor(wx.StockCursor(self.__cursor))

    def StopResizing(self):
        if self.GetResizing():
            evt = ResizeStopEvent()
            evt.SetEventObject(self)
            self.ProcessEvent(evt)
            self.__rtimer.Stop()
            self.__resized()
            wx.SetCursor(wx.NullCursor)

    def GetDragging(self):
        return self.__enabled and self.__dtimer.IsRunning()

    def GetResizing(self):
        return self.__resizable and self.__rtimer.IsRunning()

    def __bind(self, wxwindows, bindset):
        for i in wxwindows:
            if not i in bindset:
                i.Bind(wx.EVT_LEFT_DOWN, self.__onmousedown)
                i.Bind(wx.EVT_LEFT_UP, self.__onmouseup)
                i.Bind(wx.EVT_MOTION, self.__onmousemove)
        bindset.update(wxwindows)

    def __unbind(self, wxwindows, bindset):
        for i in wxwindows:
            if i in bindset:
                i.Unbind(wx.EVT_LEFT_DOWN, handler=self.__onmousedown)
                i.Unbind(wx.EVT_LEFT_UP, handler=self.__onmouseup)
                i.Unbind(wx.EVT_MOTION, handler=self.__onmousemove)
        bindset.difference_update(wxwindows)

    def AddDragger(self, *wxwindows):
        self.__bind(wxwindows, self.__dbinded)

    def GetDraggers(self):
        return tuple(self.__dbinded)

    def AddResizer(self, *wxwindows):
        self.__bind(wxwindows, self.__rbinded)

    def GetResizers(self):
        return tuple(self.__rbinded)

    def RemoveDragger(self, *wxwindows):
        self.__unbind(wxwindows, self.__dbinded)

    def RemoveResizer(self, *wxwindows):
        self.__unbind(wxwindows, self.__rbinded)

    __target = None
    def GetTarget(self):
        return self.__target

    def SetTarget(self, target):
        self.__target = target
        if self.__resizable:
            self.__resized()

    def __resized(self):
        if self.__enabled and not self.__target.IsMaximized():
            self.__size_before = self.__target.GetSize()
        if self.__resizable:
            b = self.__border
            w, h = self.__target.GetClientSize()
            self.__inner_area = wx.Rect(b, b, w-b-b, h-b-b)

    def __move(self, pos):
        if pos != self.__last_pos:
            if self.__target.IsMaximized():
                self.__target.Maximize(False)

            tx, ty = self.__start_drag_offset
            self.__target.SetPosition((pos[0]-tx, pos[1]-ty))
            self.__last_pos = pos

    def __resize(self, pos):
        if pos != self.__last_pos:
            if self.__target.IsMaximized():
                self.__target.Maximize(False)

            rx, ry = self.__start_resize_offset
            tx, ty = self.__start_resize_pos
            tw, th = self.__start_resize_size
            zx, zy = self.__start_resize_zone
            mw, mh = self.__start_resize_minsize
            xw, xh = self.__start_resize_maxsize

            mx, my = tx+rx, ty+ry
            px, py = pos

            # x-coord and width
            x = wx.DefaultCoord
            w = -1
            if zx > 0:
                w = max(min(tw + px - mx, xw), mw)
            elif zx < 0:
                w = max(min(tw - px + mx, xw), mw)
                x = tx + tw - w

            # y-coord and height
            y = wx.DefaultCoord
            h = -1
            if zy > 0:
                h = max(min(th + py - my, xh), mh)
            elif zy < 0:
                h = max(min(th - py + my, xh), mh)
                y = ty + th - h

            self.__target.SetDimensions(x, y, w, h, wx.SIZE_USE_EXISTING)
            self.__last_pos = pos

    def __resize_zone(self, pos):
        if self.__inner_area.Contains(pos):
            return 0, 0
        rx, ry = pos
        x = y = 0
        if rx < self.__inner_area.GetLeft():
            x = -1
        elif rx > self.__inner_area.GetRight():
            x = 1
        if ry < self.__inner_area.GetTop():
            y = -1
        elif ry > self.__inner_area.GetBottom():
            y = 1
        return x, y

    __cursor = None
    def __change_cursor(self, c=None):
        if c != self.__cursor:
            self.__cursor = c
            if c is None:
                self.SetCursor(wx.NullCursor)
            else:
                self.SetCursor( wx.StockCursor(c))
                self.__ctimer.Start(250)

    def __onmousedown(self, evt):
        t = evt.GetEventObject()
        handled = False

        if not handled and t in self.__rbinded:
            pos = self.__target.ScreenToClient(wx.GetMousePosition())
            if not self.__inner_area.Contains(pos):
                self.StartResizing()
                handled = True

        if not handled and t in self.__dbinded:
            self.StartDragging()
            handled = True

        if not handled:
            evt.Skip()

    def __onmouseup(self, evt):
        self.StopResizing()
        self.StopDragging()
        evt.Skip()

    __resize_cursors = {
        (-1,-1): wx.CURSOR_SIZENWSE,
        (-1, 0): wx.CURSOR_SIZEWE,
        (-1, 1): wx.CURSOR_SIZENESW,
        ( 0,-1): wx.CURSOR_SIZENS,
        ( 0, 0): None,
        ( 0, 1): wx.CURSOR_SIZENS,
        ( 1,-1): wx.CURSOR_SIZENESW,
        ( 1, 0): wx.CURSOR_SIZEWE,
        ( 1, 1): wx.CURSOR_SIZENWSE,
        }
    def __onmousemove(self, evt):
        '''
        Smoother dragging than using timers on small movements
        '''
        if self.__enabled and self.GetDragging():
            self.__move(wx.GetMousePosition())
        elif self.__resizable:
            if self.GetResizing():
                self.__resize(wx.GetMousePosition())
            elif evt.GetEventObject() in self.__rbinded:
                pos = self.__target.ScreenToClient(wx.GetMousePosition()) # Relativize to target
                cursor = self.__resize_cursors[self.__resize_zone(pos)]
                self.__change_cursor(cursor)
        evt.Skip()

    __size_before = (0, 0)
    def __onsize(self, evt):
        if not self.GetResizing():
            self.__resized()
        evt.Skip()

    def __ondtimer(self, evt):
        '''
        Left button down guard for moving
        '''
        if wx.GetMouseState().ButtonIsDown(wx.MOUSE_BTN_LEFT):
            self.__move(wx.GetMousePosition())
        else:
            self.StopDragging()

    def __onrtimer(self, evt):
        '''
        Left button down guard for resizing
        '''
        if wx.GetMouseState().ButtonIsDown(wx.MOUSE_BTN_LEFT):
            self.__resize(wx.GetMousePosition())
        else:
            self.StopResizing()

    __onctimer_pos = None
    def __onctimer(self, evt):
        '''
        Resizing cursor guard
        '''
        pos = wx.GetMousePosition()
        if self.__onctimer_pos != pos:
            self.__onctimer_pos = pos
            if not self.GetResizing() and not wx.FindWindowAtPoint(pos) in self.__rbinded:
                self.__change_cursor()
                self.__ctimer.Stop()


class WxCairoDraw(object): # Requires inheritance from wx.Window too
    def __init__(self):
        self.compositing = my_env.get_compositing()

    def enable_compositing(self, value):
        self.compositing = my_env.get_compositing() and value

    def BindDraw(self):
        self.Bind(wx.EVT_PAINT, self.__paint)
        self.Bind(wx.EVT_SIZE, self.__resize)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self.__erase)

    @utils.attribute
    def __lock(self):
        return threading.Lock()

    def __erase(self, evt):
        pass

    def __paint(self, evt):
        self.__draw(evt)

    def __resize(self, evt):
        with self.__lock:
            self.__uncache()
        self.Refresh()
        evt.Skip()

    def __uncache(self):
        self.__last_surface = None

    __locked = False
    __last_surface = None
    def __draw(self, paint=None, refresh=False):
        if not self._can_draw():
            return

        with self.__lock:
            self.__locked = True
            if refresh or self.__last_surface is None:
                surface = self.GetSurface()
                if surface and surface.get_width() > 0 and surface.get_height() > 0:
                    self.__last_surface = surface

            if self.__last_surface: # GetSurface can return None
                self._draw_surface(self.__last_surface, paint=paint)
            self.__locked = False

    def _can_draw(self):
        return self.IsShownOnScreen() and self.GetHandle()

    def _draw_surface(self, surface, paint=None, rect=None):
        # creates a drawing context. maybe a buffered dc is also needed
        dc2 = None
        if paint:
            dc = wx.BufferedPaintDC(self)
        else:
            dc =  wx.ClientDC(self)
            if not self.compositing:
                if rect:
                    dc.SetClippingRect(rect)
                dc2, dc = dc, wx.BufferedDC(dc)

        # paints the surface
        context = wx.lib.wxcairo.ContextFromDC(dc)
        context.set_operator(cairo.OPERATOR_SOURCE)
        if not self.compositing:
            # If not compositing, we need to draw background
            context.set_source_rgba(*wxColourCairoRGBA(self.GetBackgroundColour()))
            context.paint()
            context.set_operator(cairo.OPERATOR_OVER)
        elif rect:
            # When compositing, cliping is done with cairo
            context.rectangle(*rect)
            context.clip()
        context.set_source_surface(surface)
        context.paint()

        # destroy drawing contexts
        dc.Destroy()
        if dc2:
            dc2.Destroy()

    def DrawSurface(self, surface, rect=None):
        if not self._can_draw():
            return

        if self.__locked:
            logger.critical("DrawSurface called inside GetSurface on %s" % self)
            return
        with self.__lock:
            self._draw_surface(surface, rect=rect)
        self.__uncache()

    def Draw(self):
        self.__draw(refresh=True)

    def GetSurface(self):
        ''' Stub, this method must be overloaded for 'Draw' behavior '''
        return None


class WxProxy(object):
    '''
    Proxy any object given to constructor.

    All attributes and functions of given object are wrapped too, so they
    return proxy objects as well.

    All wrapped object's properties are accesible in their original name
    (that means CamelCase for wx) and by a more pythonic way (underscored_method_names).
    Get Set wx properties are wrapped to python getter, setters too.

    Note: In python, attribute descriptor can only be attached to classes, not
    instances. That means we need to create a new type for each instance
    we need in order to isolate dynamic getter-setter assignments.
    '''
    _python_types = types.__dict__.values()
    _logger = logging.getLogger("%s.WxProxyLogger" % __name__)
    _proxy_blacklist = _proxy_classes = ()
    _class_cache = {} # Cache of wrapped clases by wx type

    _obj_cache = utils.WeakCappedDict(10) # utils.CappedDict(1000)
    def __new__(cls, *args, **kwargs):
        # Let's try to construct a WxProxy object
        if cls == WxProxy:
            obj = cls.unproxize(args[0]) # Assert is not proxized
            objid = id(obj)

            # We cache a small amount of wrapped objects
            if objid in cls._obj_cache:
                return cls._obj_cache[objid]

            if isinstance(obj, cls._proxy_blacklist):
                return obj

            for k, v in cls._proxy_classes:
                if isinstance(obj, k):
                    # We create a new custom WxProxy class for every wx type (for getters and setters)
                    if not obj.__class__ in cls._class_cache:
                        cls._class_cache[obj.__class__] = type(v.__name__, (v,), {})

                    # Proxy object instantiation
                    r = cls._class_cache[obj.__class__](obj)

                    # Instance work cache
                    cls._obj_cache[objid] = r # obj cache

                    return r

            if callable(obj):
                # If not wxobject but callable
                return WxCallableProxy(obj)
            otype = type(obj)
            # wx modules
            if otype == types.ModuleType and obj.__package__ == "wx":
                return WxModuleProxy(obj)
            # Not a python type
            if not otype in cls._python_types:
                return WxObjectProxy(otype)
            if otype == types.TupleType:
                return tuple(cls(i) for i in obj)
            if otype == types.ListType:
                return [cls(i) for i in obj]
            if otype == types.DictType:
                return dict((cls(k), cls(v)) for k, v in obj.iteritems())
            # Cannot proxy object, return object itself
            return obj
        return object.__new__(cls)

    @classmethod
    def unproxize(cls, o):
        # TODO(felipe): find a way for doing this
        #if hasattr(o, "__call__") and not isinstance(o, wx_classes):
        #    return WxCallbackProxy(o)
        if isinstance(o, cls):
            return o.obj
        return o

    @classmethod
    def _add_getter(cls, name, getter, setter=None):
        '''
        Add a getter-setter proxy to class.
        '''
        if setter:
            desc = WxGetSetterProxy(getter, setter)
        else:
            desc = WxGetterProxy(getter)
        setattr(cls, name, desc)

    # All instance variables must be declared on class due setattr behavior
    obj = None

    def __init__(self, obj):
        self.obj = self.unproxize(obj)

    def __getattr__(self, attr):
        '''
        Attribute pythonization

        wxPython has very ugly and unpythonic methods, getters and
        setter, this method fixes this. - Yeah, my butt
        '''
        if hasattr(self.obj, attr):
            return WxProxy(getattr(self.obj, attr))
        else:
            # Coverts lowercase with underscores like load_panel to
            # camelcase like LoadPanel
            carr = "".join(i.capitalize() for i in attr.split("_"))
            # Replaces Get/Set methods by python getters/setters:
            getter = "Get%s" % carr
            if hasattr(self.obj, getter): # getter
                setter = "Set%s" % carr
                if hasattr(self.obj, setter): # setter
                    self._add_getter(attr, getter, setter)
                    return object.__getattribute__(self, attr)
                self._add_getter(attr, getter)
                return object.__getattribute__(self, attr)
            # Property search after getset search due collisions (i.e GetValue vs Value)
            elif hasattr(self.obj, carr): # capitalized attr
                return WxProxy(object.__getattribute__(self.obj, carr))
        # Is this sick or what?
        raise AttributeError, "Property %s not found in %s" % (attr, self)

    def __setattr__(self, attr, value):
        if not (attr in self.__dict__ or any(attr in t.__dict__ for t in self.__class__.__mro__)):
            # Replaces Get/Set methods by python getters/setters:
            carr = "".join(i.capitalize() for i in attr.split("_"))
            setter = "Set%s" % carr
            if hasattr(self.obj, setter): # setter
                self._add_getter(attr,"Get%s" % carr, setter)
        object.__setattr__(self, attr, value)

    def __eq__(self, x):
        if isinstance(x, WxProxy):
            return x.obj == self.obj
        return x == self.obj

    def __repr__(self):
        r = repr(self.obj)
        p = r.find("; proxy of <Swig Object of type")
        if p > -1:
            return "<%s of %s of %s>" % (self.__class__.__name__, r[1:p], r[p+32:-3])
        elif r.startswith("<") and r.endswith(">"):
            return "<%s of %s>" % (self.__class__.__name__, r[1:-1])
        return "<%s of %s>" % (self.__class__.__name__, r)


class WxGetterProxy(object):
    __slots__ = ("p",)
    def __init__(self, p):
        self.p = p

    def __get__(self, wxproxy, t=None):
        return WxProxy(getattr(wxproxy.obj, self.p)())


class WxGetSetterProxy(WxGetterProxy):
    __slots__ = ("p", "q")
    def __init__(self, p, q):
        WxGetterProxy.__init__(self, p)
        self.q = q

    def __set__(self, wxproxy, v):
        if not isinstance(v, tuple):
            v = (v,)
        v = (WxProxy.unproxize(i) for i in v)
        return WxProxy(getattr(wxproxy.obj, self.q)(*v))


class WxCallableProxy(WxProxy):
    def __call__(self, *args, **kwargs):
        args = map(WxProxy.unproxize, args)
        kwargs = dict((k, WxProxy.unproxize(v)) for k, v in kwargs.iteritems())
        return WxProxy(self.obj(*args, **kwargs))

class WxCallbackProxy(WxCallableProxy):
    @classmethod
    def _proxize(cls, o):
        return WxProxy(o)


class WxObjectProxy(WxProxy):
    def __getitem__(self, k):
        return WxProxy(self.obj[k])

    def __setitem__(self, k, v):
        self.obj[k] = WxProxy.unproxize(v)

    def __len__(self):
        return len(self.obj)


class WxModuleProxy(WxObjectProxy):
    pass


class WxEventHandler(WxProxy):
    def bind(self, evt, handler, *args, **kwargs):
        self.obj.Bind(WxProxy.unproxize(evt), functools.partial(WxEventProxy.wrap, handler), *args, **kwargs)


_style_properties = (
    ("background", "SetBackgroundColour", themeWxColour, None),
    ("foreground", "SetForegroundColour", themeWxColour, None),
    ("show", "Show", bool, None),
    )

def apply_style(obj, code):
    # Get style class from name
    parts = code.split(".")
    obj_theme = theme
    for i in parts:
        obj_theme = getattr(obj_theme, i)

    # Apply known properties
    for key, setter, parser, default in _style_properties:
        if hasattr(obj_theme, key) and getattr(obj_theme, key) != default:
            getattr(obj, setter)(parser(getattr(obj_theme, key)))

    # Compositing background
    if getattr(obj, "compositing", False):
        obj.SetBackgroundColour(wx.Colour(0,0,0,0))

class WxWindowProxy(WxEventHandler):
    def __getitem__(self, k):
        '''
        Recursive name search.
        '''
        if isinstance(k, (int, long)):
            return self.obj.FindWindowById(k)
        elif isinstance(k, basestring):
            if hasattr(self.obj, "FindWindowByName"):
                r = self.obj.FindWindowByName(k)
                if r:
                    return WxProxy(r)
            if hasattr(self, "children"):
                children = self.children
                for i in children:
                    if hasattr(i, "GetName") and i.GetName() == k:
                        return WxProxy(i)
                for i in children:
                    if isinstance(i, WxProxy):
                        c = i[k]
                        if not c is None:
                            return c
        return None


    @property
    def label(self):
        return self.obj.GetLabel()

    @label.setter
    def label(self, v):
        if u"&" in v:
            v = v.replace(u"&", u"&&")
        return self.obj.SetLabel(v)

    def change_label(self, text):
        window = self.obj
        if window.GetLabel() != text:
            window.SetLabel(text)
            return True
        return False

    def position_from(self, parent_window):
        return parent_window.ScreenToClient(self.obj.GetScreenPosition())

    def apply_icons(self, iconlist):
        for k, icon in iconlist:
            element = self[k] if k else self
            if element:
                if hasattr(icon, "__iter__"): # iterable
                    if hasattr(element, "set_icons"):
                        iconbundle = wx.IconBundle()
                        for ricon in icon:
                            iconbundle.AddIcon(wx.IconFromBitmap(ricon))
                        element.icons = iconbundle
                    elif my_env.is_windows and hasattr(element, "set_bitmaps") and len(icon) > 1:
                        element.set_bitmaps(icon[0], icon[1])
                elif hasattr(element, "set_icon"):
                    element.icon = wx.IconFromBitmap(icon)
                elif hasattr(element, "set_bitmap"):
                    element.bitmap = icon

    def remove_children(self, children_list):
        sizer = self.sizer
        for child in children_list:
            if isinstance(child, (WxWindowProxy, wx.Window)):
                sizer.remove(child)
                self.remove_child(child)
                child.Destroy() # child could be a nonproxy window
        self.update()
        self.refresh()
        self.layout()

    @property
    def children(self):
        r = list(self.obj.GetChildren())
        return WxProxy(r)

    def get_all_children(self):
        return sum((i.get_all_children() for i in self.children), [self])


class WxFrameProxy(WxWindowProxy):
    @property
    def children(self):
        r = list(self.obj.GetChildren())
        toolbar = self.obj.GetToolBar()
        if toolbar:
            r.insert(0, toolbar)
        menubar = self.obj.GetMenuBar()
        if menubar:
            r.insert(0, menubar)
        return WxProxy(r)


class WxSizerProxy(WxObjectProxy):
    @property
    def children(self):
        return [i.inner for i in self]

    def __iter__(self):
        return (WxProxy(self.obj.GetItem(i)) for i in xrange(self.obj.GetItemCount()))


class WxSizerItemProxy(WxObjectProxy):
    @property
    def inner(self):
        return WxProxy(self.obj.GetSizer() or self.obj.GetSpacer() or self.obj.GetWindow())


class WxScrolledWindowProxy(WxWindowProxy):
    @property
    def scrollpx(self):
        pux, puy = self.obj.GetScrollPixelsPerUnit()
        vsx, vsy = self.obj.GetViewStart()
        return WxProxy(wx.Point(pux*vsx, puy*vsy))

    @scrollpx.setter
    def scrollpx(self, (x, y)):
        pux, puy = self.obj.GetScrollPixelsPerUnit()
        self.obj.Scroll(float(x)/pux if x > -1 and pux > 0 else -1, float(y)/puy if y > -1 and puy > 0 else -1)

    def get_virtual_point(self, (px, py)):
        x, y = self.scrollpx
        return WxProxy(wx.Point(px+x if px > -1 else -1, py+y if py > -1 else -1))

    def get_virtual_rect(self, rect):
        rect = wx.Rect(*rect)
        rect.x, rect.y = self.get_virtual_point((rect.x, rect.y))
        return WxProxy(rect)

    def get_screen_to_virtual_client(self, p):
        return self.get_virtual_point(self.obj.ScreenToClient(WxProxy.unproxize(p)))

    def get_display_point(self, (px, py)):
        x, y = self.scrollpx
        return WxProxy(wx.Point(px-x if px > -1 else -1, py-y if py > -1 else -1))

    def get_display_rect(self, rect):
        rect = wx.Rect(*rect)
        rect.x, rect.y = self.get_display_point((rect.x, rect.y))
        return WxProxy(rect)


class WxMenuProxy(WxWindowProxy):
    _forcename = {}

    def __init__(self, obj):
        WxWindowProxy.__init__(self, obj)
        # Menus has no name
        if hasattr(obj, "GetId"):
            oid = obj.GetId()
            if oid in self._forcename:
                self._forced_name = self._forcename[oid]
                self.GetName = self._getname
                self.SetName = self._setname

    _forced_name = None
    def _getname(self):
        return self._forced_name

    def _setname(self, v):
        self._forced_name = v
        self._forcename[self.obj.GetId()] = v

    def apply_names(self, hierarchy):
        '''
        Due Wx limitations, menu objects has no names, making really hard
        event binding.
        We make use of proxies to assign names.
        '''
        lines = [(len(line) - len(line.lstrip()), line) for line in hierarchy.strip().splitlines()]
        pindentation, name = lines.pop(0)

        if lines:
            cindentation = min(lines)[0]
            assert cindentation > pindentation < min(lines)[0], ValueError("Malformed hierarchy.")
            children = self.children
            children.reverse()
            parent_pos = -1
            for n, (identation, line) in enumerate(lines):
                if identation == cindentation:
                    if parent_pos > -1:
                        children.pop().apply_names(os.linesep.join(i[1] for i in lines[parent_pos:n]))
                    parent_pos = n
            if parent_pos > -1:
                children.pop().apply_names(os.linesep.join(i[1] for i in lines[parent_pos:]))

        name = name.strip()
        if hasattr(self.obj, "SetName"):
            self.obj.SetName(name)
        else:
            if hasattr(self.obj, "GetId"):
                oid = self.obj.GetId()
                if oid != wx.ID_ANY:
                    self._forcename[self.obj.GetId()] = name
            self._forced_name = name
            self.GetName = self._getname

    _cached_children_cache = {}
    @classmethod
    def _cached_children(cls, obj, method):
        '''
        Another workaround for another stupid wxWidgets memory leak:
        Everytime GetMenuItems is called, a lot of MenuItemObjects are
        created and never garbage collected.
        '''
        objid = "wxid:%d" % obj.GetId() if hasattr(obj, "GetId") else "pyid:%d" % id(obj)
        if not objid in cls._cached_children_cache:
            cls._cached_children_cache[objid] = {}
        cache = cls._cached_children_cache[objid]
        for subobj in getattr(obj, method)():
            subobjid = subobj.GetId() if hasattr(subobj, "GetId") else id(subobj)
            if subobjid in cache:
                subobj.Destroy()
            else:
                cache[subobjid] = subobj
            yield cache[subobjid]

    @property
    def children(self):
        #return [WxProxy(i) for i in self.obj.GetMenuItems()]
        return [WxProxy(i) for i in self._cached_children(self.obj, "GetMenuItems")]


class WxMenuBarProxy(WxMenuProxy):
    @property
    def children(self):
        return [WxProxy(i[0]) for i in self.obj.GetMenus()] # GetMenus returns pairs

    def bind(self, *args, **kwargs):
        if len(args) > 2:
            menu = WxProxy.unproxize(args[2]).GetMenu()
            WxProxy(menu).bind(*args, **kwargs)
        self.Bind(*args, **kwargs)


class WxMenuItemProxy(WxMenuProxy):
    _custom_bitmaps = {}
    @property
    def custom_bitmap(self):
        return self.__class__._custom_bitmaps.get(self.obj.GetId(), None)

    @custom_bitmap.setter
    def custom_bitmap(self, v):
        self.__class__._custom_bitmaps[self.obj.GetId()] = v

    @property
    def enabled(self):
        return self.obj.IsEnabled()

    @enabled.setter
    def enabled(self, v):
        self.obj.Enable(v)

    @property
    def children(self):
        r = self.obj.GetSubMenu()
        if r:
            return [WxProxy(r)]
        return []


class WxToolBarProxy(WxMenuProxy):
    _right_aligned = {}
    _timers = {}

    @classmethod
    def release(cls, obj):
        if obj in cls._right_aligned:
            self = WxProxy(obj)
            self.Unbind(wx.EVT_TIMER, id=self.timer.GetId(), handler=self._handle_timer)
            self.Unbind(wx.EVT_SIZE, handler=self._handle_size)
            self.GetTopLevelParent().Unbind(wx.EVT_SIZE, handler=self._handle_parent_size)
            if self.timer.IsRunning():
                self.timer.Stop()

    @property
    def timer(self):
        return self._timers.get(self.obj)

    def __init__(self, obj):

        WxMenuProxy.__init__(self, obj)

        if not WxProxy.unproxize(obj) in self._right_aligned:
            # Prevent for initializing twice
            self._right_aligned[obj] = []
            self._timers[self.obj] = wx.Timer(self.obj, wx.ID_ANY)

            self.obj.Bind(wx.EVT_SIZE, self._handle_size)

            # There is another BUG: wxWidgets' wxToolBar only triggers
            # EVT_SIZE once.
            # Workaround: look at frame resizes and start a millisecond
            #             one-shot timer for resizing.
            self.GetTopLevelParent().Bind(wx.EVT_SIZE, self._handle_parent_size)
            self.Bind(wx.EVT_TIMER, self._handle_timer, None, self.timer.GetId())


    def set_right_align(self, client):
        self.adjust()
        unproxized_client = WxProxy.unproxize(client)
        if not unproxized_client in self._right_aligned:
            self._right_aligned[self.obj].append(unproxized_client)

    def unset_right_align(self, client):
        self._right_aligned[self.obj].remove(WxProxy.unproxize(client))

    def _handle_size(self, event):
        w = self.obj.GetClientSize().GetWidth()
        self.adjust(w)
        event.Skip()

    _last_w = 0
    def _handle_parent_size(self, event):
        w = self.obj.GetClientSize().GetWidth()
        if w != self._last_w:
            # Current size changed, we do not need delay update
            self._last_w = w
            self.adjust(w)
        else:
            # Current size is not updated yet, tray again later
            self.timer.Start(1, True) # OneShot
        event.Skip()

    def _handle_timer(self, event):
        w = self.obj.GetClientSize().GetWidth()
        if w != self._last_w:
            self._last_w = w
            self.adjust(w)
        event.Skip()

    right_align_margin = 0
    def adjust(self, w=None):
        # Right aligned controls
        if self._right_aligned[self.obj]:
            if w is None:
                w = self.obj.GetClientSize().GetWidth()
            posx = w - self.right_align_margin
            for child in reversed(self._right_aligned[self.obj]):
                posx -= child.GetClientSizeTuple()[0] + self.right_align_margin
                posy = child.GetPosition().y
                child.SetPosition((posx, posy))

    @property
    def children(self):
        return [WxProxy(self.obj.GetToolByPos(i)) for i in xrange(self.obj.GetToolsCount())]


class WxToolBarToolProxy(WxMenuProxy):
    pass


class WxEventProxy(WxObjectProxy):
    _cancelled = False
    def cancel(self):
        self._cancelled = True

    @classmethod
    def wrap(self, callback, event):
        wevent = WxEventProxy(event)
        callback(wevent)
        if not wevent._cancelled and \
           not (hasattr(event, "GetVeto") and event.GetVeto()) and \
           not (hasattr(event, "IsAllowed") and not event.IsAllowed()):
            # Skip event if cancelled and is not vetoed
            event.Skip()

class WxAppProxy(WxEventHandler):
    _singleton = None
    class WxApp(wx.App):
        def __init__(self, owner):
            owner.obj = self
            self.owner = owner
            if my_env.is_linux:
                wx.App() # Hack so that it doesn't crash on the next call
            wx.App.__init__(self, False, useBestVisual=True)

        def OnInit(self):
            self.owner.main()
            return True

        def OnExit(self):
            self.owner.exit()
            return True

    _timers = None
    def add_timer(self, callback, interval, autostart=False):
        timer = wx.Timer(self.obj, wx.ID_ANY)
        timer.Start(interval)
        timer.Stop()
        self.Bind(wx.EVT_TIMER, callback, None, timer.GetId())
        self._timers.append(timer)
        if autostart:
            timer.Start(interval)
        return timer

    def get_all_timers(self):
        return tuple(i for i in self._timers)

    def stop_all_timers(self):
        for i in self._timers:
            i.Stop()

    def __init__(self):
        WxAppProxy._singleton = self
        self._timers = []
        self.WxApp(self)
        WxEventHandler.__init__(self, self.obj)

    def __getitem__(self, k):
        if hasattr(self, k):
            r = getattr(self, k)
            if isinstance(r, (WxProxy, wx.Object)):
                return r
        raise KeyError("Child %s not found" % repr(k))

    @classmethod
    def get(cls):
        if WxAppProxy._singleton is None:
            raise RuntimeError, "App not initialized"
        return WxAppProxy._singleton

    def main(self):
        pass

    def exit(self):
        pass


class WxPartGauge(wx.Panel):
    def __init__(self, parent, parts=()):
        wx.Panel.__init__(self, parent, wx.ID_ANY)
        self._parts = parts
        self.SetMinSize((50, 16))
        self.Bind(wx.EVT_PAINT, self._redraw)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self._redraw) # For offscreen-inscreen moves
        self.Bind(wx.EVT_SIZE, self._redraw)

    _parts = None
    @property
    def parts(self):
        return self._parts

    @parts.setter
    def parts(self, v):
        if v != self._parts:
            self._parts[:] = v
            self.refresh()

    @classmethod
    def sum_colors(self, *args):
        r, g ,b = (sum(i)/len(args) for i in itertools.izip(*args))
        return wx.Colour(r, g, b)

    def refresh(self):
        if self._image:
            self._image.Destroy()
        if self._bitmap:
            self._bitmap.Destroy()
        self._image = self._bitmap = None
        self._paint()

    _image = None
    _bitmap = None
    def _partbar(self, w, h, active_color, inactive_color):
        if self._image is None:
            partlen = len(self.parts)

            bmp = wx.EmptyBitmap(partlen, 1)
            dc = wx.MemoryDC(bmp)

            if self.parts.count(True) > partlen/2:
                # More downloaded parts, we draw active colour as background
                dc.SetPen(wx.Pen(active_color, 1))
                dc.DrawLine(0, 0, partlen, 0)
                dc.SetPen(wx.Pen(inactive_color, 1))
                drawvalue = False
            else:
                # More remaining parts, we draw inactive colour as background
                dc.SetPen(wx.Pen(inactive_color, 1))
                dc.DrawLine(0, 0, partlen, 0)
                dc.SetPen(wx.Pen(active_color, 1))
                drawvalue = True

            lastx = 0
            lasti = None
            for x, i in enumerate(self.parts):
                if i != lasti: # If value changed
                    if lasti == drawvalue:
                        dc.DrawLine(lastx, 0, x, 0)
                    lasti = i
                    lastx = x
            if lasti == drawvalue:
                dc.DrawLine(lastx, 0, partlen, 0)
            dc.Destroy()

            self._image = bmp.ConvertToImage()
        self._bitmap = wx.BitmapFromImage(self._image.Scale(w, h, wx.IMAGE_QUALITY_HIGH))
        return self._bitmap

    def _redraw(self, event):
        if isinstance(event, wx.PaintEvent):
            self._paint(event, None)
        elif isinstance(event, wx.EraseEvent):
            self._paint(None, event)
        event.Skip()

    def _paint(self, paintevent=False, eraseevent=False):
        w, h = self.GetClientSizeTuple()
        if eraseevent:
            dc = eraseevent.GetDC()
            if not dc:
                dc = wx.BufferedDC(wx.ClientDC(self))
        elif paintevent:
            dc = wx.BufferedPaintDC(self)
        else:
            dc = wx.BufferedDC(wx.ClientDC(self))
        dc.Clear()
        if self._bitmap and w == self._bitmap.GetWidth() and h == self._bitmap.GetHeight():
            dc.DrawBitmap(self._bitmap, 0, 0, False)
        elif w > 1 and h > 1:
            # System color detection
            active_color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
            # Create inactive_color based on active_color value
            inactive_color = active_color
            if sum(active_color.Get()[:3]) > 384:
                inactive_color = self.sum_colors(inactive_color, wx.Colour(0,0,0))
            else:
                inactive_color = self.sum_colors(inactive_color, wx.Colour(255,255,255))
            if self.parts:
                self._bitmap = self._partbar(w, h, active_color, inactive_color)
                dc.DrawBitmap(self._bitmap, 0, 0, False)
            else:
                dc.SetPen( wx.Pen( inactive_color, 0 ))
                dc.SetBrush( wx.Brush( inactive_color ))
                dc.DrawRectangle(0, 0, w, h)


class WxAppMenu(wx.Menu):
    def __init__(self):
        wx.Menu.__init__(self)

    def attach_menubar(self, menubar, ignore_ids=(), add_to_end=()):
        last_sep = False
        for i in xrange(menubar.GetMenuCount()):
            menu = menubar.GetMenu(i)

            if i > 0 and not last_sep:
                # Ensure menus are separated by one separators
                self.AppendSeparator()
                last_sep = True
            for item in menu.GetMenuItems():
                if item.GetId() in ignore_ids:
                    continue
                if item.IsSeparator() and last_sep: # Skip two separators
                    continue
                self.AppendItem(item)
                last_sep = item.IsSeparator()
        for item in add_to_end:
            if item == "-":
                self.AppendSeparator()
            else:
                self.AppendItem(item)


class WxNiceProgressBar(wx.Window, WxImpersonator, WxCairoDraw):
    def __init__(self, *args, **kwargs):
        editable = kwargs.pop("editable", False)
        stheme = kwargs.pop("theme", theme.downloads.progress)
        wx.Window.__init__(self, *args, **kwargs)
        WxCairoDraw.__init__(self)

        self._timer = wx.Timer(self, wx.ID_ANY)
        self._pulse_interval = 0.05

        self.Bind(wx.EVT_TIMER, self.OnTimer, None, self._timer.GetId())

        self.BindDraw()
        self.SetEditable(editable)
        self.SetTheme(stheme)

    def Destroy(self):
        if self._timer.IsRunning():
            self._timer.Stop()
        wx.Window.Destroy(self)

    _theme = None
    def SetTheme(self, v):
        self._theme = v

    def ShouldInheritColours(self):
        return True

    _value = 0.
    _setted_value = 0
    def SetValue(self, v):
        redraw = False
        if self._timer.IsRunning():
            self._timer.Stop()
            redraw = True
        if v != self._setted_value:
            old_setted_value = self._setted_value
            old_value = self._value
            self._setted_value = v
            self._value = float(v)/self._range
            self.ProcessEvent(ProgressEvent(
                value=v, rvalue=self._value, old_value = old_setted_value,
                old_rvalue = old_value))
            redraw = True
        if redraw:
            self.Draw()

    def GetValue(self):
        return self._setted_value

    _range = 1.
    def SetRange(self, v):
        self._value = self._value*self._range/v
        self._range = v

    def GetRange(self):
        return self._range

    def Pulse(self):
        if not self._timer.IsRunning():
            self._timer.Start(self._pulse_interval*1000)

    def OnTimer(self, event):
        self.Draw()

    _mouse_start_pos = None
    def OnLeftDown(self, evt):
        self._mouse_start_pos = evt.GetPosition()
        wx.CallAfter(self._set_value, evt.GetPosition(), evt.GetTimestamp())

    _last_x = 0
    _last_timestamp = 0
    def _set_value(self, pos, timestamp):
        if timestamp > self._last_timestamp:
            self._last_timestamp = timestamp
            x = pos.x
            if self._last_x != x:
                w, h = self.GetClientSizeTuple()
                self.SetValue(x * self.GetRange() / w)
                self._last_x = x

    def OnMotion(self, evt):
        if self._mouse_start_pos:
            if wx.GetMouseState().ButtonIsDown(wx.MOUSE_BTN_LEFT):
                wx.CallAfter(self._set_value, evt.GetPosition(), evt.GetTimestamp())
            else:
                self._mouse_start_pos = None

    _editable = False
    def SetEditable(self, v):
        if self._editable != v:
            self._editable = v
            if v:
                self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
                self.Bind(wx.EVT_MOTION, self.OnMotion)
            else:
                self.Unbind(wx.EVT_LEFT_DOWN, handler=self.OnLeftDown)
                self.Unbind(wx.EVT_MOTION, handler=self.OnMotion)

    def GetEditable(self):
        return self._editable

    _pulse_step = 10
    _pulse_size = 20
    _pulse_width = 0
    _pulse_pos = 0
    _pulse_direction = 1
    _last_pulse = 0
    def GetSurface(self):
        width, height = self.GetClientSizeTuple()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        context.set_source_rgba(*wxColourCairoRGBA(self.GetBackgroundColour()))
        context.paint()

        if self._theme.wide < 0:
            h = height
            y = 0
        else:
            h = height if self._theme.wide < 0 else self._theme.wide
            y = (height-h)/2.

        cairo_rounded_rectangle(context, 0, y, width, h, self._theme.radius)
        context.set_source_rgba(*themeCairoRGBA(self._theme.background))
        context.fill()

        pulsing = self._timer.IsRunning()
        if pulsing:
            t = time.time()
            if t - self._last_pulse >= self._pulse_interval: # Ensures constant pulsing
                self._last_pulse = t
                if self._pulse_width != width:
                    self._pulse_width = width
                    self._pulse_step = width / 80.
                    self._pulse_size = width / 10.
                self._pulse_pos += self._pulse_step * self._pulse_direction
                if self._pulse_pos < 0:
                    self._pulse_pos = 0
                    self._pulse_direction = 1
                elif self._pulse_pos + self._pulse_size > width:
                    self._pulse_pos = width - self._pulse_size
                    self._pulse_direction = -1
            x = self._pulse_pos
            w = self._pulse_size
        elif self._value:
            x = 0
            w = width*self._value
        else:
            x = 0
            w = 0

        foreground = themeCairoRGBA(self._theme.foreground)
        if w:
            cairo_rounded_rectangle(context, x, y, w, h, self._theme.radius)
            context.set_source_rgba(*foreground)
            context.fill()

        if not pulsing and self.GetEditable():
            hw = height / 3
            cairo_rounded_rectangle(context, x+w-hw/2, 0, hw, height, 2)
            context.set_source_rgba(*foreground)
            context.fill()

        return surface


class WxNiceTabPanel(wx.Panel, WxImpersonator, WxDragger, WxCairoDraw):
    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)
        WxDragger.__init__(self, self.GetTopLevelParent())
        WxCairoDraw.__init__(self)
        self.DraggingEnabled(self.compositing)

        self.SetMinSize((-1, theme.tab_panel.height))

        if self.compositing:
            # wxWidgets bug makes black transparent, stupid but useful
            bg = wx.Colour(0, 0, 0, 0)
        elif theme.tab_panel.background is None:
            bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DSHADOW)
        else:
            bg = themeWxColour(theme.tab_panel.background)

        self.SetBackgroundColour(bg)

        self.enable_compositing(theme.tab_panel.compositing)

        self._timer = wx.Timer(self, wx.ID_ANY)
        self.Bind(wx.EVT_TIMER, self._handle_timer, None, self._timer.GetId())
        self.Bind(wx.EVT_MOTION, self._handle_move)
        self.Bind(wx.EVT_LEFT_DOWN, self._handle_click)

        self.BindDraw()

    _appmenu = None
    _appmenu_is_tab = False
    def SetAppMenu(self, v):
        if v != self._appmenu:
            is_tab = not isinstance(v, (wx.Menu, wx._core.Menu))
            if is_tab:
                # If is tab, should behave like content
                if not hasattr(v, "__iter__"):
                    v = (v, )
                elif not isinstance(v, tuple):
                    v = tuple(v)
                if self.GetActiveTab() != -1:
                    for i in v:
                        i.Show(False)
            self._appmenu = v
            self._appmenu_is_tab = is_tab
            self.Draw()

    _tabs = ()
    def SetTabs(self, v):
        if not isinstance(v, tuple):
            v = tuple(v)
        if v != self._tabs:
            numtabs = len(v)
            self._tabs = v
            self._tab_sizes = [(0, 0)] * numtabs
            self.Draw()

    def GetTabs(self):
        return self._tabs

    _tooltips = ()
    def SetTabToolTips(self, v):
        if not isinstance(v, tuple):
            v = tuple(v)
        if v != self._tooltips:
            self._tooltips = v
            # TODO refresh current showed tooltip

    def GetTabToolTips(self):
        return self._tooltips

    _appmenu_notification = None
    _tab_notifications = ()
    def SetTabNotifications(self, v):
        if not isinstance(v, tuple):
            v = tuple(v)
        if v != self._tab_notifications:
            self._tab_notifications = v
            self.Draw()

    def GetTabNotifications(self):
        return self._tab_notifications

    def SetTabNotification(self, tab, text):
        if tab == -1:
            if text != self._appmenu_notification:
                self._appmenu_notification = text
                self.render_tab(tab)
        elif tab >= len(self._tab_notifications) or text != self._tab_notifications[tab]:
            self._tab_notifications = setextuple(self._tab_notifications, tab, text)
            self.render_tab(tab)

    def GetTabNotification(self, tab):
        if tab == -1:
            return self._appmenu_notification
        elif tab < len(self._tab_notifications):
            return self._tab_notifications[tab]
        return None

    _appmenu_tooltip = None
    def SetAppMenuToolTip(self, v):
        if not isinstance(v, basestring):
            v = None
        if v != self._appmenu_tooltip:
            self._appmenu_tooltip = v

    def GetAppMenuToolTip(self):
        return self._appmenu_tooltip

    _active_tab = None
    def SetActiveTab(self, v):
        if v != self._active_tab:
            old_content = None
            if not self._active_tab is None:
                old_content = self.GetTabContent(self._active_tab)

            old_active = self._active_tab
            self._active_tab = v

            if not old_active is None:
                self.render_tab(old_active)
            if not v is None:
                self.render_tab(v)

            self._show_content(v, old_content)
            self.ProcessEvent(TabChangeEvent(n=v))

    def GetActiveTab(self):
        return self._active_tab

    _hover_tab = None
    def SetHoverTab(self, v):
        if v != self._hover_tab:
            # We use SetToolTipString instead caching tooltip objects
            # due another wxWidgets' bug, raising SegFaults.
            if self.GetToolTipString():
                self.SetToolTip(None)
            if not v is None:
                if v == -1:
                    if self._appmenu_tooltip:
                        self.SetToolTipString(self._appmenu_tooltip)
                elif len(self._tooltips) >= v and self._tooltips[v]:
                    self.SetToolTipString(self._tooltips[v])

            old_hover = self._hover_tab
            self._hover_tab = v

            if not old_hover is None:
                self.render_tab(old_hover)
            if not v is None:
                self.render_tab(v)

    def _show_content(self, tab=None, old_content=None, recursive_old_content=None):
        # Get new content form tab
        if tab is None:
            new_content = ()
        else:
            new_content = self.GetTabContent(tab)
            if new_content is None:
                new_content = ()
            elif not hasattr(new_content, "__iter__"):
                new_content = (new_content, )

        # Old content to hide
        if old_content is None:
            old_content = ()
        elif not hasattr(old_content, "__iter__"):
            old_content = (old_content, )

        # Old content to hide
        if recursive_old_content is None:
            recursive_old_content = ()

        parents = set()

        for tab in recursive_old_content:
            for i in (tab if hasattr(tab, "__iter__") else (tab, )):
                if not i is None:
                    i.Show(False)
                    parents.add(i.GetParent())

        for i in old_content:
            i.Show(False)
            parents.add(i.GetParent())
        for i in new_content:
            i.Show(True)
            parents.add(i.GetParent())
        for i in parents:
            i.Layout()

    _tab_contents = ()
    def SetTabContents(self, v):
        if not isinstance(v, tuple):
            v = tuple(v)
        if v != self._tab_contents:
            old_content = () if self._active_tab is None else self.GetTabContent(self._active_tab) or ()
            self._tab_contents = v
            self._show_content(self._active_tab, None, v+old_content)

    def GetTabContents(self):
        return self._tab_contents

    def SetTabContent(self, i, v):
        current_content = self.GetTabContent(i)
        if current_content != v:
            self._tab_contents = setextuple(self._tab_notifications, i, v)
            if i == self._active_tab and not i is None:
                self._show_content(v, current_content)

    def GetTabContent(self, i):
        if i == -1:
            return self._appmenu
        elif len(self._tab_contents) > i:
            return self._tab_contents[i]
        return None

    def GetContentTab(self, content):
        if self._appmenu_is_tab and self._appmenu and content in self._appmenu:
            return -1
        elif self._tab_contents:
            for n, c in enumerate(self._tab_contents):
                if content == c or hasattr(c, "__iter__") and content in c:
                    return n
        return 0

    _appmenu_shown = False
    def _handle_click(self, event):
        pos = event.GetPosition()
        tabnum = self._tab_at_pos(pos, True)
        if tabnum == -1 and not self._appmenu_is_tab:
            if not self._appmenu_shown:
                # Click must show appmenu
                self._appmenu_shown = True
                rect = self._get_appmenu_button_rect()
                pos = wx.Point(rect.GetLeft(), rect.GetBottom())
                self.PopupMenu(self.appmenu, pos)
            else:
                # TODO(felipe): hide menu
                pass
        elif not tabnum is None:
            # Click must activate tab
            self.SetActiveTab(tabnum)
        event.Skip()

    def _tab_at_pos(self, pos=None, relative=False):
        if not pos:
            pos = wx.GetMousePosition()
        if not relative:
            rect = self.GetScreenRect()
            if not rect.Contains(pos):
                return None
            pos -= rect.GetPosition()
        tab_spacing = theme.tab_panel.spacing
        px, py = pos
        for n, (w, h) in enumerate(self._tab_sizes):
            if px < w:
                # on tab
                if py < self.GetClientSize().GetHeight()-h:
                    return None
                return n
            px -= w + tab_spacing
            if px < 0:
                # between tabs
                return None
        if self._appmenu_is_tab:
            appmenu_rect = self._get_appmenu_tab_rect()
        else:
            appmenu_rect = self._get_appmenu_button_rect()
        if appmenu_rect.Contains(pos):
            return -1
        return None

    def _drawbg(self, context):
        if self.compositing:
            if theme.tab_panel.compositing_shadow:
                size = self.GetClientSize()
                height = size.GetHeight()
                rswidth = int(math.ceil(0.75 * height))

                if theme.tab_panel.compositing_shadow_extend:
                    width = size.GetWidth()
                else:
                    width = sum(i[0] for i in self._tab_sizes) + rswidth

                xo = width-rswidth

                pattern = cairo.LinearGradient(0, 0, 0, height)
                pattern.add_color_stop_rgba(0.25, 0, 0, 0, 0)
                pattern.add_color_stop_rgba(0.5, 0, 0, 0, 0.1)
                pattern.add_color_stop_rgba(0.75, 0, 0, 0, 0.25)
                pattern.add_color_stop_rgba(1, 0, 0, 0, 0.5)
                context.set_source(pattern)
                context.rectangle(0, 0, width-rswidth, height)
                context.fill()

                pattern = cairo.RadialGradient(xo, height, 0, xo, height, height)
                pattern.add_color_stop_rgba(0, 0, 0, 0, 0.5)
                pattern.add_color_stop_rgba(0.25, 0, 0, 0, 0.25)
                pattern.add_color_stop_rgba(0.5, 0, 0, 0, 0.1)
                pattern.add_color_stop_rgba(0.75, 0, 0, 0, 0)
                context.set_source(pattern)
                context.rectangle(xo, 0, rswidth, height)
                context.fill()
        else:
            size = self.GetClientSize()
            height = size.GetHeight()
            width = size.GetWidth()
            if theme.tab_panel.background is None:
                bg = wxSysCairoRGBA(wx.SYS_COLOUR_3DSHADOW)
            else:
                bg = themeCairoRGBA(theme.tab_panel.background)

            if theme.tab_panel.linear_gradient != None:
                grad = themeCairoRGBA(theme.tab_panel.linear_gradient)
                pattern = cairo.LinearGradient(0, 0, 0, height)
                pattern.add_color_stop_rgba(0, *grad)
                pattern.add_color_stop_rgba(1, *bg)
                context.set_source(pattern)
            else:
                context.set_source_rgba(*bg)
            context.rectangle(0, 0, width, height)
            context.fill()

    def _handle_move(self, event):
        tabnum = self._tab_at_pos()
        if tabnum is None:
            self.SetHoverTab(None)
        else:
            self.SetHoverTab(tabnum)
            self._timer.Start(100, True)
        event.Skip()

    def _handle_timer(self, event):
        if not self.GetScreenRect().Contains(wx.GetMousePosition()):
            self.SetHoverTab(None)

    _tab_base_cache = {}
    @classmethod
    def _get_tab_base(cls, mode, width, height, tab_sizes=()):
        if mode == 0:
            style = theme.tab_panel.tab
        elif mode == 1:
            style = theme.tab_panel.tab_hover
        elif mode == 2:
            style = theme.tab_panel.tab_active

        if (mode, width) in cls._tab_base_cache:
            old_height, surface = cls._tab_base_cache[mode, width]
            if old_height == height:
                return surface

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)

        line_width = max(style.border_width, 0)
        rect_x = line_width/2.
        rect_y = line_width/2.
        rect_width  = width - line_width
        rect_height = height - line_width + (mode == 2)

        radius = max(style.border_radius, 0)
        if radius:
            degrees = math.pi / 180
            context.new_sub_path()
            context.arc(rect_x + rect_width - radius, rect_y + radius, radius, -90 * degrees, 0 * degrees) # TOPRIGHT
            context.line_to(rect_x + rect_width, rect_y + rect_height)
            context.line_to(rect_x, rect_y + rect_height)
            context.arc(rect_x + radius, rect_y + radius, radius, 180 * degrees, 270 * degrees) # TOPLEFT
            context.close_path()
        else:
            context.rectangle(rect_x, rect_y, rect_width, rect_height)

        if style.background is None:
            bg = wxSysCairoRGBA(wx.SYS_COLOUR_3DFACE)
        else:
            bg = themeCairoRGBA(style.background)

        background_drawed = False
        if not style.linear_gradient is None:
            pattern = cairo.LinearGradient(0, 0, 0, rect_y+rect_height)
            pattern.add_color_stop_rgba(0, *bg)
            pattern.add_color_stop_rgba(1, *themeCairoRGBA(style.linear_gradient))
            context.set_source(pattern)
            context.fill_preserve()
            background_drawed = True

        if not style.radial_gradient is None:
            r, g, b, a = themeCairoRGBA(style.radial_gradient)
            half_width = width/2.
            if tab_sizes:
                radius = min(min(i[0] for i in tab_sizes)/2, min(i[1] for i in tab_sizes))
            else:
                radius = min(half_width, rect_height)

            pattern = cairo.RadialGradient(half_width, height, 0, half_width, height, radius)
            pattern.add_color_stop_rgba(0, r, g, b, a)
            if background_drawed:
                # Previous gradient: alpha radial gradient
                pattern.add_color_stop_rgba(1, r, g, b, 0)
            else:
                # No previous gradient: smoother radial gradient
                pattern.add_color_stop_rgba(1, bg[0], bg[1], bg[2], bg[3])
            context.set_source(pattern)
            context.fill_preserve()
            background_drawed = True

        if not background_drawed:
            context.set_source_rgba(*bg)
            context.fill_preserve()

        if line_width:
            if style.border_color is None:
                border_color = wxSysCairoRGBA(wx.SYS_COLOUR_3DDKSHADOW)
            else:
                border_color = themeCairoRGBA(style.border_color)
            context.set_line_width(line_width)
            context.set_source_rgba(*border_color)
            context.stroke()

        cls._tab_base_cache[mode, width] = (height, surface)
        return surface

    def _final_text(self, tab, style):
        if tab < 0:
            return ""
        text = self._tabs[tab]
        all_transformations = {"lower", "upper", "capitalize"}
        if style.transform:
            for i in all_transformations.intersection(style.transform.split(",")):
                text = getattr(text, i)()
        return text

    _tab_text_cache = {}
    def _get_tab_surface(self, tab, icon=None):
        client_width, client_height = self.GetClientSizeTuple()

        mode = self._get_tab_mode(tab)
        style = self._get_tab_style(tab)

        text = self._final_text(tab, style)

        if (tab, mode) in self._tab_text_cache:
            old_client_width, old_client_height, old_text, surface = self._tab_text_cache[tab, mode]
            if old_text == text and (
              style.height > -1 or
              old_client_height == client_height):
                return surface

        height = client_height if style.height == -1 else style.height
        width = style.width
        padding = style.border_width if style.padding == -1 else style.padding

        if tab == -1:
            width = self._get_appmenu_tab_rect().GetWidth()
            text = "[appmenu]" # For cache
        elif style.width == -1:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, client_width, height)
            context = cairo.Context(surface)

            font_desc = get_font_desc(self, context, style.font_size, style.bold)
            rect = get_text_layout(text, context, font_desc, wx.Rect(0, 0, client_width, height), wx.ALIGN_CENTER)[0]
            width = int(math.ceil(rect[2] + padding*2))

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)

        font_desc = get_font_desc(self, context, style.font_size, style.bold)

        if self._appmenu_is_tab:
            tab_sizes = list(self._tab_sizes)
            tab_sizes.append(tuple(self._get_appmenu_tab_rect().GetSize()))
        else:
            tab_sizes = self._tab_sizes
        base = self._get_tab_base(mode, width, height, self._tab_sizes)
        context.set_source_surface(base)
        context.paint()

        if tab == -1:
            appmenu_surface = self._get_appmenu_button()
            x = (width-appmenu_surface.get_width())/2
            y = (height-appmenu_surface.get_height())/2
            context.set_source_surface(appmenu_surface, x, y)
            context.paint()
        elif text and style.font_size:
            if style.foreground is None:
                foreground = wxSysCairoRGBA(wx.SYS_COLOUR_BTNTEXT)
            else:
                foreground = themeCairoRGBA(style.foreground)

            pango_text_path(text, context, font_desc, wx.Rect(0, 0, width, height), wx.ALIGN_CENTER)
            cairo_fill_path(context, fill=foreground, border=themeCairoRGBA(style.stroke), shadow=themeCairoRGBA(style.shadow), border_width=style.stroke_width, shadow_width=style.shadow_width)

        self._tab_text_cache[tab, mode] = (client_width, client_height, text, surface)

        return surface

    def _get_tab_style(self, i):
        if self._active_tab == i:
            return theme.tab_panel.tab_active
        elif self._hover_tab == i:
            return theme.tab_panel.tab_hover
        return theme.tab_panel.tab

    def _get_tab_mode(self, i):
        if self._active_tab == i:
            return 2
        elif self._hover_tab == i:
            return 1
        return 0

    _appmenu_button_cache = {}
    def _get_appmenu_button(self):
        size = self._get_appmenu_button_rect().GetSize()

        mode = 0
        style = None
        if self._appmenu_is_tab:
            style = self._get_tab_style(-1)
            mode = self._get_tab_mode(-1)

        if mode in self._appmenu_button_cache:
            old_size, old_is_tab, surface = self._appmenu_button_cache[mode]
            if old_size == size and old_is_tab == self._appmenu_is_tab:
                return surface

        width = size.GetWidth()
        height = size.GetHeight()

        if style:
            border_width = style.stroke_width
        else:
            border_width = max(theme.tab_panel.appmenu.stroke_width, 0)

        if style:
            border_color = themeCairoRGBA(style.stroke)
        elif theme.tab_panel.appmenu.stroke is None:
            border_color = tuple(wxSysCairoRGBA(wx.SYS_COLOUR_3DDKSHADOW))
        else:
            border_color = themeCairoRGBA(theme.tab_panel.appmenu.stroke)

        if style:
            color = themeCairoRGBA(style.foreground)
        elif theme.tab_panel.appmenu.color is None:
            color = (1, 1, 1)
        else:
            color = themeCairoRGBA(theme.tab_panel.appmenu.color)

        border_inset = border_width /2.

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)

        half_width = width/2.
        half_height = height/2.

        radius = min(half_width, half_height)

        tooth_size = 3.2
        tooth_deviation = 1

        tooth_outer_radius = radius - border_inset
        tooth_inner_radius = radius*9/12 - max(border_inset, 1)

        outer_radius = radius*9/12 + border_inset
        inner_radius = radius*11/24 - border_inset


        rotation = theme.tab_panel.appmenu.rotation * math.pi
        axis_radius = radius*1/6

        context = cairo.Context(surface)
        context.set_line_width(border_width)
        context.set_line_join(cairo.LINE_JOIN_ROUND)

        if border_width:
            context.set_source_rgba(*border_color)
            context.arc(half_width, half_height, outer_radius, 0, 2*math.pi)
            context.stroke()

        context.save()
        context.translate(half_width, half_height)
        context.rotate(rotation*math.pi)
        half_tooth_size = tooth_size/2. + border_inset
        for i in xrange(8):
            context.rotate(i*math.pi/4)
            context.move_to(-half_tooth_size, -tooth_outer_radius)
            context.line_to(half_tooth_size, -tooth_outer_radius)

            context.line_to(half_tooth_size + tooth_deviation, -tooth_inner_radius)
            context.line_to(-half_tooth_size - tooth_deviation, -tooth_inner_radius)

            context.close_path()
            context.set_source_rgba(*color)

            if border_width:
                context.fill_preserve()
                context.set_source_rgba(*border_color)
                context.stroke()
            else:
                context.fill()
        context.restore()

        context.arc(half_width, half_height, outer_radius, 0, 2*math.pi)
        context.set_source_rgba(*color)
        context.fill()

        if border_width:
            context.set_source_rgba(*border_color)
            context.arc(half_width, half_height, inner_radius, 0, 2*math.pi)
            context.stroke()

        context.set_operator(cairo.OPERATOR_CLEAR)
        context.arc(half_width, half_height, inner_radius-border_inset, 0, 2*math.pi)
        context.fill()

        if theme.tab_panel.appmenu.axis:
            context.set_operator(cairo.OPERATOR_OVER)
            context.arc(half_width, half_height, axis_radius, 0, 2*math.pi)
            context.set_source_rgba(*color)
            context.fill_preserve()
            if border_width:
                context.set_source_rgba(*border_color)
                context.stroke()

        self._appmenu_button_cache[mode] = size, self._appmenu_is_tab, surface
        return surface

    _gmb_rect_size = None
    _appmenu_button_rect = None
    def _get_appmenu_button_rect(self):
        size = self.GetClientSize()
        if size != self._gmb_rect_size:
            self._gmb_rect_size = size
            height = theme.tab_panel.appmenu.height
            if height == -1:
                height = size.GetHeight() -2  -theme.tab_panel.appmenu.border_width * 2

            width = theme.tab_panel.appmenu.width
            if width == -1:
                width = height
            x = size.GetWidth()-width
            y = (size.GetHeight()-height)/2
            x -= y
            self._appmenu_button_rec = wx.Rect(x, y, width, height)
        return self._appmenu_button_rec

    def _get_appmenu_tab_rect(self):
        size = self.GetClientSize()
        button_rect = self._get_appmenu_button_rect()
        margin = size.GetWidth()-button_rect.GetRight()
        x = button_rect.GetX()-margin
        tab_rect = wx.Rect(x, 0, size.GetHeight(), size.GetWidth()-x)
        return tab_rect

    def _render_tab(self, i, context, size=None, xoffset=None):
        # Draw a single tab
        if size is None:
            size = self.GetClientSize()
        if xoffset is None:
            if i == -1:
                xoffset = size.GetWidth() - self._get_appmenu_tab_rect().GetWidth()
            else:
                xoffset = sum(self._tab_sizes[t][0] for t in xrange(0, i)) + theme.tab_panel.spacing*i
        tabsurface = self._get_tab_surface(i)
        tab_width = tabsurface.get_width()
        tab_height = tabsurface.get_height()
        yoffset = size.GetHeight()-tab_height
        context.set_source_surface(tabsurface, xoffset, yoffset)
        context.paint()

        if i > -1:
            self._tab_sizes[i] = (tab_width, tab_height)

        # Notifications
        if len(self._tab_notifications) > i and self.GetTabNotification(i):
            style = theme.tab_panel.notification
            padx = style.padding_x
            pady = style.padding_y

            font_desc = get_font_desc(self, context, style.font_size, style.bold)

            draw_rect = pango_text_path(
                self.GetTabNotification(i),
                context, font_desc,
                wx.Rect(xoffset+padx, yoffset+pady, tab_width-padx*2, tab_height-pady*2),
                wx.ALIGN_RIGHT|wx.ALIGN_TOP
                )
            text_path = context.copy_path()
            context.set_source_rgba(*themeCairoRGBA(style.background))
            context.new_path()
            context.rectangle(
                draw_rect.GetX()-padx,
                yoffset,
                draw_rect.GetWidth()+padx*2,
                draw_rect.GetHeight()+draw_rect.GetY()*2
                )
            context.fill()
            context.append_path(text_path)
            cairo_fill_path(context, fill=themeCairoRGBA(style.foreground), border=themeCairoRGBA(style.stroke), shadow=themeCairoRGBA(style.shadow), border_width=style.stroke_width, shadow_width=style.shadow_width)

        return xoffset, yoffset, tab_width, tab_height

    def render_tab(self, i):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *self.GetClientSizeTuple())
        context = cairo.Context(surface)

        # Draw tab
        xoffset, yoffset, tab_width, tab_height = self._render_tab(i, context)

        # Draw background below
        context.set_operator(cairo.OPERATOR_DEST_OVER)
        self._drawbg(context)
        self.DrawSurface(surface, wx.Rect(xoffset, yoffset, tab_width, tab_height))

    def GetSurface(self):
        size = self.GetClientSize()
        width = size.GetWidth()
        height = size.GetHeight()

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)

        # Draw tabs
        tab_spacing = theme.tab_panel.spacing

        xoffset = 0
        for n in xrange(len(self._tabs)):
            xoffset, yoffset, tab_width, tab_height = self._render_tab(n, context, size, xoffset)
            xoffset += tab_width + tab_spacing

        # Draw appmenu button
        if self._appmenu_is_tab:
            rect = self._get_appmenu_tab_rect()
            self._render_tab(-1, context, size, width-rect.GetWidth())
        else:
            rect = self._get_appmenu_button_rect()
            context.set_source_surface(self._get_appmenu_button(), rect.GetX(), rect.GetY())
            context.paint()

        # Draw background below
        context.set_operator(cairo.OPERATOR_DEST_OVER)
        self._drawbg(context)

        return surface

class WxNiceStaticText(wx.StaticText, WxImpersonator):
    '''
    Workaround for wxwidgets StaticText erase background flicker bug:
    http://wiki.wxwidgets.org/Flicker-Free_Drawing#Controling_.22CONTROL.22_flickering
    '''

    def __init__(self, *args, **kwargs):
        wx.StaticText.__init__(self, *args, **kwargs)

        if my_env.is_windows:
            self.Bind(wx.EVT_ERASE_BACKGROUND, self.OnMSWEraseBackground)

    def OnMSWEraseBackground(self, evt):
        pass


class WxNiceDownloadPanel(wx.Panel, WxImpersonator):
    _alternative = False
    _active = False
    _hover = False

    def __init__(self, *args, **kwargs):
        wx.Panel.__init__(self, *args, **kwargs)

        self.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.Bind(wx.EVT_KILL_FOCUS, self.OnUnfocus)
        self.Bind(EVT_IMPERSONATE, self.OnImpersonate)

        self.SetDoubleBuffered(True)


    def Destroy(self):
        for c in self.Children:
            c.Destroy()
        wx.Panel.Destroy(self)

    _dispatchable = False
    def SetDispatchable(self, v):
        if v != self._dispatchable:
            self._dispatchable = v
            self._pausebutton.Show(not v)
            self._deletebutton.Show(not v)
            self._donebutton.Show(v)
            self.Layout()
            self.Refresh()

    def GetDispatchable(self):
        return self._dispatchable

    _quality_icons = ["gui_ico.signal-%d.png" % i for i in xrange(5)]
    _quality = 0
    def SetQuality(self, v):
        if v != self._quality:
            self._quality = v
            qwin = self.FindWindowByName("QualityIcon")
            last = len(self._quality_icons)-1
            icon_name = self._quality_icons[int(round(v*last))]
            bitmap = wx.ArtProvider.GetBitmap(icon_name)
            if qwin and bitmap:
                qwin.SetBitmap(bitmap)

    def OnFocus(self, evt):
        self._active = True
        self._update_colours()

    def OnUnfocus(self, evt):
        self._active = False
        self._update_colours()

    def OnImpersonate(self, evt):
        for i in tuple(self.GetChildren()):
            name = i.GetName()
            if name and name.startswith("DownloadPanelSep"):
                WxNiceHorizontalSeparator.Impersonate(i)

        WxNiceProgressBar.Impersonate(self.FindWindowByName("progress_bar"))

        self._pausebutton = WxNiceButton.Impersonate(self.FindWindowByName("DownloadPauseButton"))
        self._deletebutton = WxNiceButton.Impersonate(self.FindWindowByName("DownloadDeleteButton"))
        self._donebutton = WxNiceButton.Impersonate(self.FindWindowByName("DownloadDoneButton"), theme=theme.done_button)
        self._donebutton.Show(False)
        self._update_colours()

        # StaticText widgets which tend to flicker
        children = {self}
        while children:
            child = children.pop()
            if isinstance(child, (wx.StaticText, wx._core.StaticText)):
                WxNiceStaticText.Impersonate(child)
            children.update(child.GetChildren())

    def SetAlternative(self, v):
        if v != self._alternative:
            self._alternative = v
            self._update_colours()

    def _update_colours(self):
        style = theme.downloads.panel
        if self._active:
            style = theme.downloads.panel_active
        elif self._hover:
            style = theme.downloads.panel_hover
        elif self._alternative:
            style = theme.downloads.panel_alternative
        background = themeWxColour(style.background)
        foreground = themeWxColour(style.foreground)
        self.SetBackgroundColour(background)
        self.SetForegroundColour(foreground)
        self.PropagateColours()
        self.Refresh()

    def GetSurface(self):
        return


class WxNiceStatusBar(wx.StatusBar, WxImpersonator, WxCairoDraw):
    def __init__(self, *args, **kwargs):
        wx.StatusBar.__init__(self, *args, **kwargs)
        WxCairoDraw.__init__(self)
        self._children = {}

        self.Bind( EVT_IMPERSONATE, self.OnImpersonate )
        self.BindDraw()
        self.enable_compositing(theme.statusbar.compositing)

    def OnImpersonate(self, evt):
        self.SetBackgroundColour(wx.Colour(0, 0, 0) if self.compositing else themeWxColour(theme.statusbar.background))
        self.SetForegroundColour(themeWxColour(theme.statusbar.foreground))
        self.Position = evt.other.Position

    _aligns = None
    def SetAligns(self, aligns):
        assert len(aligns) == self.GetFieldsCount(), "Wrong length"
        self._aligns = aligns

    def SetStatusWidths(self, w):
        wx.StatusBar.SetStatusWidths(self, w)
        for i, child in self._children.iteritems():
            child.SetDimensions(*self.GetFieldRect(i))

    def GetStatusText(self, i):
        if i == -1:
            i = self.GetFieldsCount()-1
        r = wx.StatusBar.GetStatusText(self, i)
        if r == "\0": # Another stupid wxPython bug: a null byte
            return ""
        return r.replace("\t", "")

    def SetStatusText(self, text, i):
        if i == -1:
            i = self.GetFieldsCount()-1
        old = self.GetStatusText(i)
        if old != text:
            wx.StatusBar.SetStatusText(self, text, i)
            self.DrawField(i)

    def SetStatusWindow(self, window, i):
        #assert isinstance(button, WxNiceButton), "Only WxNiceButton objects are allowed"
        if i == -1:
            i = self.GetFieldsCount()-1
        if window:
            self._children[i] = window
        elif i in self._children:
            del self._children[i]

        window.SetBackgroundColour(self.GetBackgroundColour())
        window.SetDimensions(*self.GetFieldRect(i))

        #self.DrawField(i)

    def _initialize_draw(self):
        style = theme.statusbar

        width, height = self.GetClientSizeTuple()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)


        self.font_desc = get_font_desc(self, context, style.font_size, style.bold)

        foreground = wxColourCairoRGBA(self.GetForegroundColour())
        #padding = style.padding
        #TODO(felipe): use padding for something yet to be discovered

        return surface, context, foreground, style

    def GetFieldRect(self, i):
        rect = wx.StatusBar.GetFieldRect(self, i)
        if not self.compositing:
            rect.SetY(0)
            rect.SetHeight(self.GetClientSize().GetHeight())
        return rect

    def DrawField(self, i, preparation=None):
        if preparation is None:
            surface, context, foreground, style = self._initialize_draw()
        else:
            surface, context, foreground, style = preparation

        rect = self.GetFieldRect(i)

        width, height = self.GetClientSizeTuple()

        align = self._aligns[i] if self._aligns else wx.ALIGN_CENTER_HORIZONTAL

        text = self.GetStatusText(i)
        if text:
            rect.SetX(rect.GetX()+style.padding)
            rect.SetWidth(rect.GetWidth()-style.padding*2)
            pango_text_path(text, context, self.font_desc, rect, align)
            cairo_fill_path(context, fill=foreground, border=themeCairoRGBA(style.stroke), shadow=themeCairoRGBA(style.shadow), border_width=style.stroke_width, shadow_width=style.shadow_width)

        if preparation is None:
            self.DrawSurface(surface, rect)

    def GetSurface(self):
        preparation = self._initialize_draw()
        for i in xrange(self.GetFieldsCount()):
            self.DrawField(i, preparation)
        return preparation[0]


class WxNiceSearchbox(wx.Window, WxImpersonator, WxCairoDraw):
    def __init__(self, *args, **kwargs):
        wx.Window.__init__(self, *args, **kwargs)
        WxCairoDraw.__init__(self)
        self.SetSize((-1, 39))
        self.SetCursor(wx.StockCursor(wx.CURSOR_IBEAM))

        self.style = theme.toolbar.searchbox
        self._has_text = False
        self.Bind(EVT_IMPERSONATE, self.OnImpersonate)
        self.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        self.BindDraw()

    def OnImpersonate(self, evt):
        self._entry = self.FindWindowByName("SearchboxEntry")

        self._entry.Bind(wx.EVT_SET_FOCUS, self.OnEntryFocus)
        self._entry.Bind(wx.EVT_KILL_FOCUS, self.OnEntryUnfocus)
        self._entry.Bind(wx.EVT_TEXT, self.OnEntryText) # Another wxWidgets bug: isn't fired
        self._entry.Bind(wx.EVT_TEXT_ENTER, self.OnEntryEnter)

        self._button = self.FindWindowByName("SearchboxButton")
        self._button.SetCursor(wx.StockCursor(wx.CURSOR_DEFAULT))
        self._button.Bind(wx.EVT_BUTTON, self.OnButton)

        self.SetBackgroundColour(themeWxColour(self.style.background))
        self.SetForegroundColour(themeWxColour(self.style.foreground))
        self.PropagateColours()
        self.OnEntryUnfocus()

    def _post(self, evt):
        event = evt(self.GetId())
        event.SetString(self._entry.GetValue())
        event.SetEventObject(self)
        self.ProcessEvent(event)

    def OnEntryText(self, evt):
        self._post(SearchTextEvent)

    def OnEntryEnter(self, evt):
        self._post(SearchEnterEvent)

    def OnButton(self, evt):
        self._post(SearchEnterEvent)

    def GetEntry(self):
        return self._entry

    def GetButton(self):
        return self._button

    def OnEntryFocus(self, evt):
        if not self._has_text:
            self._entry.ChangeValue("")
            self._entry.SetForegroundColour(themeWxColour(self.style.foreground))

    def OnFocus(self, evt=None):
        self._entry.SetFocus()

    def OnEntryUnfocus(self, evt=None):
        self._has_text = bool(self._entry.GetValue())
        if not self._has_text:
            self._entry.ChangeValue(self.style.caption)
            self._entry.SetForegroundColour(themeWxColour(self.style.caption_color))

    def GetSurface(self):
        width, height = self.GetClientSizeTuple()

        radius = 5

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        context = cairo.Context(surface)
        context.set_source_rgb(1,1,1)
        context.paint()
        cairo_rounded_rectangle(context, 0.5, 1.5, width-1, height-2, radius)
        context.set_source_rgba(*themeCairoRGBA(self.style.border_color))
        context.set_line_width(1)
        context.stroke()
        context.rectangle(0, 0, width, math.ceil(radius)-0.5)
        context.clip()
        cairo_rounded_rectangle(context, 0.5, 0.5, width-1, height-1, 5)
        context.set_source_rgba(*themeCairoRGBA(self.style.border_top_color))
        context.set_line_width(1)

        context.stroke()
        return surface


class WxNiceToolbar(wx.Window, WxImpersonator):
    def __init__(self, *args, **kwargs):
        wx.Window.__init__(self, *args, **kwargs)

        self.searchbox = None
        self.Bind(EVT_IMPERSONATE, self.OnImpersonate)

    def OnImpersonate(self, evt):
        searchbox = self.FindWindowByName("ToolbarSearchbox")

        if searchbox:
            self.searchbox = WxNiceSearchbox.Impersonate(searchbox)

        self.SetDoubleBuffered(True)
        self.SetBackgroundColour(themeWxColour(theme.toolbar.background))
        self.SetForegroundColour(themeWxColour(theme.toolbar.foreground))
        self.PropagateColours()
        self.Refresh()

    def AddControl(self, control):
        flags = wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM
        if self.GetChildren():
            flags |= wx.LEFT
        self.GetSizer().Add(control, 0, flags, self._padding)

    def SetRightAlign(self, control):
        if not self.GetRightAlign(control):
            sizer = self.GetSizer()
            for n, child in enumerate(sizer.GetChildren()):
                if child.GetWindow() == control:
                    sizer.InsertStretchSpacer(n, 1)

    def GetRightAlign(self, control):
        ''' Get if control is right_aligned '''
        before_spacer = False
        for child in self.GetSizer().GetChildren():
            if child.IsSpacer():
                before_spacer = True
            elif child.GetWindow() == control:
                return before_spacer
        return False

    def SetRightAlignMargin(self, margin):
        self.SetPadding(margin)

    def ApplyNames(self, names):
        pass


class WxNiceButton(wx.Control, WxImpersonator, WxCairoDraw):
    def __init__(self, *args, **kwargs):

        self.theme = kwargs.pop("theme", theme.button)

        wx.Control.__init__(self, *args, **kwargs)
        WxCairoDraw.__init__(self)
        self.SetWindowStyleFlag(self.GetWindowStyleFlag()|wx.BORDER_NONE)

        self._timer = wx.Timer(self, wx.ID_ANY)

        self.Bind(wx.EVT_TIMER, self.OnTimer, None, self._timer.GetId())
        self.Bind(wx.EVT_MOTION, self.OnMouseMove)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
        self.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
        self.Bind(wx.EVT_COMMAND_LEFT_CLICK, self.OnLeftClick)
        self.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
        self.BindDraw()

    def Destroy(self):
        if self._timer.IsRunning():
            self._timer.Stop()
        wx.Control.Destroy(self)

    _label = ""
    def SetLabel(self, v):
        if v != self._label:
            self._label = v
            self.Draw()

    def GetLabel(self):
        return self._label

    def _send_button_event(self):
        evt = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED, self.GetId())
        evt.SetEventObject(self)
        wx.PostEvent(self, evt)

    def OnLeftClick(self, evt):
        self._send_button_event()

    def OnTimer(self, evt):
        if not self.GetScreenRect().Contains(wx.GetMousePosition()):
            self._timer.Stop()
            self._selected = False
            self._hover = False
            self.Draw()

    def OnMouseMove(self, evt):
        if not self._timer.IsRunning():
            self._hover = True
            self.Draw()
            self._timer.Start(500) # Timer for mouseout

    def OnKeyDown(self, evt):
        if evt.GetKeyCode() == wx.stc.STC_KEY_RETURN:
            self._send_button_event()

    _selected = False
    def OnLeftDown(self, evt):
        self.SetFocus()
        self._selected = True
        self.Draw()

    def OnLeftUp(self, evt):
        if self._selected:
            self._send_button_event()
        self._selected = False
        self.Draw()

    _bitmap = None
    def SetBitmap(self, v):
        if self._bitmap != v:
            self._bitmap = v
            if not self._active:
                self.Draw()

    _active_bitmap = None
    def SetBitmapActive(self, v):
        if self._active_bitmap != v:
            self._active_bitmap = v
            if self._active:
                self.Draw()

    _selected_bitmap = None
    def SetBitmapSelected(self, v):
        if self._selected_bitmap != v:
            self._selected_bitmap = v
            self.Draw()

    def SetBitmapDisabled(self, v):
        pass

    def SetBitmapFocus(self, v):
        pass

    def SetBitmapHover(self, v):
        pass

    def SetBitmapLabel(self, v):
        pass

    _active = False
    def SetActive(self, v):
        if self._active != v:
            self._active = v
            self.Draw()

    def GetActive(self):
        return self._active

    def ToggleActive(self):
        r = self._active
        self._active = not self._active
        self.Draw()
        return r

    _cache = ((0,0), None, None, None, "", None)
    def GetSurfaceWithSize(self, size):
        if not isinstance(size, tuple):
            size = tuple(size)
        old_size, old_bitmap, old_background, old_style, old_label, surface = self._cache
        background = self.GetBackgroundColour()

        style = self.theme.button_normal
        if self._active:
            style = self.theme.button_active_clicked if self._selected else self.theme.button_active
            bitmap = self._active_bitmap or self._bitmap
        elif self._selected:
            style = self.theme.button_clicked
            bitmap = self._bitmap
        else:
            style = self.theme.button_normal
            bitmap = self._bitmap

        if style.selected_bitmap and self._selected_bitmap:
            bitmap = self._selected_bitmap

        label = self.GetLabel()

        if size != old_size or bitmap != old_bitmap or background != old_background or style != old_style or label != old_label:
            width, height = size
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            context = cairo.Context(surface)

            context.set_source_rgba(*wxColourCairoRGBA(background))

            border = style.border_width
            hb = border/2.

            context.set_line_width(border)
            cairo_rounded_rectangle(context, hb, hb, width-border, height-border, style.border_radius)
            pattern = cairo.LinearGradient(0, border, 0, width-border)
            pattern.add_color_stop_rgba(0, *themeCairoRGBA(style.background_color_1))
            pattern.add_color_stop_rgba(1, *themeCairoRGBA(style.background_color_2))
            context.set_source(pattern)
            context.fill_preserve()
            pattern = cairo.LinearGradient(0, border, 0, width-border)
            pattern.add_color_stop_rgba(0, *themeCairoRGBA(style.border_color_1))
            pattern.add_color_stop_rgba(1, *themeCairoRGBA(style.border_color_2))
            context.set_source(pattern)
            context.stroke()

            if label:
                margin = style.text_margin
                x = margin
                if bitmap and bitmap != wx.NullBitmap:
                    x += bitmap.GetWidth() + style.icon_margin
                    margin += style.icon_margin
                font_desc = get_font_desc(self, context, style.font_size, style.bold)
                pango_text_path(label, context, font_desc, wx.Rect(x, 0, width-x-margin, height), wx.ALIGN_CENTER)
                cairo_fill_path(context, fill=themeCairoRGBA(style.foreground), border=themeCairoRGBA(style.stroke), shadow=themeCairoRGBA(style.shadow), border_width=style.stroke_width, shadow_width=style.shadow_width)

            if bitmap and bitmap != wx.NullBitmap: # None cannot compare with wx.NullBitmap
                bitmap_surface = wx.lib.wxcairo.ImageSurfaceFromBitmap(bitmap)
                x = style.icon_margin if label else (width - bitmap_surface.get_width())/2.
                y = (height - bitmap_surface.get_height())/2.

                context.set_source_surface(bitmap_surface, math.ceil(x), math.ceil(y))

                if my_env.is_linux:  # fixes linux bug
                    context.set_operator(cairo.OPERATOR_XOR)
                    context.paint()

                context.paint()

            self._cache = (size, bitmap, background, style, label, surface)
        return surface

    def GetSurface(self):
        return self.GetSurfaceWithSize(self.GetClientSizeTuple())


class WxNiceHorizontalSeparator(wx.Window, WxImpersonator, WxCairoDraw):
    def __init__(self, *args, **kwargs):
        wx.Window.__init__(self, *args, **kwargs)
        WxCairoDraw.__init__(self)
        self.BindDraw()

    def ShouldInheritColours(self):
        return True

    _cache = ((0, 0), None, None)
    def GetSurface(self):
        size = self.GetClientSizeTuple()
        background = self.GetBackgroundColour()
        old_size, old_background, surface = self._cache

        if size != old_size or background != old_background:
            width, height = size
            hwidth = width/2.
            style = theme.downloads.panel.separator
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            context = cairo.Context(surface)
            context.set_source_rgba(*wxColourCairoRGBA(background))
            context.paint()
            context.rectangle(0, 0, hwidth, height)
            context.set_source_rgba(*themeCairoRGBA(style.background_color_1))
            context.fill()
            context.rectangle(hwidth, 0, hwidth, height)
            context.set_source_rgba(*themeCairoRGBA(style.background_color_2))
            context.fill()
            self._cache = (size, background, surface)
        return surface


class WxNiceBrowser(wx.Panel, WxImpersonator):
    _comm = ("sc", "ec")
    _codechars = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVXYZ0123456789")
    _script_output_waiting = type("WaitingType", (), {})

    class JavascriptException(Exception):
        pass

    class RequestError(Exception):
        def __init__(self, url, reason, desc):
            self.reason = reason
            self.url = url
            self.description = desc

        def __repr__(self):
            return "Request error '%s' on '%s'." % (self.reason, self.url)

    def __init__(self, *args, **kwargs):
        self._start_url = kwargs.pop("url", None)
        self._local = kwargs.pop("local", False)

        wx.Panel.__init__(self, *args, **kwargs)

        self._flags = set()
        self._safe_locations = {"about:"}
        self._script_output = {}

        self._browser = html2.WebView.New(self, wx.ID_ANY)
        self._browser.SetWindowStyleFlag(wx.BORDER_NONE)
        self._browser.Bind(html2.EVT_WEBVIEW_NAVIGATING, self.OnNavigating)
        self._browser.Bind(html2.EVT_WEBVIEW_NEWWINDOW, self.OnNewWindow)
        self._browser.Bind(html2.EVT_WEBVIEW_LOADED, self.OnViewLoaded)
        self._browser.Bind(html2.EVT_WEBVIEW_ERROR, self.OnError)

        self._browser.Bind(wx.EVT_SET_FOCUS, self.OnChildFocus)
        for child in self._browser.GetChildren():
            child.Bind(wx.EVT_SET_FOCUS, self.OnChildFocus)

        self.ShowLoadingPage()

        if hasattr(self._browser, "EnableContextMenu"):
            self._browser.EnableContextMenu(False)
            self._flags.add("contextmenu_disabled")
        self.Bind(EVT_IMPERSONATE, self.OnImpersonate)

    _loading_page = None
    def ShowLoadingPage(self, url="about:loading", script=""):
        self._loading_page = url
        self.SetPage('''<!DOCTYPE html>
            <head>
                <title>Loading</title>
                <meta http-equiv="X-UA-Compatible" content="IE=edge">
                <style type="text/css">%(css)s</style>
                <style type="text/css">
                    *{
                        cursor:wait;
                        }
                    body{
                        background:#EAEAEA;
                        font-family:Open Sans;
                        font-size:14px;
                        }
                    .loader{
                        position: absolute;
                        top:45%%;
                        left:50%%;
                        margin-top:-50px;
                        margin-left:-150px;
                        text-align:center;
                        padding-bottom:50px;
                        line-height:50px;
                        width:300px;
                        background-position:center center;
                        background-repeat:no-repeat;
                        background-image:url('%(loading)s');
                        }
                </style>
            </head>
            <body>
                <p class="loader">%(text)s</p>
                <script type="text/javascript">%(script)s</script>
            </body>
            </html>''' % {
                "text": _("Loading..."),
                "loading": theme.browser.loading_css_url,
                "css": self.GetBaseCSS(),
                "script": script,
                }, url)

    def OnChildFocus(self, event):
        self.RunScript("window.focus()")

    def SetFocus(self):
        self._browser.SetFocus()
        self.RunScript("window.focus()")

    def SetFocusFromKbd(self):
        self._browser.SetFocusFromKbd()
        self.RunScript("window.focus()")

    def GetErrorRedirectHandler(self):
        return self._error_redirect_handler

    def AddSafeLocation(self, prefix):
        self._safe_locations.add(prefix)

    def AddSafeLocations(self, prefixes):
        self._safe_locations.update(prefixes)

    def SetSafeLocations(self, prefixes):
        self._safe_locations.clear()
        self.AddSafeLocations(prefixes)

    def GetSafeLocations(self):
        return list(self._safe_locations)

    def IsLoaded(self):
        return not self._browser.IsBusy()

    def OnImpersonate(self, event):
        sizer = self.GetSizer()
        if not sizer:
            sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.SetSizer(sizer)
        sizer.Add(self._browser, 1, wx.EXPAND, 0)
        if self._start_url:
            self.LoadURL(self._start_url)

    def GetBaseCSS(self):
        f = self.GetFont()
        font_face = f.GetFaceName()
        font_family = "serif" if f.GetFamily() == wx.FONTFAMILY_ROMAN else "sans-serif"
        if f.IsUsingSizeInPixels():
            font_size = "%spx" % max(f.GetPixelSize())
        else:
            font_size = "%fpt" % f.GetPointSize()
        base_css = '''
            body{
                cursor:default;
                }
            *{
                cursor:inherit;
                }
            input, select, button, a{
                cursor:pointer;
                }
            textarea, input[type=text], input[type=number]{
                cursor: text;
                }
            textarea[readonly], input[readonly], input[readonly],
            textarea[disabled], input[disabled], input[disabled]{
                cursor: pointer;
                }
            *:not(input, textarea){
                -webkit-user-select: none;
                -moz-user-select: none;
                -ms-user-select: none;
                user-select: none;
                }
            ''' % {
                "font_face": font_face,
                "font_short": font_face.split()[0],
                "font_family": font_family,
                "font_size": font_size
                }
        return base_css

    _error_url = None
    def GetErrorURL(self):
        return self._error_url

    def SetErrorURL(self, url):
        self._error_url = url

    def GetPageSource(self):

        if not my_env.is_windows: # WebKit backends dont return the HTML updated by JavaScript.
            self.RunScript('old_title=document.title;document.title=document.documentElement.innerHTML;')
            html = self._browser.GetCurrentTitle()
            self.RunScript('document.title=old_title;')
            return html

        return self._browser.GetPageSource()

    def RunScript(self, js):
        self._browser.RunScript(js)

    _load_json_mark = "<!--JSON-LOADED-->"
    _load_json = "".join(i.strip() for i in (r'''
        if(!window.JSON){
            var e=/[\\\"\x00-\x1f\x7f-\x9f\u00ad\u0600-\u0604\u070f\u17b4\u17b5\u200c-\u200f\u2028-\u202f\u2060-\u206f\ufeff\ufff0-\uffff]/g,
            t={"\b":"\\b","\t":"\\t","\n":"\\n","\f":"\\f","\r":"\\r",'"':'\\"',"\\":"\\\\"},
            n=function(n){e.lastIndex=0;return e.test(n)?'"'+n.replace(e,function(e){var n=t[e];return typeof n==="string"?n:"\\u"+("0000"+e.charCodeAt(0).toString(16)).slice(-4)})+'"':'"'+n+'"'},
            r=function(e,t){var i,s,o,u,a,f=t[e];if(f&&typeof f==="object"&&typeof f.toJSON==="function")f=f.toJSON(e);switch(typeof f){case"string":return n(f);case"number":return isFinite(f)?String(f):"null";case"boolean":case"null":return String(f);case"object":if(!f)return"null";a=[];if(Object.prototype.toString.apply(f)==="[object Array]"){u=f.length;for(i=0;i<u;i+=1)a[i]=r(i,f)||"null";o=a.length===0?"[]":"["+a.join(",")+"]";return o}for(s in f){if(Object.prototype.hasOwnProperty.call(f,s)){o=r(s,f);if(o)a.push(n(s)+":"+o)}}o=a.length===0?"{}":"{"+a.join(",")+"}";return o}};
            window.JSON={stringify:function(e){return r("",{"":e})}};
            };
        var parent=document.body.parentNode;
        parent.insertBefore(document.createComment("%s"), parent.firstChild);
        ''' % _load_json_mark).splitlines())
    _call_script = "".join(i.strip() for i in (r'''
        %(prefix)s
        try{var r={r:(function(){%(script)s}())};}
        catch(e){var r={e: e.toString()};}
        r.c="%(code)s";
        window.location.href="output:"+window.JSON.stringify(r);
        ''').splitlines())
    def CallScript(self, js):
        '''
        Run javascript on webview and returns its output.

        Script outputs must be jsonificable

        Params:
            js: javascript code to execute.

        Returns:
            Script output.
        '''
        code = "".join(j for i in xrange(4) for j in random.sample(self._codechars, 8))
        prefix = "" if self._load_json_mark in self.GetPageSource()[:1024] else self._load_json
        self._script_output[code] = self._script_output_waiting
        self.RunScript(self._call_script % {"prefix":prefix, "script":js, "code":code})
        while self._script_output[code] == self._script_output_waiting:
            wx.EventLoop.GetActive().Dispatch()
        return self._script_output.pop(code)

    _current_url = None
    def LoadURL(self, url):
        self._current_url = url
        self._browser.LoadURL(url)

    def GetURL(self, url):
        self.LoadURL(url)

    def PostURL(self, url, **kwargs):
        script = '''
            (function(path, params){
                var form = document.createElement("form"), hiddenField;
                form.method = "post";
                form.action = path;
                for(var key in params){
                    if(params.hasOwnProperty(key)){
                        hiddenField = document.createElement("input");
                        hiddenField.type = "hidden";
                        hiddenField.name = key;
                        hiddenField.value = params[key];
                        form.appendChild(hiddenField);
                    }
                }
                document.body.appendChild(form);
                form.submit();
            }("%(path)s", %(params)s));
            ''' % {"path": url, "params": json.dumps(kwargs)}

        current_url = self.GetCurrentURL()
        cparse = urlparse.urlparse(current_url)

        self._current_url = url
        if not cparse.netloc:
            self.ShowLoadingPage(script=script)
        else:
            self.RunScript(script)

    def SetPage(self, html, url):
        self._current_url = url
        self._browser.SetPage(html, url)

    def _is_safe(self, url):
        return not url or any(url.startswith(i) for i in self._safe_locations) # no URL is considered safe

    def OnNewWindow(self, evt):
        my_env.open_url(evt.GetURL())

    def GetCurrentURL(self):
        return self._browser.GetCurrentURL()

    def OnNavigating(self, evt):
        current_url = self.GetCurrentURL()
        event_url = evt.GetURL()
        scheme, data = event_url.split(":", 1)

        if event_url.startswith("output:"):
            data = json.loads(urllib.unquote(event_url[7:]))
            if data.get("c", None) in self._script_output:
                if "e" in data:
                    logger.error("JSERROR(%r): %s" % (current_url, data["e"]))
                self._script_output[data["c"]] = data.get("r", None)
                evt.Veto()
        elif self._is_safe(current_url):
            if scheme == "download":
                sc = "<!--FI:%s" % data
                html = self.GetPageSource()
                cmt_start = html.find(sc)
                if cmt_start > -1:
                    cmt_start += len(sc)
                    data = json.loads(html[cmt_start:html.find("-->", cmt_start)])
                    logger.debug("Download with data: %s" % data)
                    self.ProcessEvent(WebViewDownloadEvent(data=data))
                evt.Veto()
            elif scheme == "action":
                self.ProcessEvent(WebViewActionEvent(data=urllib.unquote(data)))
                evt.Veto()
            elif not scheme in ("http", "https", "ftp", "file", "about"): # do we wan't to use ftp protocol here???
                evt.Veto()
        else:
            if not scheme in ("http", "https"): # don't allow anything but http on "untrusted" pages
                evt.Veto()

    def OnViewLoaded(self, evt):
        current_url =  self.GetCurrentURL()
        if evt.GetURL() == current_url and self._is_safe(current_url):
            css = self.GetBaseCSS().replace("\n", "\\n").replace("\"", "\\\"")
            if config.DEBUG:
                if my_env.is_windows and win32.get_ieversion()[0] < 9:
                    # FIREBUG 1.2 (for legacy IE versions)
                    firebug = "var firebug=document.createElement('script');firebug.setAttribute('src','http://getfirebug.com/releases/lite/1.2/firebug-lite-compressed.js');document.body.appendChild(firebug);(function(){if(window.firebug.version){firebug.init();}else{setTimeout(arguments.callee);}})();"
                else:
                    # FIREBUG 1.4 for IE10 and nice browsers
                    firebug = "(function(F,i,r,e,b,u,g,L,I,T,E){if(F.getElementById(b))return;E=F[i+'NS']&&F.documentElement.namespaceURI;E=E?F[i+'NS'](E,'script'):F[i]('script');E[r]('id',b);E[r]('src',I+g+T);E[r](b,u);(F[e]('head')[0]||F[e]('body')[0]).appendChild(E);E=new Image;E[r]('src',I+L);})(document,'createElement','setAttribute','getElementsByTagName','FirebugLite','4','firebug-lite.js','releases/lite/latest/skin/xp/sprite.png','https://getfirebug.com/','#startOpened');"
                extra = '''
                    var a=document.createElement("a");
                    a.href = "javascript:";
                    a.onclick = function(){
                        %s
                        if(document.stopObserving)
                            document.stopObserving('keypress');
                            return false;
                            };
                    a.appendChild(document.createTextNode("RUN FIREBUG"));
                    a.style.display = "block";
                    a.style.padding = "10px";
                    a.style.position = "fixed";
                    a.style.bottom = "0px";
                    a.style.backgroundColor = "red";
                    a.style.color = "white";
                    document.body.appendChild(a);
                    ''' % firebug
            elif my_env.is_windows:
                extra = '''
                    // IE text select disable
                    document.onselectstart = function(e){
                        var srct=(window.event.srcElement||e.target).tagName.toLowerCase();
                        return (srct=="input"||srct=="textarea");
                        };
                    // IE context menu disable
                    document.oncontextmenu = function(){return false;};
                    '''
            else:
                extra = ""
            self.RunScript('''
                "use strict";
                if(!window._events_catched){
                    window._events_catched = true;
                    // Backspace back disable
                    var types=["text", "number", "password"];
                    document.onkeydown = function(evt){
                        var e=(window.event||evt), d=(e.srcElement||e.target), n;
                        if (e.keyCode===8){
                            n=d.tagName.toLowerCase();
                            if((n=="textarea")||((n=="input")&&(types.indexOf(d.type.toLowerCase())>-1)))
                                return !(d.readOnly||d.disabled);
                            return false;
                            }
                        };
                    // Style overwriting (and webkit and mozilla selection disable)
                    var css = document.createElement("style"), cssText = "%(css)s";
                    css.setAttribute("type", "text/css");
                    if(css.styleSheet) css.styleSheet.cssText = cssText; // IE sucks
                    else css.appendChild(document.createTextNode(cssText));
                    document.getElementsByTagName("head")[0].appendChild(css);
                    %(extra)s
                    }''' % {
                        "css": css,
                        "extra": extra,
                        })
        wx.PostEvent(self, evt)

    def OnError(self, evt):
        logger.error("wxNiceBrowser error: %r %r %r %r %r" % (evt, evt.GetString(), evt.GetEventType(), evt.GetURL(), evt.GetTarget()))

        if evt.GetString() == u"INET_E_RESOURCE_NOT_FOUND": # no network
            error_url = self.GetErrorURL()
            if error_url:
                error_url += "%se=%d&m=%s" % (
                    "&" if "?" in error_url else "?",
                    evt.GetInt(),
                    urllib.quote_plus(evt.GetString())
                    )
                self.LoadURL(error_url)
        else:
            evt.Skip()


class WxNicePlayerDialog(wx.Dialog, WxImpersonator, WxDragger):
    class SlowPlayer(Exception):
        ''' Exception for preventing from flooding mplayer '''
        pass

    @classmethod
    def pidpath(self):
        return my_env.tempdirpath("player")

    @classmethod
    def killpids(self):
        path = self.pidpath()
        if os.path.isdir(path):
            for i in os.listdir(path):
                if i.endswith(".pid"):
                    pidfile = os.path.join(path, i)
                    if my_env.get_running_pidfile(pidfile):
                        my_env.kill_process_pidfile(pidfile)
                    else:
                        os.remove(pidfile)

    @classmethod
    def addpid(self, pid):
        if pid is None:
            return

        path = self.pidpath()

        while True:
            pidfile = os.path.join(path, "%x.pid" % (time.time()*1000))
            if os.path.exists(pidfile):
                continue
            with open(pidfile, "w") as f:
                f.write("%d" % pid)
            return pidfile

    @classmethod
    def rempid(self, remfile):
        if remfile is None:
            return

        if os.path.exists(remfile):
            os.remove(remfile)

    def __init__(self, *args, **kwargs):
        wx.Dialog.__init__(self, *args, **kwargs)
        WxDragger.__init__(self)
        self.DraggingEnabled(True)
        self.ResizingEnabled(True)

        self.compositing = my_env.get_compositing()

        # Forced flags
        flags = 0
        if not my_env.is_windows or self.compositing:
            # wxRESIZE_BORDER looks ugly without composition in windows
            flags |= wx.RESIZE_BORDER
        self.SetWindowStyle(self.GetWindowStyle() | flags)

        self._cursor_timer = wx.Timer(self, wx.ID_ANY)
        self._status_timer = wx.Timer(self, wx.ID_ANY)

        self._lock = threading.Lock()

        self.Bind(wx.EVT_TIMER, self.OnCursorTimer, None, self._cursor_timer.GetId())
        self.Bind(wx.EVT_TIMER, self.OnStatusTimer, None, self._status_timer.GetId())
        self.Bind(wx.EVT_CLOSE, self.OnClose)

        self.Bind(EVT_IMPERSONATE, self.OnImpersonate)

    def OnClose(self, evt):
        self.Exit()

    def OnImpersonate(self, evt):
        background = themeWxColour(theme.player.background)
        foreground = themeWxColour(theme.player.foreground)
        playertop = self.FindWindowByName("PlayerTop")
        playercontrols = self.FindWindowByName("PlayerControls")

        self.SetBackgroundColour(background)
        playertop.SetBackgroundColour(background)
        playercontrols.SetBackgroundColour(background)
        playercontrols.SetDoubleBuffered(True)

        self.SetForegroundColour(foreground)
        playertop.SetForegroundColour(foreground)
        playercontrols.SetForegroundColour(foreground)

        closebtn = self.FindWindowByName("PlayerCloseButton")
        closebtn.SetBackgroundColour(self.GetBackgroundColour())
        closebtn.Bind(wx.EVT_BUTTON, self.OnClose)

        self._pbar = WxNiceProgressBar.Impersonate(self.FindWindowByName("PlayerProgress"), editable=True, theme=theme.player.progress)
        self._pbar.Bind(EVT_PROGRESS, self.OnProgressBar)


        self._vbar = WxNiceProgressBar.Impersonate(self.FindWindowByName("PlayerVolume"), editable=True, theme=theme.player.volume)
        self._vbar.Bind(EVT_PROGRESS, self.OnVolumeBar)

        prevb = WxNiceButton.Impersonate(self.FindWindowByName("PlayerPrev"))
        nextb = WxNiceButton.Impersonate(self.FindWindowByName("PlayerNext"))

        for i in (prevb, nextb):
            i.Show(False)

        self._playertime = self.FindWindowByName("PlayerTime")

        self._playerlength = self.FindWindowByName("PlayerLength")

        self._fullscreen = WxNiceButton.Impersonate(self.FindWindowByName("PlayerFullscreen"))
        self._fullscreen.Bind(wx.EVT_BUTTON, self.OnFullscreen)

        self._pause = WxNiceButton.Impersonate(self.FindWindowByName("PlayerPause"))
        self._pause.Bind(wx.EVT_BUTTON, self.OnPause)

        # Color propagation
        self.PropagateColours()
        self.PropagateColours(playertop)
        self.PropagateColours(playercontrols)

        self._player_title = self.FindWindowByName("PlayerTitle")
        self._player_title.SetWindowStyleFlag(wx.ST_ELLIPSIZE_END)
        self._player_title.Bind(wx.EVT_LEFT_DCLICK, self.OnTitleDClick)

        self.AddDragger(self._player_title)
        self.AddDragger(playertop)

        self.AddResizer(playertop)
        self.AddResizer(playercontrols)

        self._player_title.SetForegroundColour(themeWxColour(theme.player.title.foreground))

        self.Refresh()

    def OnTitleDClick(self, evt):
        if self.IsFullScreen():
            self._toggle_fullscreen()
        else:
            self.Maximize(not self.IsMaximized())

    def OnPlayerDclick(self, evt):
        self._toggle_fullscreen()

    _last_progress = 0
    def OnProgressBar(self, evt):
        with self._lock:
            if evt.value != self._last_progress:
                pos = evt.value
                self._player.time_pos = pos
                self._last_progress = pos
                self.UpdatePlaytime(pos)

    _next_update_playtime_labels = 0
    _already_known_length = 0
    def UpdatePlaytime(self, current_seconds=None):
        # Minimum resolution is 1s
        t = time.time()
        if t < self._next_update_playtime_labels and current_seconds is None:
            return
        self._next_update_playtime_labels = t + 1

        if self._already_known_length:
            total_seconds = self._already_known_length
        else:
            total_seconds = self._player.GetTimeLength()

            if total_seconds is None:
                raise self.SlowPlayer

            self._already_known_length = total_seconds
            self._pbar.SetRange(total_seconds)
            self._playerlength.SetLabel(utils.time_fmt_hms(total_seconds))

        if current_seconds is None:
            current_seconds = self._player.GetTimePos()
            if current_seconds is None:
                raise self.SlowPlayer

        self._playertime.SetLabel(utils.time_fmt_hms(current_seconds))
        self._playertime.GetContainingSizer().Layout()

        if current_seconds != self._last_progress:
            self._last_progress = current_seconds
            self._pbar.SetValue(current_seconds)

    def ResetPlaytimeLabels(self):
        self._playertime.SetLabel("0:00")
        self._playerlength.SetLabel("0:00")
        self._pbar.SetRange(100)
        self._already_known_length = 0

    _already_known_volume = False
    def UpdateVolumeBar(self):
        if not self._already_known_volume:
            volume = self._player.volume
            if volume is None:
                raise self.SlowPlayer
            self._already_known_volume = True
            self._last_volume = volume
            self._vbar.SetValue(volume)

    def ResetVolumeBar(self):
        self._already_known_volume = False

    _last_volume = 0
    def OnVolumeBar(self, evt):
        with self._lock:
            if evt.value != self._last_volume:
                self._player.volume = self._last_volume = evt.value

    def OnStatusTimer(self, evt):
        if self._player:
            try:
                self.UpdatePlaytime()
                self.UpdateVolumeBar()
            except self.SlowPlayer:
                pass
        else:
            self._status_timer.Stop()

    _show_bars_cache = True
    def ShowBars(self, v):
        if v != self._show_bars_cache:
            self._show_bars_cache = v
            self.FindWindowByName("PlayerTop").Show(v)
            self.FindWindowByName("PlayerControls").Show(v)
            self.Layout()

    def _show_cursor(self, v):
        if v:
            self._player.SetCursor(wx.NullCursor)
        else:
            self._player.SetCursor(wx.StockCursor(wx.CURSOR_BLANK))

    _fs_player_rect = None
    def _toggle_fullscreen(self):
        fs = not self.IsFullScreen()
        self.ShowFullScreen(fs)
        self.DraggingEnabled(not fs)
        self.ResizingEnabled(not fs)

        self._fullscreen.SetActive(fs)
        self._show_cursor(not fs)
        if fs:
            sr = self.GetScreenRect()
            sr.Top = self.FindWindowByName("PlayerTop").GetClientSizeTuple()[1]
            sr.Height -= sr.Top + self.FindWindowByName("PlayerControls").GetClientSizeTuple()[1]
            self._fs_player_rect = sr
        else:
            self._fs_player_rect = None
            self.ShowBars(True)

    def OnFullscreen(self, evt):
        self._toggle_fullscreen()

    def PlayerMouseMove(self, evt):
        if self._fs_player_rect: # On fullscreen
            self._show_cursor(True)
            if self._show_bars_cache:
                self.ShowBars(False)
            elif not self._fs_player_rect.Contains(evt.GetPosition()):
                self.ShowBars(True)
            self._cursor_timer.Start(500, True) # Oneshot

    def OnCursorTimer(self, evt):
        if self._player:
            self._show_cursor(False)
        else:
            self._cursor_timer.Stop()

    def OnPause(self, evt):
        self._paused = not self._paused
        self._pause.SetActive(self._paused)
        self._player.Pause()

        if self._paused:
            self._status_timer.Stop()
        elif not self._status_timer.IsRunning():
            self._status_timer.Start(500)

    def OnMediaStart(self, evt):
        if self._pidfile is None:
            self._pidfile = self.addpid(self._player.GetPID())
        if not self._status_timer.IsRunning():
            self._status_timer.Start(500)
        evt.Skip()

    def OnMediaFinish(self, evt):
        self._status_timer.Stop()
        evt.Skip()

    def OnProcessStopped(self, evt):
        self._status_timer.Stop()
        evt.Skip()

    def OnProcessStarted(self, evt):
        self._player.Osd(0)
        evt.Skip()

    def OnClose(self, evt):
        self.Exit()

    _player = None
    _pidfile = None
    def Play(self, title, path):
        mplayer = os.environ.get("MPLAYER_PATH", None)
        if mplayer is None:
            return False
        # Assert mplayer exists
        if not os.path.exists(mplayer):
            return False
        # Assert mplayer is executable
        if not os.access(mplayer, os.X_OK):
            return False
        self._status_timer.Stop()
        self._paused = False
        self._pause.SetActive(False)

        self.ResetPlaytimeLabels()
        self.ResetVolumeBar()

        self.Show()
        try:
            self._player_title.SetLabel(title)
            self.SetTitle(title)
            # player not initialized
            if self._player is None:
                other = self.FindWindowByName("PlayerPanel")
                self._player = mplayerctrl.MplayerCtrl(
                    self, other.GetId(), mplayer, path, None, True,
                    other.GetPosition(), other.GetSize(),
                    other.GetWindowStyleFlag(), other.GetName())
                self._player.Bind(mplayerctrl.EVT_MEDIA_STARTED, self.OnMediaStart)
                self._player.Bind(mplayerctrl.EVT_MEDIA_FINISHED, self.OnMediaFinish)
                self._player.Bind(mplayerctrl.EVT_PROCESS_STOPPED, self.OnProcessStopped)
                self._player.Bind(mplayerctrl.EVT_PROCESS_STARTED, self.OnProcessStarted)
                self._player.Bind(wx.EVT_LEFT_DCLICK, self.OnPlayerDclick)
                self._player.SetBackgroundColour(other.GetBackgroundColour())
                self._player.player_window.Bind(wx.EVT_MOTION, self.PlayerMouseMove)
                self._player.hover_window.Bind(wx.EVT_MOTION, self.PlayerMouseMove)
                self.AddResizer(self._player, self._player.hover_window, self._player.player_window)
                self.GetSizer().Replace(other, self._player)
                other.Destroy()
                self._pidfile = self.addpid(self._player.GetPID())
                return True
            # player already initialized
            if self._player.process_alive:
                while not self._player.Quit():
                    time.sleep(0.1)
            return self._player.Start(path)
        except BaseException as e:
            logger.debug(e)
            #self.Show(False)
        return False

    def Exit(self):
        if self._player:
            wx.CallAfter(self._player.Stop)
            wx.CallAfter(self._player.Quit)
            self.rempid(self._pidfile)
            self._player = None
        self.Show(False)

    @property
    def is_playing(self):
        return self._player and self._player.playing and not self._paused

class ArtProvider(wx.ArtProvider):
    def __init__(self, resource_manager):
        wx.ArtProvider.__init__(self)
        self.manager = resource_manager
        self.providers = {
            "icons": self.manager.bitmap,
            "gui": self.manager.image,
            }
        self.push()

    def CreateBitmap(self, artid, client, size):
        if artid.startswith("wxART_"):
            return wx.NullBitmap
        category, artid = artid.split("_", 1)
        if not category in self.providers:
            return wx.NullBitmap
        return self.providers[category][artid]

    def push(self):
        wx.ArtProvider.Push(self)


class XrcProxy(WxObjectProxy):
    '''
    Extra methods are inherited (and proxied) from wx.xrc.XmlResource.
    '''
    _image_re = re.compile(">([a-z0-9 _.-]+)/([a-z0-9 _.-]+).png</(bitmap|disabled|selected|focus|hover)>")
    _default_family = "swiss"
    _default_face = "Open Sans"
    def __init__(self, xml, skip_bitmaps=False,
                 default_font_family=_default_family,
                 default_font_face=_default_face):
        if skip_bitmaps:
            xml = self._image_re.sub(self.bitmap_replace, xml)

        # Bugfixing XML
        # Remove garbage inserted by wxformbuilder, that does nothing
        # good and breaks the Gtk backend
        xml = xml.replace(
            "<family>default</family>",
            "<family>%s</family><face>%s</face>" % (default_font_family, default_font_face)
            ).replace(
            "<maxlength>0</maxlength>", # wxFormBuilder is kinda stupid
            ""
            )

        # Advanced bugfixing: remove <bitmap>s from the tray element in linux
        if my_env.is_linux:
            import lxml.etree
            tree = lxml.etree.fromstring(xml)
            for b in tree.findall('.//ns:object[@name="TrayMenu"]//ns:bitmap',
                                  namespaces={'ns': 'http://www.wxwidgets.org/wxxrc'}):
                b.find('..').remove(b)
            xml = lxml.etree.tostring(tree)

        res = wx.xrc.EmptyXmlResource()
        res.LoadFromString(xml)
        WxObjectProxy.__init__(self, res)
        self.xml = xml
        self._cache = []
        self._children = set()

    @classmethod
    def bitmap_replace(cls, match):
        return " stock_id=\"%s_%s\"/>" % (match.group(1), match.group(2))

    def copy(self):
        return self.__class__(self.xml)

    def __getitem__(self, k):
        if isinstance(k, basestring):
            # Get from _cache
            for obj in self._cache:
                if obj.GetName() == k:
                    return obj
            # Get frame with id
            r = self.obj.LoadFrame(None, k)
            if r:
                r = WxProxy(r)
                self._cache.append(r)
                return r
        return None

    def __setattr__(self, k, v):
        if isinstance(v, wx.Window):
            self._children.add(v)
        WxObjectProxy.__setattr__(self, k, v)

    @property
    def children(self):
        return list(self._children)

    def get_all_children(self):
        return sum((i.get_all_children() for i in self._children), [])

    def get_id(self, name):
        return wx.xrc.XRCID(name)

# Configuration
WxProxy._proxy_blacklist = (WxProxy, wx.ScrolledWindow)
# Wrappers (only for classes with __init__'s obj param)
WxProxy._proxy_classes = (
    (wx.Frame, WxFrameProxy),
    (wx.ToolBarToolBase, WxToolBarToolProxy),
    (wx.ToolBar, WxToolBarProxy),
    (wx.MenuBar, WxMenuBarProxy),
    (wx.MenuItem, WxMenuItemProxy),
    (wx.Menu, WxMenuProxy),
    #(wx.ScrolledWindow, wx.ScrolledWindow),
    (wx.Window, WxWindowProxy),
    (wx.Sizer, WxSizerProxy),
    (wx.SizerItem, WxSizerItemProxy),
    (wx.Object, WxObjectProxy),
    )

# Custom events
TabChangeEvent, EVT_TAB_CHANGE = wx.lib.newevent.NewEvent()

SearchTextEvent, EVT_SEARCH_TEXT = wx.lib.newevent.NewCommandEvent()
SearchEnterEvent, EVT_SEARCH_ENTER = wx.lib.newevent.NewCommandEvent()

DispatchEvent, EVT_DISPATCH = wx.lib.newevent.NewEvent()
ImpersonateEvent, EVT_IMPERSONATE = wx.lib.newevent.NewEvent()
ProgressEvent, EVT_PROGRESS = wx.lib.newevent.NewEvent()
DragStartEvent, EVT_DRAG_START = wx.lib.newevent.NewEvent()
DragStopEvent, EVT_DRAG_STOP = wx.lib.newevent.NewEvent()
ResizeStartEvent, EVT_RESIZE_START = wx.lib.newevent.NewEvent()
ResizeStopEvent, EVT_RESIZE_STOP = wx.lib.newevent.NewEvent()

WebViewDownloadEvent, EVT_WEBVIEW_DOWNLOAD = wx.lib.newevent.NewEvent()
WebViewActionEvent, EVT_WEBVIEW_ACTION = wx.lib.newevent.NewEvent()

# Wrapping entire wxPython
pwx = wx

# Custom constants
pwx.EVT_TAB_CHANGE = EVT_TAB_CHANGE
pwx.EVT_SEARCH_TEXT = EVT_SEARCH_TEXT
pwx.EVT_SEARCH_ENTER = EVT_SEARCH_ENTER
pwx.EVT_IMPERSONATE = EVT_IMPERSONATE
pwx.EVT_WEBVIEW_DOWNLOAD = EVT_WEBVIEW_DOWNLOAD
pwx.EVT_WEBVIEW_ACTION = EVT_WEBVIEW_ACTION
pwx.EVT_DISPATCH = EVT_DISPATCH

# External EVT constants
external_modules = (html2, mplayerctrl)
for module in external_modules:
    for k, v in module.__dict__.iteritems():
        if k.startswith("EVT_") and not hasattr(pwx, k):
            setattr(pwx, k, v)
