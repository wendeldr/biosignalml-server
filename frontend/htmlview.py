######################################################
#
#  BioSignalML Management in Python
#
#  Copyright (c) 2010  David Brooks
#
#  $Id: biosignalml.py,v eeabfc934961 2011/02/14 17:47:59 dave $
#
######################################################


import logging
import urllib
import tornado.web
from tornado.options import options

import biosignalml.rdf as rdf
import biosignalml.model as model
from biosignalml import BSML, Annotation, Event
from biosignalml.utils import trimdecimal, chop, xmlescape
from biosignalml.utils import maketime, datetime_to_isoformat

from forms import Button, Field
import frontend
import mktree
import menu
import user


SNORQL_ENDPOINT = '/snorql/'      ##### Needs to come from ../server.py

PREFIXES = { 'bsml':  BSML.URI }
PREFIXES.update(rdf.NAMESPACES)


def resource_to_repository_URI(uri):
#-----------------------------------
#  logging.debug('U=%s, RP=%s, RS=%s', uri, options.repository.uri, options.resource_prefix)
  if str(uri).startswith(options.resource_prefix):
    return str(options.repository.uri) + '/repository/' + str(uri)[len(options.resource_prefix):]
  else:
    return uri


def abbreviate(u):
#-----------------
  s = str(u) if u else ''
  for p, n in PREFIXES.iteritems():
    if s.startswith(n): return ''.join([p, ':', s[len(n):]])
  return s


class Properties(object):
#========================
  def __init__(self, properties):
    self._properties = properties

  def header(self, all=False):
    if all:
      return [ (p[0] if p[0][0] != '*' else p[0][1:]) for p in self._properties ]
    else:
      return [ p[0] for p in self._properties if p[0][0] != '*']

  def details(self, object, all=False, **kwds):
    r = [ ]
    for p in [ p for p in self._properties if (all or p[0][0] != '*')]:
      prop = p[1]
      v = getattr(object, prop, None)
      if v is None:
        meta = getattr(object, 'metadata', None)
        if meta: v = meta.get(prop)
      args = p[3] if (len(p) > 3) else []
      r.append('' if v is None
          else (p[2](v, **{ k: v for k, v in kwds.iteritems() if k in args })) if (len(p) > 2)
          else [ str(s) for s in v ] if isinstance(v, list)
          else unicode(v)
          )
    return r

def property_details(object, properties, **args):
#------------------------------------------------
  r = [ ]
  prompts = properties.header()
  for n, d in enumerate(properties.details(object, **args)):
    if d:
      t = '<br/>'.join(list(d)) if hasattr(d, '__iter__') else str(d)
      r.append('<span class="emphasised">%s: </span>%s' % (prompts[n], xmlescape(t).replace('\n', '<br/>')))
  return '<p>' + '</p><p>'.join(r) + '</p>'


def rdflink(uri):
#----------------
  return ('<a href="%s">RDF</a> <a href="%s?describe=%s">SNORQL</a>'
         % (uri, SNORQL_ENDPOINT, urllib.quote_plus(str(uri))) )

def annotatelink(uri):
#---------------------
  return '<a href="/repository/%s?annotations">Add Annotation</a>' % uri


def link(uri, trimlen=0, makelink=True):
#---------------------------------------
  text = chop(uri, trimlen)
  if makelink:
    return '<a href="%s">%s</a>' % (resource_to_repository_URI(uri), text)
  else:
    return text


signal_properties = Properties([
                      ('Id',    'uri',   link, ['trimlen', 'makelink']),
                      ('Name',  'label'),
                      ('Units', 'units', abbreviate),
                      ('Rate',  'rate',  trimdecimal),
##                      ('*Annotations', 'uri', annotatelink),
                      ('*RDF',         'uri', rdflink),
                    ])

recording_properties = Properties([
                         ('Desc',      'description'),
                         ('Created',   'starttime'),
                         ('Duration',  'duration', maketime),
                         ('Format',    'format', abbreviate),
                         ('Study',     'investigation'),
                         ('Comments',  'comment'),
                         ('Source',    'source'),
                         ('Submitted', 'dateSubmitted', datetime_to_isoformat),
                       ])

