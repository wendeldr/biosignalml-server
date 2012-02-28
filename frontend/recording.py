######################################################
#
#  BioSignalML Management in Python
#
#  Copyright (c) 2010-2011  David Brooks
#
#  $ID$
#
######################################################


import logging
import uuid
import web
import os
import urllib
import hashlib
from datetime import datetime

from biosignalml.utils import xmlescape
from biosignalml.model import BSML

import biosignalml.formats as fileformats
import biosignalml.formats.stream.ssf as stream
import biosignalml.formats.stream.samplerate as samplerate

import htmlview
import frontend

"""
/recording/label/...
/recording/uuid/...
/recording/uuid/metadata/...

stream v's native (raw)
"""

# Raising web.errors in web.py sets Content-type to text/html.
# If we are returning <bsml> then we should raise web.HTTPError
# directly, setting Content-type.


MIMETYPE_BSML = 'application/x-bsml+xml'


class HTTPError(web.HTTPError):
#==============================

  def __init__(self, status, message=None):
  #----------------------------------------
    if message is None: message = status.split(" ", 1)[1].lower()
    logging.error(message)
    web.HTTPError.__init__(self, status, {'Content-Type': MIMETYPE_BSML},
                          '<bsml>\n <error>%s</error>\n</bsml>\n' % xmlescape(message))


class NotFound(HTTPError):
#=========================

  def __init__(self, message=None):
  #--------------------------------
    status = '404 Not Found'
    HTTPError.__init__(self, status, message)


class InternalError(HTTPError):
#==============================

  def __init__(self, message=None):
  #--------------------------------
    status = '500 Internal Server Error'
    HTTPError.__init__(self, status, message)


class BadRequest(HTTPError):             # Missing from web.py
#===========================

  def __init__(self, message=None):
  #--------------------------------
    status = '400 Bad Request'
    HTTPError.__init__(self, status, message)


class Conflict(HTTPError):               # Missing from web.py
#=========================

  def __init__(self, message=None):
  #--------------------------------
    status = '409 Conflict'
    HTTPError.__init__(self, status, message)


class UnsupportedMediaType(HTTPError):   # Missing from web.py
#=====================================

  def __init__(self, message=None):
  #--------------------------------
    status = '415 Unsupported Media Type'
    HTTPError.__init__(self, status, message)



class RecConfig(object):
#=======================

  def __init__(self, format, recording, mtype):
  #--------------------------------------------
    self._format = format
    self._recording = recording
    self._mimetypes = [ mtype ]

  def add_type(self, mtype):
  #-------------------------
    self.mimetypes.append(mtype)


"""
RFC 2396                   URI Generic Syntax                August 1998


6. URI Normalization and Equivalence

   In many cases, different URI strings may actually identify the
   identical resource. For example, the host names used in URL are
   actually case insensitive, and the URL <http://www.XEROX.com> is
   equivalent to <http://www.xerox.com>. In general, the rules for
   equivalence and definition of a normal form, if any, are scheme
   dependent. When a scheme uses elements of the common syntax, it will
   also use the common syntax equivalence rules, namely that the scheme
   and hostname are case insensitive and a URL with an explicit ":port",
   where the port is the default for the scheme, is equivalent to one
   where the port is elided.
"""



class ReST(object):
#==================

  _repo = web.config.biosignalml['repository']
  _storepath = web.config.biosignalml['recordings']
  _formats = { }
  _mimetype = { }
  _deftype = None
  for r in _repo.query(
  ## Use repo.base to get configuration...   ##############
    """PREFIX cfg: <http://www.biosignalml.org/ontologies/2011/06/configuration#>

       select ?fmt ?cls ?def
         from <http://biosignalml/configuration>
         where {
           ?fmt cfg:mimetype       ?def .
           ?fmt cfg:recordingClass ?cls .
           }
         order by ?fmt desc(?def)"""):
    if r[2].get('value'):
      try:
        cls = getattr(fileformats, r[1]['value'])
        _formats[r[2]['value']] = (r[0]['value'], cls)
        _mimetype[r[0]['value']] = r[2]['value']
      except AttributeError:
        logging.error("Unknown importer: fileformats.%s", r[1]['value'])


  @staticmethod
  def _pathname(name):
  #------------------
    paths = name.split('/')
    if len(paths) < 2 or not paths[1]:
      raise NotFound("Cannot find '%s'" % name)
    tail = paths[-1].split('#', 1)
    fragment = tail[1] if len(tail) > 1 else ''
    paths[-1] = tail[0]
    return ('/'.join(paths[1:]), tail[0], fragment)


  @staticmethod
  def _get_interval(t):
  #--------------------
    try:
      if '-' in t:
         (start, end) = tuple([ float(x) for x in t.split('-') ])
         length = end - start
      elif ':' in t:
        interval = [ float(x) for x in t.split(':') ]
        (start, length) = (interval[0], interval[1])
      else:
        raise Exception
      if length <= 0.0: raise Exception
      return (start, length)
    except Exception:
      pass
    raise InternalError('Invalid time interval')


  def GET(self, name):
  #-------------------
    accept = { k[0].strip(): k[1].strip() if len(k) > 1 else ''
                for k in [ a.split(';', 1)
                  for a in web.ctx.environ.get('HTTP_ACCEPT', '*/*').split(',') ] }
    #logging.debug('ACCEPT: %s -> %s', web.ctx.environ['HTTP_ACCEPT'], accept)

    source, filename, fragment = self._pathname(name)
    #logging.debug('%s, %s, %s', source, filename, fragment)
    if source.startswith('http:'): rec_uri = source
    else: rec_uri = ReST._repo.base + name.split('/', 1)[0] + '/' + source

    recording = ReST._repo.get_recording(rec_uri)
    if recording is None: raise NotFound("Unknown recording: '%s'" % source)
    logging.debug("Request '%s' --> '%s'", name, recording.source)
    logging.debug('ENV: %s', web.ctx.environ)


    objtype = ReST._repo.get_type(rec_uri)
    ctype = (ReST._mimetype.get(str(recording.format), 'application/x-raw')
               if objtype in [BSML.Recording, BSML.Signal]
             else None)
    logging.debug('OBJ=%s, FMT=%s, CT=%s, AC=%s', objtype, recording.format, ctype, accept)

