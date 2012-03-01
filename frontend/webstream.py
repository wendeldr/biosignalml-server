######################################################
#
#  BioSignalML Management in Python
#
#  Copyright (c) 2010  David Brooks
#
#  $Id: webstream.py,v a82ffb1e85be 2011/02/03 04:16:28 dave $
#
######################################################

import logging

import web
from ws4py.websocket import WebSocket

import biosignalml.transports.stream as stream

from biosignalml      import BSML
from biosignalml.rdf  import Uri
from biosignalml.data import UniformTimeSeries
import biosignalml.formats as formats


class StreamServer(WebSocket):
#=============================

  protocol = 'biosignalml-ssf'

  def __init__(self, *args, **kwds):
  #---------------------------------
    WebSocket.__init__(self, *args, **kwds)
    self._parser = stream.BlockParser(self.got_block, check=stream.Checksum.CHECK)

  def got_block(self, block):
  #--------------------------
    pass

  def received_message(self, msg):
  #-------------------------------
    self._parser.process(msg.data)
    self.close()

  def send_block(self, block, check=stream.Checksum.STRICT):
  #---------------------------------------------------------
    '''
    Send a :class:`~biosignalml.transports.stream.StreamBlock` over a web socket.

    :param block: The block to send.
    :param check: Set to :attr:`~biosignalml.transports.stream.Checksum.STRICT`
      to append a MD5 checksum to the block.
    '''
    self.send(block.bytes(), True)


class StreamEchoSocket(StreamServer):
#====================================

  def got_block(self, block):
  #--------------------------
    self.send_block(block)


class StreamDataSocket(StreamServer):
#====================================

  MAXPOINTS = 4096 ### ?????

  def _add_signal(self, uri):
  #--------------------------
    if self._repo.is_signal(uri):
      rec = self._repo.get_recording(uri)
      recclass = formats.CLASSES.get(str(rec.format))
      if recclass:
        sig = self._repo.get_signal(uri)
        rec.add_signal(sig)
        recclass.initialise_class(rec, str(rec.source))   ## Assumes signal index is last part of s.uri
        self._sigs.append(sig)

  def got_block(self, block):
  #--------------------------
    logging.debug('GOT: %s', block)
    if block.type == stream.BlockType.DATA_REQ:
      self._repo = web.config.biosignalml['repository']
      uri = block.header.get('uri')
      self._sigs = [ ]
      if isinstance(uri, list):
        for s in uri: self._add_signal(s)
      elif self._repo.is_recording(uri):
        rec = self._repo.get_recording_with_signals(uri)
        recclass = formats.CLASSES.get(str(rec.format))
        if recclass:
          recclass.initialise_class(rec, str(rec.source))   ## Assumes signal index is last part of s.uri
          self._sigs = rec.signals()
      else:
        self._add_signal(uri)
      start = block.header.get('start')
      duration = block.header.get('duration')
      if start is None and duration is None: interval = None
      else:                                  interval = (start, duration)
      offset = block.header.get('offset')
      count = block.header.get('count')
      if offset is None and count is None: segment = None
      else:                                segment = (offset, count)
      for sig in self._sigs:
        try:
          for d in sig.read(interval=sig.recording.interval(*interval) if interval else None,
                            segment=segment,
                            points=block.header.get('maxsize', 0)):
            if isinstance(d.dataseries, UniformTimeSeries):
              timing = { 'rate': d.dataseries.rate }
            else:
              timing = { 'clock': d.dataseries.times }
            self.send_block(stream.SignalData(str(sig.uri), d.starttime, d.dataseries.data, **timing).streamblock())
        except Exception, msg:
          self.send_block(stream.ErrorBlock(0, block, str(msg)))
          if web.config.debug: raise


if __name__ == '__main__':
#=========================

  import sys

  from triplestore import repository

  def print_object(obj):
  #=====================
    attrs = [ '', repr(obj) ]
    for k in sorted(obj.__dict__):
      attrs.append('  %s: %s' % (k, obj.__dict__[k]))
    print '\n'.join(attrs)


  def test(uri):
  #-------------

    repo = repository.BSMLRepository('http://devel.biosignalml.org', 'http://localhost:8083')



  if len(sys.argv) < 2:
    print "Usage: %s uri..." % sys.argv[0]
    sys.exit(1)

  uri = sys.argv[1:]
  if len(uri) == 1: uri = uri[0]


  test(uri)