annotation_properties = Properties([
                          ('About',      'target'),
                          ('Created',    'annotated', datetime_to_isoformat),
                          ('Author',     'annotator'),
                          ('Annotation', 'body', lambda b: b.text),
                        ])


def recording_info(rec):
#-----------------------
  html = [ '<div id="recording" class="treespace">' ]
  html.append('<div class="block">')
  html.append(rdflink(rec.uri))
##  html.append(annotatelink(rec.uri))
  html.append('</div>')
  html.append(property_details(rec, recording_properties))
  html.append('</div>')
  return ''.join(html)


def time_display(t):
#-------------------
  d = ['%g s' % t.start]
  if t.duration: d.append('for %g s' % d.duration)
  return ' '.join(d)


def event_info(evt):
#------------------
  props = Properties([('Event at:', 'time', time_display),
                      (' ',         'body', lambda b: b.text)])
  h = [ ]
  prompts = props.header()
  for n, d in enumerate(props.details(evt)):
    if d is None: d = ''
    t = '<br/>'.join(list(d)) if hasattr(d, '__iter__') else str(d)
    p = '<span class="prompt">%s </span>%s' % (prompts[n], xmlescape(t).replace('\n', '<br/>'))
    if   n == 0: h.append('<div><div class="event_time">%s</div>' % p)
    elif n == 1: h.append('<span>%s</span></div>' % p)
  return ''.join(h)


def annotation_info(ann):
#------------------------

  if isinstance(ann, model.Event): return event_info(ann)

  props = Properties([('Author',     'annotator'),
                      ('Created',    'annotated', datetime_to_isoformat),
                      ('Annotation', 'body', lambda b: b.text)])
  h = [ ]
  prompts = props.header()
  for n, d in enumerate(props.details(ann)):
    if d is None: d = ''
    t = '<br/>'.join(list(d)) if hasattr(d, '__iter__') else str(d)
    p = '<span class="prompt">%s: </span>%s' % (prompts[n], xmlescape(t).replace('\n', '<br/>'))
    if   n == 0: h.append('<div><div class="half">%s</div>' % p)
    elif n == 1: h.append('<span>%s</span></div>' % p)
    else:        h.append('<p>%s</p>' % p)
  return ''.join(h)


def signal_table(handler, recording, selected=None):
#---------------------------------------------------
  lenhdr = len(str(recording.uri)) + 1
  # Above is for abbreviating signal id;
  # should we check str(sig.uri).startswith(str(rec.uri)) ??
  rows = [ ]
  selectedrow = -1
  for n, sig in enumerate(recording.signals()):
    if str(sig.uri) == selected: selectedrow = n
    rows.append(signal_properties.details(sig, True, trimlen=lenhdr))
  return handler.render_string('table.html',
    header = signal_properties.header(True),
    rows = rows,
    selected = selectedrow,
    treespace = True,
    tableclass = 'signal')


def build_metadata(uri):
#-----------------------
  #logging.debug('Get metadata for: %s', uri)
  html = [ '<div class="metadata">' ]
  if uri:
    repo = options.repository
    rec_uri, graph_uri = repo.get_recording_and_graph_uri(uri)
    objtypes = repo.get_types(uri, graph_uri)
    if   BSML.Recording in objtypes:    # repo.has_recording(uri)
      rec = repo.get_recording(uri)
      ## What about a local cache of opened recordings?? (keyed by uri)
      ## in bsml.recordings module ?? in repo ??
      html.append(property_details(rec, recording_properties))
      # And append info from repo.provenance graph...
    elif BSML.Signal in objtypes:       # repo.has_signal(uri)
      sig = repo.get_signal(uri)
      html.append(property_details(sig, signal_properties, makelink=False))
    elif BSML.Event in objtypes:
      html.append('event type, time, etc')
    elif (rdf.TL.RelativeInstant in objtypes
       or rdf.TL.RelativeInterval in objtypes):
      html.append('time, etc')
    elif (BSML.Annotation in objtypes      #  OA.Annotation
       or BSML.Event in objtypes):
      ann = repo.get_annotation(uri)
      html.append(property_details(ann, annotation_properties))
    elif rdf.CNT.ContentAsText in objtypes:
      ann = repo.get_annotation_by_content(uri)
      html.append(property_details(ann, annotation_properties))
    else:
      html.append(str(objtype))
  html.append('</div>')
  return ''.join(html)