## Should we set 'Content-Location' header as well?
## (to actual URL of representation returned).

    web.header('Vary', 'Accept')      # Let caches know we've used Accept header
    if ctype in accept: # send file
      # Also we may be GETting a signal, not a recording
      # - check rdf:type. If Signal then find/open bsml:recording

      if recording.source is None:
        raise NotFound("Missing recording source: '%s'" % source)
      logging.debug("Streaming '%s'", recording.source)

      try:
        rfile = urllib.urlopen(str(recording.source)).fp
        web.header('Content-Type', ctype)
        ### web.header('Transfer-Encoding','chunked')
        web.header('Content-Disposition', 'attachment; filename=%s' % filename)
        while True:
          data = rfile.read(32768)
          if not data: break
          yield data
        rfile.close()
      except Exception, msg:
        raise InternalError("Error serving recording: %s" % msg)


    elif ctype not in [None, 'application/x-raw'] and 'application/x-stream' in accept:
      logging.debug('Opening: %s', ctype)

      if recording.source is None:
        raise NotFound("Missing recording source: '%s'" % source)

      RecordingClass = ReST._formats.get(ctype, (None, None))[1]
      try:
        rec = RecordingClass.open(str(recording.source), uri=recording.uri)
      except IOError:
        raise NotFound("Cannot open source: '%s'" % recording.source)

      query = web.ctx.environ['QUERY_STRING']
      if query: times = [ self._get_interval(t) for t in query.split(';') ]
      else:     times = [ (0.0, rec.duration) ]
      logging.debug("Times: %s", times)

##      logging.debug('Session: %s', frontend.session._data) # .get('lastrec', None))
      #session.lastrec = rec  ## Swig objects can't be pickled...
      frontend.session.lastrec = 'test...xxx'