class Metadata(tornado.web.RequestHandler):  # Tool-tip popup
#==========================================
  def post(self):
    self.write({ 'html': build_metadata(self.get_argument('uri', '')) })



def get_annotation(graph, uri):
#------------------------------
  '''
  Get an Annotation from the repository.

  :param uri: The URI of an Annotation.
  :rtype: :class:`~biosignalml.Annotation`
  '''
  if graph.contains(rdf.Statement(uri, rdf.RDF.type, BSML.Event)):
    return Event.create_from_graph(uri, graph)
  else:
    return Annotation.create_from_graph(uri, graph)


class Repository(frontend.BasePage):
#===================================

  def _xmltree(self, uris, base, prefix, select=''):
    tree = mktree.maketree(uris, base)
    #logging.debug('tree: %s', tree)
    if select.startswith(options.resource_prefix):
      selectpath = select[len(options.resource_prefix):].split('/')
    elif select.startswith('http://') or select.startswith('file://'):
      selectpath = select.rsplit('/', select.count('/') - 2)
    else:
      selectpath = select.split('/')
    #logging.debug('SP: %s, %s', select, selectpath)
    return self.render_string('ttree.html',
                               tree=tree, prefix=prefix,
                               selectpath=selectpath)

  def _show_contents(self, name, annotate):
    repo = options.repository
    prefix = options.resource_prefix[:-1]
    if name:
      recuri = (name if name.startswith('http://') or name.startswith('file://')
               else '%s/%s' % (prefix, name))
      #logging.debug('RECORDING: %s', recuri)
      recording = repo.get_recording_with_signals(recuri)
      if recording is None:
        self.send_error(404) # 'Unknown recording...')
        return
      if str(recording.uri) != recuri:
        selectedsig = recuri
        recuri = str(recording.uri)
      else:
        selectedsig = None
      kwds = dict(bodytitle = recuri, style = 'signal',
                  tree = self._xmltree(repo.recordings(), prefix, frontend.REPOSITORY, name),
                  content = recording_info(recording)
                          + signal_table(self, recording, selectedsig) )
      target = selectedsig if selectedsig else recuri
      annotations = [ annotation_info(get_annotation(recording.graph, ann))
                       for ann in repo.annotations(target) ]
      if not annotate : annotations.append(annotatelink(target))
      kwds['content'] += self.render_string('annotate.html', uri=target, annotations=annotations)
      if annotate:
        self.render('tform.html',
          bottom = True,    # Form below other content
          treespace = True,
          formclass = 'annotform',
          rows = 6,  cols = 0,
          buttons = [ Button('Annotate', 1, 4), Button('Cancel', 1, 5) ],
          fields = [ Field.textarea('Add Annotation', 'annotation', 60, 8),
                     Field.hidden('target', target ) ],
          **kwds)
      else: self.render('tpage.html', **kwds)
    else:
      self.render('tpage.html',
        title = 'Recordings in repository:',
        tree = self._xmltree(repo.recordings(), prefix, frontend.REPOSITORY))

  @tornado.web.authenticated
  def get(self, name=''):
    self._show_contents(name, 'annotations' in self.request.query)

  @tornado.web.authenticated
  def post(self, name=''):
    body = self.get_argument('annotation', '').strip()
    if self.get_argument('action') == 'Annotate' and body:
      repo = options.repository
      target = self.get_argument('target')
      recording = repo.get_recording(target)
      ann = Annotation.Note(recording.make_uri(prefix='annotation'), target,
                            '%s/user/%s' % (repo.uri, self.current_user), body)
      repo.extend_graph(recording.graph.uri, ann.metadata_as_string())
    self._show_contents(name, False)