##      logging.debug('Session: %s', frontend.session._data) # .get('lastrec', None))
      frontend.session._save()         ## Shouldn't be needed??
                              ## Or does saving depend on how we return??

      if objtype == BSML.Signal:
        try:
          newrate = None ############### set by query parameter... ###################
          sig = rec.get_signal(rec_uri)
          rs = None if newrate is None else samplerate.RateConvertor(newrate)
          for t in times:
            for d in sig.read(rec.interval(*t)):
              yield stream.DataBlock(d if rs is None else rs.convert(d)).data(stream.CHECKSUM_STRICT)
            if rs is not None:
              logging.debug('finish convert')
              db = stream.DataBlock(rs.finish()).data(stream.CHECKSUM_STRICT)
              logging.debug('DB=%s', db)
              yield db
        except Exception, msg:
          raise InternalError(msg)

    # elif ctype == 'text/html':
    #   yield htmlview.recording_html(rec_uri)

    else:
      ## Build a new RDF Graph that has { <uri> ?p ?o  } UNION { ?s ?p <uri> }
      ## and serialise this??

      # check rdf+xml, turtle, n3, html ??
      format = 'text/turtle' if ('text/turtle' in accept
                              or 'application/x-turtle' in accept) else 'application/rdf+xml'
      web.header('Content-Type', format)
      if recording is not None:
        yield ReST._repo.construct('?s ?p ?o', 'graph <%s> { ?s ?p ?o' % recording.uri
                                             + ' FILTER (?p != <http://4store.org/fulltext#stem>'
                                             + ' && (?s = <%s> || ?o = <%s>)) }' % (rec_uri, rec_uri),
                                    format=format)
      elif format == 'text/turtle':
        yield (ReST._repo.construct('<%s> ?p ?o' % rec_uri,
                                    '<%s> ?p ?o FILTER(?p != <http://4store.org/fulltext#stem>)'
                                     % rec_uri, format=format)
             + ReST._repo.construct('?s ?p <%s>' % rec_uri,
                                    '?s ?p <%s> FILTER(?p != <http://4store.org/fulltext#stem>)'
                                     % rec_uri, format=format) )
      else:
        yield ReST._repo.construct('<%s> ?p ?o' % rec_uri,
         '<%s> ?p ?o FILTER(?p != <http://4store.org/fulltext#stem>)'
           % rec_uri, format=format)


  def PUT(self, name):
  #-------------------
    logging.debug("NM: %s", name)  ##
    ctype = web.ctx.environ.get('CONTENT_TYPE', 'application/x-raw')
    if not ctype.startswith('application/x-'):
      raise UnsupportedMediaType("Invalid Content-Type: '%s'" % ctype)

    # Can we also PUT RDF content ???

    RecordingClass = ReST._formats.get(ctype, (None, None))[1]
    if not RecordingClass:
      raise UnsupportedMediaType("Unknown Content-Type: '%s'" % ctype)

    source = self._pathname(name)[0]
    if source.startswith('http:'): rec_uri = source
    else: rec_uri = ReST._repo.base + name.split('/', 1)[0] + '/' + source


    ##file_id   = str(uuid.uuid4()) + '.' + format
    ##file_name = os.path.abspath(os.path.join(ReST._repo.storepath, file_id))

    file_name = os.path.abspath(os.path.join(ReST._storepath, source))
    if getattr(RecordingClass, 'normalise_name', None):
      file_name = RecordingClass.normalise_name(file_name)

    #if container: file_uri = os.path.split(file_uri)[0]

    if ReST._repo.check_type(rec_uri, BSML.Recording):
      raise Conflict("Recording '%s' is already in repository" % rec_uri)

    try:            os.makedirs(os.path.dirname(file_name))
    except OSError: pass
    try:
      output = open(file_name, 'wb')
      rfile = web.ctx.env['wsgi.input']
      sha = hashlib.sha512()
      while True:
        data = rfile.read(32768)       ##
        if not data: break             ## Can we detect broken stream and raise error ???
        sha.update(data)
        output.write(data)
      output.close()

      recording = RecordingClass.open(file_name, uri=rec_uri) ####, metadata={'digest': sha.hexdigest()})
      ReST._repo.add_graph(recording.save_to_graph())
      recording.close()
    except Exception, msg:
      raise  ###########
      ### Log traceback if debugging...
      raise BadRequest("%s: %s -> %s" % (msg, source, file_name), )

    logging.debug("Imported %s -> %s", source, file_name)

    location = '%s://%s/%s' % (web.ctx.environ['wsgi.url_scheme'],
                               web.ctx.environ['HTTP_HOST'],
                               name)
    # Does web.ctx give us the original URL ???
    body = '\n'.join(['<bsml>',
                      ' <created',
                      '  class="recording"',
                      '  uri="%s"'      % recording.uri,
                      '  mimetype="%s"' % ctype,
                      '  />',
                      '</bsml>', ''])
    # Or do we return HTML? RDF/XML of provenance? And include location in provenance...
    # OR a <status>Added...</status> message ???
    # OR <added>...</added>  ??
    # Content-type: XML? application/x-bsml+xml ???
    ## Return 200 OK since we are providing content
    ## Otherwise return Created()
    raise web.OK(body, {'Location': recording.uri,
                        'Content-Type': MIMETYPE_BSML})


  def POST(self, name):
  #--------------------
    logging.debug('POST: %s', web.ctx.environ)
    source = self._pathname(name)[0]
    return "<html><body><p>POST: %s</p></body></html>" % source


  def DELETE(self, name):
  #----------------------
    ###print name, web.ctx.environ
    source, filename, fragment = self._pathname(name)
    rec_uri = ReST._repo.base + source
    recording = ReST._repo.get_recording(rec_uri)
    if recording.source is None:
      raise NotFound("Recording '%s' is not in repository" % rec_uri)
    if fragment:
      raise NotFound("Cannot delete fragment of '%s'" % rec_uri)

    try:
      file_name = urllib.urlopen(str(recording.source)).fp.name
      if file_name != '<socket>': os.unlink(file_name)
    except IOError:
      pass
    ## But if multiple files in the recording?? eg. SDF, WFDB, ...

    ReST._repo.remove_graph(rec_uri)
    logging.debug("Deleted '%s' (%s)", rec_uri, recording.source)
    raise web.OK('\n'.join(['<bsml>',
                            ' <deleted uri="%s"/>' % rec_uri,
                            '</bsml>', '']), {'Content-Type': MIMETYPE_BSML})


  def HEAD(self, name):
  #--------------------
    return "<html><body><p>HEAD: %s</p></body></html>" % name
