# coding=UTF-8
#
# Readability. An Arc90 Lab Experiment.
# Website: http://lab.arc90.com/experiments/readability
# Source:  http://code.google.com/p/arc90labs-readability
#
# Copyright (c) 2009 Arc90 Inc
# Readability is licensed under the Apache License, Version 2.0.
#
# Python port (c) Alex Popescu
#
# Compatible with readability.js 1.7.1, except the multi-page part
from __future__ import generators

import htmlentitydefs
import logging
import re
import urllib
import urlparse

from string import punctuation

__READABILITY_VERSION__ = '1.7.1'
__BEAUTIFULSOUP_VERSION = '3.2.0'
__VERSION__ = '1.7.1.11'
__DEBUG__ = False 
__OUTPUT__ = True

unlikelyCandidatesRe = re.compile('combx|comment|community|disqus|extra|foot|header|menu|remark|meta|nav|rss|shoutbox|sidebar|sponsor|ad-break|agegate|pagination|pager|popup|tweet|twitter', re.IGNORECASE)
okMaybeItsACandidateRe = re.compile('and|article|body|column|main|shadow', re.IGNORECASE)
positiveRe = re.compile('article|body|content|entry|hentry|main|page|pagination|post|text|blog|story', re.IGNORECASE)
negativeRe = re.compile('combx|comment|com-|contact|foot|footer|footnote|link|masthead|media|meta|outbrain|promo|related|scroll|shoutbox|sidebar|sponsor|shopping|tags|tool|widget', re.IGNORECASE)
extraneousRe = re.compile('print|archive|comment|discuss|e[\-]?mail|share|reply|all|login|sign|single', re.IGNORECASE)
divToPElementsRe = re.compile('<(a|blockquote|dl|div|img|ol|p|pre|table|ul)', re.IGNORECASE)
replaceBrsRe = re.compile('(<br[^>]*>[ \n\r\t]*){2,}', re.IGNORECASE | re.MULTILINE)
replaceFontsRe = re.compile('<(/?)font[^>]*>', re.IGNORECASE | re.MULTILINE)
trimRe = re.compile('^\s+|\s+$', re.MULTILINE)
normalizeRe = re.compile('\s+', re.MULTILINE)
killBreaksRe = re.compile('(<br\s*/?>(\s|&nbsp;?)*){1,}', re.MULTILINE)
killMoreBreaksRe = re.compile('<br[^>]*>\s*<p', re.MULTILINE)
videoRe = re.compile('(youtube|vimeo|blip|slideshare)\.(com|tv|net)', re.IGNORECASE)
unknownRe = re.compile('\.( |$)')
skipFootnoteLink = re.compile('^\s*(\[?[a-z0-9]{1,2}\]?|^|edit|citation needed)\s*$', re.IGNORECASE)
nextLinkRe = re.compile('(next|weiter|continue|>([^\|]|$)|»([^\|]|$))', re.IGNORECASE) # Match: next, continue, >, >>, ¬ª but not >|, ¬ª| as those usually mean last.
prevLinkRe = re.compile('(prev|earl|old|new|<|«)', re.IGNORECASE)
wordSplitRe = re.compile('(\s|&nbsp;|&#160;|&#xA0)+', re.UNICODE)

READ_STYLES = ('style-newspaper', 'style-novel', 'style-athelas', 'style-ebook', 'style-apertura')
READ_MARGINS = ('margin-x-narrow', 'margin-narrow', 'margin-medium', 'margin-wide', 'margin-x-wide')
SIZES = ('size-x-small', 'size-small', 'size-medium', 'size-large', 'size-x-large')

# TODO:
# - frames (?)
# - use Tag.fetchText()

_DEFAULT_SETTINGS = {
  'footnote_links': False,
  'readable_links': False,
  'readable_footnote_links': False,
  'read_style': 'style-athelas',
  'read_margin': 'margin-medium',
  'read_size': 'size-medium',
  'strip_unlike': True,
  'weight_classes': True,
  'clean_conditionally': True
}

class Readability(object):
  def __init__(self, content, url=None, footnote_links=False, **settings):
    ''' Supported settings:

    - footnote_links: extract a set of footnotes from all links in content
    - readable_links: transform content links to go through readability
    - readable_footnote_links: include in the footnotes links that go through readability

    - read_style: formatting setting
    - read_margin: formatting setting
    - read_size: formatting setting

    - strip_unlike: processing setting
    - weight_classes: processing setting
    - clean_conditionally: processing setting
    '''
    self._conf = _DEFAULT_SETTINGS.copy()
    self._conf.update(settings)
    self._conf['footnote_links'] = footnote_links
    self._conf['readable_footnote_links'] = self._conf['footnote_links'] and self._conf['readable_footnote_links']

    self._url = url or ""
    
    self.content = replaceBrsRe.sub('</p><p>', content)
    try:
      self._osoup = ICantBelieveItsBeautifulSoup(self.content)
    except TypeError:
      raise ValueError('content cannot be converted to unicode')
#    dbg("content: %s" % self._osoup)
    self._fsoup = ICantBelieveItsBeautifulSoup(Readability.OUTPUT_BODY % self._conf)

  def get_html(self, prettyPrint=False, removeComments=True):
    if removeComments:
      [comment.extract() for comment in self._fsoup.findAll(text=lambda text:isinstance(text, Comment))]

    output = self._fsoup.renderContents(prettyPrint=prettyPrint)
    output = clean_extraspaces(output)
    return output

  def get_doc(self, removeComments=True):
    """ Returns the output as a BeautifulSoup object.
    Note that this object is a copy and modifying it will not
    modify the real output"""
    return ICantBelieveItsBeautifulSoup(self.get_html(removeComments=removeComments))

  def process_document(self):
    self._prepare_document()
#    dbg("_prepare_document:content: %s" % self._osoup)

    nextPageLinks = self._find_next_page_link()
    dbg("nextPageLinks: %s" % nextPageLinks)
    
    article_title = self._getArticleTitle()
    
    if not len(self._osoup.findAll('body')):
      articleContent = Tag(self._fsoup, 'p')
      articleContent.setString("Sorry, readability was unable to parse this page for content. If you feel like it should have been able to, please <a href='http://code.google.com/p/arc90labs-readability/issues/entry'>let us know by submitting an issue.</a>")
    else:
      articleContent = self._grabArticle()
      #
      # If we attempted to strip unlikely candidates on the first run through, and we ended up with no content,
      # that may mean we stripped out the actual content so we couldn't parse it. So re-run init while preserving
      # unlikely candidates to have a better shot at getting our content out properly.
      #
      if (not articleContent) or (len(get_inner_text(articleContent)) == 0):
        articleContent = Tag(self._fsoup, 'p')
        articleContent.setString("Sorry, readability was unable to parse this page for content. If you feel like it should have been able to, please <a href='http://code.google.com/p/arc90labs-readability/issues/entry'>let us know by submitting an issue.</a>")
      else:
        if nextPageLinks:
          pagesep = Tag(self._fsoup, 'p', attrs=[('class', 'readability-page-separator')])
          pagesep.setString('&#167;')
          articleContent.append(pagesep)
          continuationparagraph = Tag(self._fsoup, 'p', attrs=[('class', 'readability-page-pagination')])
          continuationparagraph.setString("Continuation: ")
          for idx, nextPage in enumerate(nextPageLinks):
            nextPageLink = Tag(self._fsoup, 'a', attrs=[('class', 'readability-page-next'), ('href', nextPage['href'])])
            nextPageLink.setString("%s" % (idx + 2))
            continuationparagraph.append(nextPageLink)
            continuationparagraph.append("&nbsp;")
          articleContent.append(continuationparagraph)

    divInner = self._fsoup.find('div', attrs={'id':'readInner'})
    divInner.append(article_title)
#    if self._url:
#      divInner.append(self._get_article_link())
    divInner.append(articleContent)
    divInner.append(self._getArticleFooter(article_title))

    # prepare head
    head = self._osoup.find('head')
    if not head:
      head = Tag(self._fsoup, 'head')
    screen_stylesheet = Tag(self._fsoup, 'link', attrs=[('rel', 'stylesheet'),
                                                       ('href', 'http://lab.arc90.com/experiments/readability/css/readability.css'),
                                                       ('type', 'text/css'),
                                                       ('media', 'screen')])
    print_stylesheet = Tag(self._fsoup, 'link', attrs=[('rel', 'stylesheet'),
                                                      ('href', 'http://lab.arc90.com/experiments/readability/css/readability-print.css'),
                                                      ('type', 'text/css'),
                                                      ('media', 'print')])
    inline_stylesheet = Tag(self._fsoup, 'style', attrs=[('type', 'text/css')])
    inline_stylesheet.setString('.style-apertura{font-family:"apertura-1","apertura-2",sans-serif;}')
    
    typekit_css = Tag(self._fsoup, 'link', attrs=[('rel', 'stylesheet'),
                                                  ('href', 'http://use.typekit.com/v/bae8ybu-b.css?'),
                                                  ('type', 'text/css')])
    typekit_js = Tag(self._fsoup, 'script', attrs=[('src', 'http://use.typekit.com/bae8ybu.js'),
                                                   ('type', 'text/javascript'),
                                                   ('charset', 'UTF-8')])

    self._fsoup.find('html').insert(0, head)
    head = self._fsoup.find('head')
    head.append(screen_stylesheet)
    head.append(print_stylesheet)
    head.append(inline_stylesheet)
    head.append(typekit_css)
    head.append(typekit_js)

    self._post_process_content()

  def _get_article_link(self):
    art_link = Tag(self._fsoup, 'p')
    art_link.setString("<small>%s</small>" % self._url)
    return art_link

  def _getArticleFooter(self, title):
    articleFooter = Tag(self._fsoup, 'div', attrs=[('id', 'readFooter')])
    if self._url:
      articleFooter.setString("<div id='rdb-footer-print-'><cite><a href='%s'>%s</a></cite></div>" % (self._url, self._url))
    
    return articleFooter

  def _post_process_content(self):
    ''' Adds footnotes for links, fixes images floats '''
    self._fix_lists()
    
    self._fix_links()
    
    if self._conf['footnote_links']:
      self._add_footnotes()

    self._fix_image_floats()

    # remove extra class attributes
    self._clean_class_attr()

  def _clean_class_attr(self):
    real_body = self._fsoup.find('div', attrs={'id': 'readability-content'})
    if real_body:
      for e in real_body.findAll(attrs={'class': True}):
        cls = e['class']
        if cls.find('readability') == -1:
          dbg("clean_class_attr %s (%s)" % (e.name, e['class']))          
          del e['class']

  def _fix_lists(self):
    ''' sometimes the DOM ends up with LI elements without parents '''
    for li in self._fsoup.findAll('li'):
      if li.parent and li.parent.name in ('ul', 'ol'):
        continue
      # must append ul
      dbg("_fix_lists: missing UL/OL")
      ul = Tag(self._fsoup, 'ul')
      new_li = Tag(self._fsoup, 'li', attrs=li.attrs)
      for c in [c for c in li.contents]:
        new_li.append(c)
      ul.append(new_li)
      sibling = li.nextSibling
      siblings = []
      while sibling:
        if isinstance(sibling, NavigableString):
          if sibling.strip(' \n\r\t'):
            nli = Tag(self._fsoup, 'li')
            nli.string = sibling
            siblings.append(nli)
          sibling = sibling.nextSibling
        if isinstance(sibling, Tag) and sibling.name == 'li':
          siblings.append(sibling)
          sibling = sibling.nextSibling
        else:
          break
      for s in siblings:
        ul.append(s)
      dbg("_fix_lists: new UL: %s" % ul)        
      li.replaceWith(ul)

  def _fix_links(self):
    if not self._url:
      return
    bits = urlparse.urlsplit(self._url)
    hostname = "%s://%s" % (bits[0], bits[1])
    rel_uri = self._url[:self._url.rfind('/')+1]

    for link in self._fsoup.findAll('a'):
      if (not link.get('href')) or (link.get('class') == 'readability-DoNotFootnote') or (skipFootnoteLink.match(self.getInnerText(link))):
        continue
      if link['href'].startswith('#'):
        continue
      if link['href'] == self._url:
        continue
      if link['href'].startswith('http://') or link['href'].startswith('https://'):
        continue
      elif link['href'].startswith('/'):
        link['href'] = hostname + link['href']
      else:
        link['href'] = rel_uri + link['href']

    
  def _add_footnotes(self):
    footnotesWrapper = self._fsoup.find({'id': 'readability-footnotes'})
    articleFootnotes = self._fsoup.find({'id': 'readability-footnotes-list'})

    if not footnotesWrapper:
      footnotesWrapper = Tag(self._fsoup, 'div', attrs=[('id', 'readability-footnotes'),
                                                        ('style', 'display:none')])
      footnotesTitle = Tag(self._fsoup, 'h3')
      footnotesTitle.setString('References')
      footnotesWrapper.append(footnotesTitle)

      articleFootnotes = Tag(self._fsoup, 'ol', attrs=[('id', 'readability-footnotes-list')])
      footnotesWrapper.append(articleFootnotes)

      readFooter = self._fsoup.find('div', attrs={'id':'readFooter'})
      if readFooter:
        rf = readFooter
        parent = rf.parent
        readFooter.replaceWith(footnotesWrapper)
        parent.append(rf)
      else:
        self._fsoup.find('div', attrs={'id': 'readInner'}).append(footnotesWrapper)

    readable_links_uri = self._conf.get('service_uri')
    make_readable_links = self._conf['readable_footnote_links'] and readable_links_uri

    linkCount = len(articleFootnotes.findAll('li'))
    for link in self._fsoup.findAll('a'):
      if (not link.get('href')) or (link.get('class') == 'readability-DoNotFootnote') or (skipFootnoteLink.match(self.getInnerText(link))):
        continue
      if link['href'].startswith('#'):
        continue
      if self._url and link['href'] == self._url:
        continue
        
      linkCount += 1

      footnote = Tag(self._fsoup, 'li')
      if make_readable_links:
        url_bits = urlparse.urlparse(link['href'])
        footnoteLink = Tag(self._fsoup, 'a', attrs=[('href', readable_links_uri % urllib.quote(link['href']))])
        footnoteLink.setString("".join(url_bits[1:]))
        footnoteLink['name'] = "readabilityFootnoteLink-%s" % linkCount

        footnote.setString("<small>%s</small> (<small><a href='%s'>%s</a></small>) <small><a href='#readabilityLink-%s' title='Jump to Link in Article'>back &#8617;</a></small>" %
                           (footnoteLink, link['href'], url_bits[1], linkCount))
      else:
        footnoteLink = Tag(self._fsoup, 'a', attrs=[('href', link.get('href'))])
        footnoteLink.setString(link['href'])
        footnoteLink['name'] = "readabilityFootnoteLink-%s" % linkCount
        footnote.setString("<small>%s</small> <small>(<a href='#readabilityLink-%s' title='Jump to Link in Article'>back &#8617;</a>)</small> " % (footnoteLink, linkCount))


      refLink = Tag(self._fsoup, 'a', attrs=[('href', '#readabilityFootnoteLink-%s' % linkCount),
                                             ('class', 'readability-DoNotFootnote')])
      refLink.setString("[%s]" % linkCount)

      refLinkSup = Tag(self._fsoup, 'sup')
      refLinkSup.append(refLink)

      replLink = Tag(self._fsoup, 'a', attrs=[('href', link['href']),
                                              ('name', "readabilityLink-%s" % linkCount)])
      replLink.setString(self.getInnerText(link))

      replElem = Tag(self._fsoup, 'span')
      replElem.append(replLink)
      replElem.append(refLinkSup)

      link.replaceWith(replElem)

      articleFootnotes.append(footnote)

    if linkCount > 0:
      footnotesWrapper['style'] = 'display:block;'

  def _fix_image_floats(self):
    imageWidthThreshold = 800 * 0.55

    if self._url:
      bits = urlparse.urlsplit(self._url)
      hostname = "%s://%s" % (bits[0], bits[1])
      rel_uri = self._url[:self._url.rfind('/')+1]
      for img in self._fsoup.findAll('img', attrs={'src': True}):
        img_src = img['src']
        if img_src.startswith('http'):
          continue
        elif img_src.startswith('/'):
          img['src'] = hostname + img_src
        else:
          img['src'] = rel_uri + img_src
          
    for img in self._fsoup.findAll('img'):
      try:
        width = int(img.get('width'), 0)
      except:
        width = 0
      if width > imageWidthThreshold:
        img['class'] = "blockImage readabilityImg %s" % img.get("class", '')      

  def _prepare_document(self):
    # let's firstly fix as much as possible the content
    html_element = self._osoup.find('html')
    if not html_element:
      html_element = Tag(self._osoup, 'html')
      elements = [t for t in self._osoup.findAll(True)]
      for el in elements:
        html_element.append(el)
      self._osoup.insert(0, html_element)
    head_element = self._osoup.find('head')
    if not head_element:
      head_element = Tag(self._osoup, 'head')
      elements = [t for t in self._osoup.findAll(True) if t.name in ('title', 'meta', 'link')]
      for el in elements:
        head_element.append(el)
        html_element.insert(0, head_element)
  
    # check if there are multiple bodies: preserve concatenate all
    bodies = self._osoup.findAll('body')
    if len(bodies) > 1:
      final_body = bodies[0]
      for b in bodies[1:]:
        for c in [c for c in b.contents]:
          final_body.append(c)
        b.extract()
    elif len(bodies) == 0:
      body = Tag(self._osoup, 'body')
      elements = [t for t in self._osoup.findAll(True) if t.name not in ('html', 'head', 'title', 'meta', 'link')]
      for el in elements:
        body.append(el)
      html_element.append(body)
    self._osoup.find('body')['id'] = 'readabilityBody'

    # remove all scripts
    [script.extract() for script in self._osoup.findAll('script')]
    
    # remove all stylesheets
    [style.extract() for style in self._osoup.findAll('style')]

    # remove all style tags in head
    [link.extract() for link in self._osoup.findAll('link', attrs={'rel': 'stylesheet'})]

    # remove fonts
    for font in self._osoup.findAll('font'):
      self._replace_element(self._osoup, font, 'span')

    for ta in self._osoup.findAll('textarea'):
      if ta.string:
        ta.setString(ta.string.replace('<', '&lt;').replace('>', '&gt;'))

  def _getArticleTitle(self):
    articleTitle = Tag(self._fsoup, 'h1')
    title_element = self._osoup.find('title')
    candidate_title = None
    if title_element:
      candidate_title = self.getInnerText(title_element)
      dbg("_get_article_title::candidate_title<title>: %s" % title_element)
    else:
      h1s = self._osoup.findAll('h1')
      if h1s and len(h1s) == 1:
        candidate_title = self.getInnerText(h1s[0])
        dbg("_get_article_title::candidate_title<h1>: %s" % title_element)

    if not candidate_title:
      return articleTitle

    alt_candidate_title = wordSplitRe.sub(' ', unescape(candidate_title))
    title_words = {}
    for word in [w.strip(punctuation).lower() for w in alt_candidate_title.split() if len(w) > 3]:
      title_words[word] = True

#    dbg("title words: (%s) %s" % (len(title_words), title_words))
      
    possible_titles = {}    
    h12s = self._osoup.findAll({'h1' : True, 'h2' : True})
    if h12s:
      for tag in h12s:
        innerText = self.getInnerText(tag)
        score = 0.0
        # somehow I need to penalize those that do not have words in common
        common_words = 0
        words = [w.strip(punctuation).lower() for w in wordSplitRe.sub(' ', unescape(innerText)).split()]
        for word in words:
          if title_words.has_key(word):
            common_words += 1
        word_match_score = -5.0 + (10.0 * common_words / len(title_words))
#        dbg("common_match: %s=>%s (%s: %s)" % (common_words, word_match_score, words, innerText.encode('utf8')))
        score += word_match_score
        links = tag.findAll('a')
        if len(links) > 1:
          continue
        if len(links) == 1:
          link = links[0]
          
          if innerText != self.getInnerText(link):
            continue

          href = link.get('href')
          if href and self._url:
            if href == "/":
              score -= 25
            elif self._url.startswith(href) and len(href) < len(self._url):
              score -= 25
            elif self._url.find(href) > -1:
              score += 25
        attr = tag.get('id')
        if attr and attr.find('title') > -1:
          score += (10 * len('title') / len(attr))
        attr = tag.get('class')
        if attr and attr.find('title') > -1:
          bits = attr.split(' ')
          for b in [b for b in bits if b.find('title') > -1]:
            score += (5 * len('title') / len(b))

        possible_titles[innerText] = (score, tag, word_match_score)

    dbg("_get_article_title::possible titles: %s" % possible_titles)
    
    if not len(possible_titles): # there aren't multiple possible titles
      if candidate_title:
        candidate_title = candidate_title.strip()
      articleTitle.setString(candidate_title)
      return articleTitle

    max_score = 0
    best_candidate = None
    for inner_text, scoret in possible_titles.items():
      if scoret[0] > max_score:
        best_candidate = inner_text
        max_score = scoret[0]

    if best_candidate:
      if alt_candidate_title.find(wordSplitRe.sub(' ', unescape(best_candidate))) > -1:
        candidate_title = best_candidate
#        dbg("_get_article_title::title best_candidate (success:%s:%s): '%s' (page title:%s)" % (score_tuple[0], score_tuple[2], best_candidate.encode('utf8'), candidate_title.encode('utf8')))
#      elif max_score > 0:
#        dbg("_get_article_title::title best_candidate (unsure :%s:%s): '%s' (page title:%s)" % (score_tuple[0], score_tuple[2], best_candidate.encode('utf8'), candidate_title.encode('utf8')))
#      else:
#        dbg("_get_article_title::title best_candidate (failure:%s:%s): '%s' (page title:%s)" % (score_tuple[0], score_tuple[2], best_candidate.encode('utf8'), candidate_title.encode('utf8')))
    if candidate_title:
      candidate_title = candidate_title.strip()
    articleTitle.setString(candidate_title)

    return articleTitle


  def _grabArticle(self):
    def match_unlikely_candidates(node):
      if not isinstance(node, Tag):
        return False
      if node.name == 'body':
        return False
      unlikelyMatchString = node.get('class', '') + node.get('id', '')
      return unlikelyMatchString and \
        unlikelyCandidatesRe.search(unlikelyMatchString) and \
        not okMaybeItsACandidateRe.search(unlikelyMatchString)

    if self._conf['strip_unlike']:
      for node in self._osoup.body.findAll(match_unlikely_candidates):
        dbg("Removing unlikely candidate - " + node.get('class', '') + node.get('id', ''))
        node.extract()

    # Turn all divs that don't have children block level elements into p's
    for node in self._osoup.body.findAll('div'):
      children = node.findAll(['a', 'blockquote', 'dl', 'div', 'img', 'ol', 'p', 'pre', 'table', 'ul'])
      if not len(children):
        self._replace_element(self._osoup, node, 'p')
        dbg("Altering div to p")
      else:
        # experimental: replace text node with a p tag with the same content
        new_div = Tag(self._osoup, 'div', attrs=node.attrs)
        for c in [c for c in node.contents]:
          # let's ignore Comments
#          if isinstance(c, Comment):
#            new_div.append(c)
          if isinstance(c, NavigableString) and c.strip(' \n\t\r'):
            new_p = Tag(self._osoup, 'p', attrs=[('class', 'readability-styled'), ('style', 'display:inline')])
            new_p.append(c)
            new_div.append(new_p)
          else:
            new_div.append(c)
        node.replaceWith(new_div)
        dbg("replacing text node with a p tag with the same content.")

    #
    # Loop through all paragraphs, and assign a score to them based on how content-y they look.
    # Then add their score to their parent node.
    #
    # A score is determined by things like number of commas, class names, etc. Maybe eventually link density.
    #
    candidates    = []

    for paragraph in self._osoup.body.findAll(['p', 'td', 'pre']):
      parentNode      = paragraph.parent
      grandParentNode = parentNode and parentNode.parent
      innerText       = self.getInnerText(paragraph)

      # If this paragraph is less than 25 characters, don't even count it.
      if len(innerText) < 25:
        continue

      # Initialize readability data for the parent.
      if not getattr(parentNode, 'readability', None):
        self.initializeNode(parentNode)
        candidates.append(parentNode)

      # Initialize readability data for the grandparent.
      if not getattr(grandParentNode, 'readability', None):
        self.initializeNode(grandParentNode)
        candidates.append(grandParentNode)

      contentScore = 0

      # Add a point for the paragraph itself as a base.
      contentScore += 1

      # Add points for any commas within this paragraph
      contentScore += len(innerText.split(','))

      # For every 100 characters in this paragraph, add another point. Up to 3 points.
      contentScore += min((len(innerText) / 100), 3)

      # Add the score to the parent. The grandparent gets half.
      parentNode.readability['contentScore'] += contentScore

      if grandParentNode:
        grandParentNode.readability['contentScore'] += contentScore/2

    #
    # After we've calculated scores, loop through all of the possible candidate nodes we found
    # and find the one with the highest score.
    #
    topCandidate = None
    for node in candidates:
      #
      # Scale the final candidates score based on link density. Good content should have a
      # relatively small link density (5% or less) and be mostly unaffected by this operation.
      #
      #dbg("before candidate found %s with contentScore: %d (%s:%s)" % (node.name, self._get_content_score(node), node.get('class', ''), node.get('id', '')))
        
      node.readability['contentScore'] = node.readability['contentScore'] * (1-self.getLinkDensity(node))

      dbg('Candidate: ' + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ") with score " + str(node.readability['contentScore']))

      if not topCandidate or node.readability['contentScore'] > topCandidate.readability['contentScore']:
        topCandidate = node


    #
    # If we still have no top candidate, just use the body as a last resort.
    # We also have to copy the body node so it is something we can modify.
    #
    if not topCandidate or topCandidate.name == 'body':
      topCandidate = Tag(self._osoup, 'div')
      for c in self._osoup.body.contents:
        topCandidate.append(c)
      self._osoup.body.append(topCandidate)
      self.initializeNode(topCandidate)
      dbg("Candidate: %s (%s:%s) with score %s" % (topCandidate.name, topCandidate.get('class', ''), topCandidate.get('id',''), self._get_content_score(topCandidate)))

    #
    # Now that we have the top candidate, look through its siblings for content that might also be related.
    # Things like preambles, content split by ads that we removed, etc.
    #
    articleContent = Tag(self._fsoup, 'div', attrs=[('id', 'readability-content')])
    siblingScoreThreshold = max(10, 0.2 * topCandidate.readability['contentScore'])

    append_list = []
    for sibling in topCandidate.parent.contents:
      if not isinstance(sibling, Tag):
        continue

      if not sibling:
        dbg('how the fuck can it be None???')
      dbg("Looking at sibling node: " + sibling.name + " (" + sibling.get('class', '') + ":" + sibling.get('id','') + ")")
      dbg("Sibling has score " + str(self._get_content_score(sibling)))

      append = (sibling == topCandidate)

#      self.initializeNode(sibling)
      
      contentBonus = 0
      # Give a bonus if sibling nodes and top candidates have the example same classname
      topCandidateClass = topCandidate.get('class', '') 
      if topCandidateClass and topCandidateClass == sibling.get('class', ''):
        contentBonus += self._get_content_score(topCandidate) * 0.2

      if self._get_content_score(sibling) + contentBonus >= siblingScoreThreshold:
        append = True

      if sibling.name == "p":
        linkDensity = self.getLinkDensity(sibling)
        nodeContent = self.getInnerText(sibling)
        nodeLength  = len(nodeContent)

        if nodeLength > 80 and linkDensity < 0.25:
          append = True
        elif nodeLength < 80 and linkDensity == 0 and unknownRe.search(nodeContent):
          append = True

      if append:
        dbg("Appending node: " + sibling.name + " (" + sibling.get('class', '') + ":" + sibling.get('id','') + ")" )

        # don't remove it from the iterator as I don't know what'll hapen
        append_list.append(sibling)

    for n in append_list:
      articleContent.append(n)

    #
    #So we have all of the content that we need. Now we clean it up for presentation.
    #
    self.prepArticle(articleContent)

    if len(get_inner_text(articleContent)) < 250:
      if self._conf['strip_unlike']:
        self._conf['strip_unlike'] = False
        self._osoup = ICantBelieveItsBeautifulSoup(self.content)
        self._prepare_document()
        return self._grabArticle()
      if self._conf['weight_classes']:
        self._conf['weight_classes'] = False
        self._osoup = ICantBelieveItsBeautifulSoup(self.content)
        self._prepare_document()
        return self._grabArticle()
      if self._conf['clean_conditionally']:
        self._conf['clean_conditionally'] = False
        self._osoup = ICantBelieveItsBeautifulSoup(self.content)
        self._prepare_document()
        return self._grabArticle()

    return articleContent

  def _get_content_score(self, node, bonus=0):
    result = 'unknown'
    try:
      result = node.readability['contentScore']
    except KeyError:
#      dbg("KeyError: node %s (%s:%s)" % (node.name, node.get("id"), node.get('class')) )
      pass
    except TypeError:
#      dbg("TypeError: node %s (%s:%s)" % (node.name, node.get("id"), node.get('class')) )
      pass

    if result == 'unknown':
      dbg("node (%s:%s) has unknown contentScore {%s}" % (node.get('id'), node.get('class'), '')) # node
      result = 0
    return result
    
  def prepArticle(self, articleContent):
    self.cleanStyles(articleContent)

    # this is better applied directly on the output string
    # self.kill_breaks(articleContent)

    self._clean(articleContent, 'form')
    self._clean(articleContent, 'object')
    self._clean(articleContent, 'h1')
    self._clean(articleContent, 'iframe')
    self._clean(articleContent, 'hr')

    subtitles = articleContent.findAll('h2') 
    if len(subtitles) == 1:
      [s.extract() for s in subtitles]


    for paragraph in articleContent.findAll('p'):
      imgCount = len(paragraph.findAll('img'))
      embedCount = len(paragraph.findAll(['embed', 'object']))
      if imgCount == 0 and embedCount == 0 and len(self.getInnerText(paragraph)) == 0:
        paragraph.extract()

    # readability.cleanHeaders(articleContent);
        
    self._clean_conditionally(articleContent, 'table')
    self._clean_conditionally(articleContent, 'ul')
    self._clean_conditionally(articleContent, 'div')
    

  def cleanStyles(self, articleContent):
    for c in articleContent.contents:
      if isinstance(c, Tag):
        if c.get('class', '') != 'readability-styled' and c.has_key('style'):
          del c['style']
        self.cleanStyles(c)
    
  def _clean(self, articleContent, tag):
    is_embed = (tag in ('object', 'embed'))
#    if is_embed:
#      dbg('working on embed')
    for c in articleContent.findAll(tag):
#      dbg('found: %s' % c)
      if is_embed and videoRe.search(str(c)):
#        dbg("matched: %s" % c)
        continue
      c.extract()

  def _clean_conditionally(self, articleContent, tag):
    for node in articleContent.findAll(tag):
      weight = self.getClassWeight(node)

      dbg("Cleaning Conditionally " + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ") w/ score:" + str(self._get_content_score(node)))
      
      if weight < 0:
        dbg("Removed  Conditionally (weight<0)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
        node.extract()
      elif self._get_char_count(node, ',') < 10:
        #
        # If there are not very many commas, and the number of
        # non-paragraph elements is more than paragraphs or other ominous signs, remove the element.
        #
        p = len(node.findAll('p'))
        img = len(node.findAll('img'))
        li = len(node.findAll('li')) - 100
        input = len(node.findAll('input'))

        embedCount = 0
        for embed in node.findAll(['embed', 'object']):
          if not videoRe.search(unicode(embed)):
            embedCount += 1

        linkDensity = self.getLinkDensity(node)
        contentLenght = len(self.getInnerText(node))
        toRemove = False

        if img > p:
          toRemove = True
          dbg("Removed  Conditionally (img>p)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
        elif li > p and tag != 'ul' and tag != 'ol':
          toRemove = True
          dbg("Removed  Conditionally (li>p)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
        elif input > (p / 3):
          dbg("Removed  Conditionally (input>p/3)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
          toRemove = True
        elif (contentLenght < 25) and (img == 0 or img > 2):
          dbg("Removed  Conditionally (contentLength<25 and img)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
          toRemove = True
        elif weight < 25 and linkDensity > .2:
          dbg("Removed  Conditionally (weight<25 and linkDensity)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
          toRemove = True
        elif weight >= 25 and linkDensity > .5:
          dbg("Removed  Conditionally (weight>=25 and linkDensity)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
          toRemove = True
        elif (embedCount == 1 and contentLenght < 75) or (embedCount > 1):
          dbg("Removed  Conditionally (embedCount)" + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
          toRemove = True

        if toRemove:
          node.extract()


  def _get_char_count(self, node, separator=','):
    return len(self.getInnerText(node).split(separator))
    
  def getLinkDensity(self, node):
    textLength = len(self.getInnerText(node))
    linkLength = 0
    for l in node.findAll('a'):
      linkLength += len(self.getInnerText(l))

    #dbg("get_link_density for %s %d/%d w/ contentScore: %s (%s:%s)" % (node.name, linkLength, textLength, self._get_content_score(node), node.get('class', ''), node.get('id', '')))
      
    if textLength == 0:
      return 1
    return float(linkLength) / textLength

  def initializeNode(self, node):
    node.readability = {'contentScore':0}

    tag = node.name 
    if tag == 'div':
      node.readability['contentScore'] += 5
    elif tag in ('pre', 'td', 'blockquote'):
      node.readability['contentScore'] += 3
    elif tag in ('address', 'ol', 'ul', 'dl', 'dd', 'dt', 'li', 'form'):
      node.readability['contentScore'] -= 3
    elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'th'):
      node.readability['contentScore'] -= 5

#    dbg("initializeNode1: %s (%s:%s): %d " % (node.name, node.get('class', ''), node.get('id', ''), node.readability['contentScore']))
    node.readability['contentScore'] += self.getClassWeight(node)
#    dbg("initializeNode2: %s (%s:%s): %d " % (node.name, node.get('class', ''), node.get('id', ''), node.readability['contentScore']))

  def getClassWeight(self, node):
    if not self._conf['weight_classes']:
      return 0
    
    weight = 0
    
    # Look for a special classname
    class_name = node.get('class')
    if class_name:
      if negativeRe.search(class_name):
        weight -= 25
      if positiveRe.search(class_name):
        weight += 25

    # Look for a special ID
    node_id = node.get('id')
    if node_id:
      if negativeRe.search(node_id):
        weight -= 25
      if positiveRe.search(node_id):
        weight += 25

    #dbg("get_class_weight: %s (%s:%s): %d" % (node.name, class_name, node_id, weight))
    return weight  

  def getInnerText(self, node, trimSpaces=True, normalizeSpaces=True):
    return get_inner_text(node, trimSpaces, normalizeSpaces)

  def _replace_element(self, soup, node, new_element):
    new_node = Tag(soup, new_element, attrs=node.attrs)
    for c in [c for c in node.contents]:
      new_node.append(c)
    node.replaceWith(new_node)

  def _find_base_url(self):
    if not self._url:
      dbg("[WARN] no content URI")
      return None
    parts = urlparse.urlsplit(self._url)
    noUrlParams = parts[2]
    urlSlashes = noUrlParams.split('/')
    urlSlashes.reverse()
    cleanedSegments = []
    possibleType = ""

    for idx, segment in enumerate(urlSlashes):
      # Split off and save anything that looks like a file type.
      dot_idx = segment.rfind('.')
      if  dot_idx > -1:
        possibleType = segment[dot_idx+1:]
        # If the type isn't alpha-only, it's probably not actually a file extension.
        if not possibleType.isalpha():
          segment = segment[:dot_idx]

      if segment.find(',00') > -1:
        segment = segment.replace(',00', '')

      # If our first or second segment has anything looking like a page number, remove it.
      if ((idx == 1) or (idx == 0)) and re.search('((_|-)?p[a-z]*|(_|-))[0-9]{1,2}$', segment, re.IGNORECASE):
        segment = re.sub('((_|-)?p[a-z]*|(_|-))[0-9]{1,2}$', '', segment, re.IGNORECASE)

      delete = False

      # If this is purely a number, and it's the first or second segment, it's probably a page number. Remove it.
      if idx < 2 and segment.isdigit():
        delete = True

      # If this is the first segment and it's just "index", remove it.
      if idx == 0 and segment.lower() == 'index':
        delete = True

      # If our first or second segment is smaller than 3 characters, and the first segment was purely alphas, remove it.
      if idx < 2 and len(segment) < 3 and (not urlSlashes[0].isalpha()):
        delete = True

      if not delete:
        cleanedSegments.append(segment)

    cleanedSegments.reverse()
    
    return "%s://%s%s" % (parts[0], parts[1], '/'.join(cleanedSegments))


  def _find_next_page_link(self):
    allLinks = self._osoup.findAll('a')
    articleBaseUrl = self._find_base_url()
    possible_pages = {}
    
    fragment_re = re.compile('#.*$')
    end_slash_re = re.compile('/$')
    paginate_re = re.compile('pag(e|ing|inat)', re.IGNORECASE)
    ext_paginate_re = re.compile('p(a|g|ag)?(e|ing|ination)?(=|\/)[0-9]{1,2}', re.IGNORECASE)
    firstLast_re = re.compile('(first|last)', re.IGNORECASE)

    if articleBaseUrl:
      bits = urlparse.urlsplit(articleBaseUrl)
      hostname = "%s://%s" % (bits[0], bits[1])
      rel_uri = self._url[:self._url.rfind('/')+1]

    for link in allLinks:
      linkHref = link.get('href')
      if not linkHref:
        continue
      linkHref = fragment_re.sub('', linkHref)
      linkHref = end_slash_re.sub('', linkHref)

      if not linkHref:
        continue

      # no it's time to work with full url-s
      if linkHref.startswith('http://') or linkHref.startswith('https//'):
        pass
      else:
        if not articleBaseUrl:
          dbg("_find_next_page_link:relative path cannot be used with no articleBaseUrl")
          continue
        if linkHref.startswith('/'):
          linkHref = hostname + linkHref
        else:
          linkHref = rel_uri + linkHref

      if (linkHref == articleBaseUrl) or (self._url and linkHref == self._url):
        continue

      # other domain
      if articleBaseUrl and not linkHref.startswith(hostname):
          continue

      linkText = self.getInnerText(link)

      if extraneousRe.search(linkText) or len(linkText) > 25:
        continue

      try:
        if articleBaseUrl:
          linkHrefLeftover = linkHref.replace(articleBaseUrl, '')
        else:
          linkHrefLeftover = linkHref
        if not re.search('\d', linkHrefLeftover):
          continue
      except TypeError:
        logging.exception("linkHref: '%s', articleBaseUrl: '%s'", linkHref, articleBaseUrl)

      if possible_pages.has_key(linkHref):
        possible_pages[linkHref]['linkText'] += ' | ' + linkText
      else:
        possible_pages[linkHref] = {'score': 0, 'linkText': linkText, 'href': linkHref}

      linkObj = possible_pages[linkHref]

      if articleBaseUrl and linkHref.find(articleBaseUrl) == -1:
          linkObj['score'] -= 25

      linkData = linkText + ' ' + link.get('class', '') + ' ' + link.get('id', '')
      if nextLinkRe.search(linkData):
          linkObj['score'] += 50

      if paginate_re.search(linkData):
        linkObj['score'] += 25

      if firstLast_re.search(linkData): #// -65 is enough to negate any bonuses gotten from a > or » in the text,
        # If we already matched on "next", last is probably fine. If we didn't, then it's bad. Penalize.
        if not nextLinkRe.search(linkObj['linkText']):
          linkObj['score'] -= 65

      if negativeRe.search(linkData) or extraneousRe.search(linkData):
        linkObj['score'] -= 50

      if prevLinkRe.search(linkData):
        linkObj['score'] -= 200


      # If a parentNode contains page or paging or paginat
      parentNode = link.parent
      positiveNodeMatch = False
      negativeNodeMatch = False
      while parentNode :
        parentNodeClassAndId = parentNode.get('class', '') + ' ' + parentNode.get('id', '')
        if (not positiveNodeMatch) and parentNodeClassAndId and paginate_re.search(parentNodeClassAndId):
          positiveNodeMatch = True
          linkObj['score'] += 25

        if (not negativeNodeMatch) and parentNodeClassAndId and negativeRe.search(parentNodeClassAndId):
          # If this is just something like "footer", give it a negative. If it's something like "body-and-footer", leave it be.
          if not positiveRe.search(parentNodeClassAndId):
            linkObj['score'] -= 25
            negativeNodeMatch = True

        parentNode = parentNode.parent


      # If the URL looks like it has paging in it, add to the score.
      # Things like /page/2/, /pagenum/2, ?p=3, ?page=11, ?pagination=34
      if paginate_re.search(linkHref) or ext_paginate_re.search(linkHref):
        linkObj['score'] += 25

      # If the URL contains negative values, give a slight decrease.
      if extraneousRe.search(linkHref):
        linkObj['score'] -= 15

      try:
        linkTextAsNumber = int(linkText)
        if linkTextAsNumber == 1:
          linkObj['score'] -= 10
        else:
          linkObj['score'] += max(0, 10 - linkTextAsNumber)
      except ValueError:
        pass

    # Loop thrugh all of our possible pages from above and find our top candidate for the next page URL.
    # Require at least a score of 50, which is a relatively high confidence that this page is the next link.
    continuation_pages = []
    for href, linkObj in possible_pages.items():
      if (linkObj['score'] >= 50):
        continuation_pages.append(linkObj)

    if continuation_pages:
      continuation_pages.sort(cmp=lambda x,y: y['score']-x['score'])
      dbg('NEXT PAGE IS:' + continuation_pages[0]['href'])
      return continuation_pages

    return []

  OUTPUT_BODY = """<html>
<body id='readabilityBody' class='%(read_style)s'>
<div id='readOverlay' class='%(read_style)s'>
  <div id='readInner' class='%(read_margin)s %(read_size)s'>
  </div>
</div>
</body>
</html>"""

def unescape(text):
  def fixup(m):
    text = m.group(0)
    if text[:2] == "&#":
        # character reference
        try:
            if text[:3] == "&#x":
                return unichr(int(text[3:-1], 16))
            else:
                return unichr(int(text[2:-1]))
        except ValueError:
            pass
    else:
        # named entity
        try:
            text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
        except KeyError:
            pass
    return text # leave as is
  return re.sub("&#?\w+;", fixup, text)    

def get_inner_text(node, trimSpaces=True, normalizeSpaces=True):
  if isinstance(node, (unicode, NavigableString)):
    textContent = node
  else:
    if len(node.contents) == 0:
        return u""
    strings = []
    for t in node.contents:
      strings.append(get_inner_text(t, trimSpaces, normalizeSpaces))
    textContent = u" ".join(strings)

  if trimSpaces:
    textContent = trimRe.sub('', textContent)
  if normalizeSpaces:
    textContent = normalizeRe.sub(' ', textContent)

  return textContent  

def clean_extraspaces(output):
  output = killBreaksRe.sub('<br />', output)
  output = killMoreBreaksRe.sub('<p', output)
  return output  
  



"""Beautiful Soup
Elixir and Tonic
"The Screen-Scraper's Friend"
http://www.crummy.com/software/BeautifulSoup/

Beautiful Soup parses a (possibly invalid) XML or HTML document into a
tree representation. It provides methods and Pythonic idioms that make
it easy to navigate, search, and modify the tree.

A well-formed XML/HTML document yields a well-formed data
structure. An ill-formed XML/HTML document yields a correspondingly
ill-formed data structure. If your document is only locally
well-formed, you can use this library to find and process the
well-formed part of it.

Beautiful Soup works with Python 2.2 and up. It has no external
dependencies, but you'll have more success at converting data to UTF-8
if you also install these three packages:

* chardet, for auto-detecting character encodings
  http://chardet.feedparser.org/
* cjkcodecs and iconv_codec, which add more encodings to the ones supported
  by stock Python.
  http://cjkpython.i18n.org/

Beautiful Soup defines classes for two main parsing strategies:

 * BeautifulStoneSoup, for parsing XML, SGML, or your domain-specific
   language that kind of looks like XML.

 * BeautifulSoup, for parsing run-of-the-mill HTML code, be it valid
   or invalid. This class has web browser-like heuristics for
   obtaining a sensible parse tree in the face of common HTML errors.

Beautiful Soup also defines a class (UnicodeDammit) for autodetecting
the encoding of an HTML or XML document, and converting it to
Unicode. Much of this code is taken from Mark Pilgrim's Universal Feed Parser.

For more than you ever wanted to know about Beautiful Soup, see the
documentation:
http://www.crummy.com/software/BeautifulSoup/documentation.html

Here, have some legalese:

Copyright (c) 2004-2010, Leonard Richardson

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above
    copyright notice, this list of conditions and the following
    disclaimer in the documentation and/or other materials provided
    with the distribution.

  * Neither the name of the the Beautiful Soup Consortium and All
    Night Kosher Bakery nor the names of its contributors may be
    used to endorse or promote products derived from this software
    without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE, DAMMIT.

"""

__author__ = "Leonard Richardson (leonardr@segfault.org)"
__version__ = "3.2.0"
__copyright__ = "Copyright (c) 2004-2010 Leonard Richardson"
__license__ = "New-style BSD"

from sgmllib import SGMLParser, SGMLParseError
import codecs
import markupbase
import types
import re
import sgmllib
try:
  from htmlentitydefs import name2codepoint
except ImportError:
  name2codepoint = {}
try:
    set
except NameError:
    from sets import Set as set

#These hacks make Beautiful Soup able to parse XML with namespaces
sgmllib.tagfind = re.compile('[a-zA-Z][-_.:a-zA-Z0-9]*')
markupbase._declname_match = re.compile(r'[a-zA-Z][-_.:a-zA-Z0-9]*\s*').match

DEFAULT_OUTPUT_ENCODING = "utf-8"

def _match_css_class(str):
    """Build a RE to match the given CSS class."""
    return re.compile(r"(^|.*\s)%s($|\s)" % str)

# First, the classes that represent markup elements.

class PageElement(object):
    """Contains the navigational information for some part of the page
    (either a tag or a piece of text)"""

    def setup(self, parent=None, previous=None):
        """Sets up the initial relations between this element and
        other elements."""
        self.parent = parent
        self.previous = previous
        self.next = None
        self.previousSibling = None
        self.nextSibling = None
        if self.parent and self.parent.contents:
            self.previousSibling = self.parent.contents[-1]
            self.previousSibling.nextSibling = self

    def replaceWith(self, replaceWith):
        oldParent = self.parent
        myIndex = self.parent.index(self)
        if hasattr(replaceWith, "parent")\
                  and replaceWith.parent is self.parent:
            # We're replacing this element with one of its siblings.
            index = replaceWith.parent.index(replaceWith)
            if index and index < myIndex:
                # Furthermore, it comes before this element. That
                # means that when we extract it, the index of this
                # element will change.
                myIndex = myIndex - 1
        self.extract()
        oldParent.insert(myIndex, replaceWith)

    def replaceWithChildren(self):
        myParent = self.parent
        myIndex = self.parent.index(self)
        self.extract()
        reversedChildren = list(self.contents)
        reversedChildren.reverse()
        for child in reversedChildren:
            myParent.insert(myIndex, child)

    def extract(self):
        """Destructively rips this element out of the tree."""
        if self.parent:
            try:
                del self.parent.contents[self.parent.index(self)]
            except ValueError:
                pass

        #Find the two elements that would be next to each other if
        #this element (and any children) hadn't been parsed. Connect
        #the two.
        lastChild = self._lastRecursiveChild()
        nextElement = lastChild.next

        if self.previous:
            self.previous.next = nextElement
        if nextElement:
            nextElement.previous = self.previous
        self.previous = None
        lastChild.next = None

        self.parent = None
        if self.previousSibling:
            self.previousSibling.nextSibling = self.nextSibling
        if self.nextSibling:
            self.nextSibling.previousSibling = self.previousSibling
        self.previousSibling = self.nextSibling = None
        return self

    def _lastRecursiveChild(self):
        "Finds the last element beneath this object to be parsed."
        lastChild = self
        while hasattr(lastChild, 'contents') and lastChild.contents:
            lastChild = lastChild.contents[-1]
        return lastChild

    def insert(self, position, newChild):
        if isinstance(newChild, basestring) \
            and not isinstance(newChild, NavigableString):
            newChild = NavigableString(newChild)

        position =  min(position, len(self.contents))
        if hasattr(newChild, 'parent') and newChild.parent is not None:
            # We're 'inserting' an element that's already one
            # of this object's children.
            if newChild.parent is self:
                index = self.index(newChild)
                if index > position:
                    # Furthermore we're moving it further down the
                    # list of this object's children. That means that
                    # when we extract this element, our target index
                    # will jump down one.
                    position = position - 1
            newChild.extract()

        newChild.parent = self
        previousChild = None
        if position == 0:
            newChild.previousSibling = None
            newChild.previous = self
        else:
            previousChild = self.contents[position-1]
            newChild.previousSibling = previousChild
            newChild.previousSibling.nextSibling = newChild
            newChild.previous = previousChild._lastRecursiveChild()
        if newChild.previous:
            newChild.previous.next = newChild

        newChildsLastElement = newChild._lastRecursiveChild()

        if position >= len(self.contents):
            newChild.nextSibling = None

            parent = self
            parentsNextSibling = None
            while not parentsNextSibling:
                parentsNextSibling = parent.nextSibling
                parent = parent.parent
                if not parent: # This is the last element in the document.
                    break
            if parentsNextSibling:
                newChildsLastElement.next = parentsNextSibling
            else:
                newChildsLastElement.next = None
        else:
            nextChild = self.contents[position]
            newChild.nextSibling = nextChild
            if newChild.nextSibling:
                newChild.nextSibling.previousSibling = newChild
            newChildsLastElement.next = nextChild

        if newChildsLastElement.next:
            newChildsLastElement.next.previous = newChildsLastElement
        self.contents.insert(position, newChild)

    def append(self, tag):
        """Appends the given tag to the contents of this tag."""
        self.insert(len(self.contents), tag)

    def findNext(self, name=None, attrs={}, text=None, **kwargs):
        """Returns the first item that matches the given criteria and
        appears after this Tag in the document."""
        return self._findOne(self.findAllNext, name, attrs, text, **kwargs)

    def findAllNext(self, name=None, attrs={}, text=None, limit=None,
                    **kwargs):
        """Returns all items that match the given criteria and appear
        after this Tag in the document."""
        return self._findAll(name, attrs, text, limit, self.nextGenerator,
                             **kwargs)

    def findNextSibling(self, name=None, attrs={}, text=None, **kwargs):
        """Returns the closest sibling to this Tag that matches the
        given criteria and appears after this Tag in the document."""
        return self._findOne(self.findNextSiblings, name, attrs, text,
                             **kwargs)

    def findNextSiblings(self, name=None, attrs={}, text=None, limit=None,
                         **kwargs):
        """Returns the siblings of this Tag that match the given
        criteria and appear after this Tag in the document."""
        return self._findAll(name, attrs, text, limit,
                             self.nextSiblingGenerator, **kwargs)
    fetchNextSiblings = findNextSiblings # Compatibility with pre-3.x

    def findPrevious(self, name=None, attrs={}, text=None, **kwargs):
        """Returns the first item that matches the given criteria and
        appears before this Tag in the document."""
        return self._findOne(self.findAllPrevious, name, attrs, text, **kwargs)

    def findAllPrevious(self, name=None, attrs={}, text=None, limit=None,
                        **kwargs):
        """Returns all items that match the given criteria and appear
        before this Tag in the document."""
        return self._findAll(name, attrs, text, limit, self.previousGenerator,
                           **kwargs)
    fetchPrevious = findAllPrevious # Compatibility with pre-3.x

    def findPreviousSibling(self, name=None, attrs={}, text=None, **kwargs):
        """Returns the closest sibling to this Tag that matches the
        given criteria and appears before this Tag in the document."""
        return self._findOne(self.findPreviousSiblings, name, attrs, text,
                             **kwargs)

    def findPreviousSiblings(self, name=None, attrs={}, text=None,
                             limit=None, **kwargs):
        """Returns the siblings of this Tag that match the given
        criteria and appear before this Tag in the document."""
        return self._findAll(name, attrs, text, limit,
                             self.previousSiblingGenerator, **kwargs)
    fetchPreviousSiblings = findPreviousSiblings # Compatibility with pre-3.x

    def findParent(self, name=None, attrs={}, **kwargs):
        """Returns the closest parent of this Tag that matches the given
        criteria."""
        # NOTE: We can't use _findOne because findParents takes a different
        # set of arguments.
        r = None
        l = self.findParents(name, attrs, 1)
        if l:
            r = l[0]
        return r

    def findParents(self, name=None, attrs={}, limit=None, **kwargs):
        """Returns the parents of this Tag that match the given
        criteria."""

        return self._findAll(name, attrs, None, limit, self.parentGenerator,
                             **kwargs)
    fetchParents = findParents # Compatibility with pre-3.x

    #These methods do the real heavy lifting.

    def _findOne(self, method, name, attrs, text, **kwargs):
        r = None
        l = method(name, attrs, text, 1, **kwargs)
        if l:
            r = l[0]
        return r

    def _findAll(self, name, attrs, text, limit, generator, **kwargs):
        "Iterates over a generator looking for things that match."

        if isinstance(name, SoupStrainer):
            strainer = name
        # (Possibly) special case some findAll*(...) searches
        elif text is None and not limit and not attrs and not kwargs:
            # findAll*(True)
            if name is True:
                return [element for element in generator()
                        if isinstance(element, Tag)]
            # findAll*('tag-name')
            elif isinstance(name, basestring):
                return [element for element in generator()
                        if isinstance(element, Tag) and
                        element.name == name]
            else:
                strainer = SoupStrainer(name, attrs, text, **kwargs)
        # Build a SoupStrainer
        else:
            strainer = SoupStrainer(name, attrs, text, **kwargs)
        results = ResultSet(strainer)
        g = generator()
        while True:
            try:
                i = g.next()
            except StopIteration:
                break
            if i:
                found = strainer.search(i)
                if found:
                    results.append(found)
                    if limit and len(results) >= limit:
                        break
        return results

    #These Generators can be used to navigate starting from both
    #NavigableStrings and Tags.
    def nextGenerator(self):
        i = self
        while i is not None:
            i = i.next
            yield i

    def nextSiblingGenerator(self):
        i = self
        while i is not None:
            i = i.nextSibling
            yield i

    def previousGenerator(self):
        i = self
        while i is not None:
            i = i.previous
            yield i

    def previousSiblingGenerator(self):
        i = self
        while i is not None:
            i = i.previousSibling
            yield i

    def parentGenerator(self):
        i = self
        while i is not None:
            i = i.parent
            yield i

    # Utility methods
    def substituteEncoding(self, str, encoding=None):
        encoding = encoding or "utf-8"
        return str.replace("%SOUP-ENCODING%", encoding)

    def toEncoding(self, s, encoding=None):
        """Encodes an object to a string in some encoding, or to Unicode.
        ."""
        if isinstance(s, unicode):
            if encoding:
                s = s.encode(encoding)
        elif isinstance(s, str):
            if encoding:
                s = s.encode(encoding)
            else:
                s = unicode(s)
        else:
            if encoding:
                s  = self.toEncoding(str(s), encoding)
            else:
                s = unicode(s)
        return s

class NavigableString(unicode, PageElement):

    def __new__(cls, value):
        """Create a new NavigableString.

        When unpickling a NavigableString, this method is called with
        the string in DEFAULT_OUTPUT_ENCODING. That encoding needs to be
        passed in to the superclass's __new__ or the superclass won't know
        how to handle non-ASCII characters.
        """
        if isinstance(value, unicode):
            return unicode.__new__(cls, value)
        return unicode.__new__(cls, value, DEFAULT_OUTPUT_ENCODING)

    def __getnewargs__(self):
        return (NavigableString.__str__(self),)

    def __getattr__(self, attr):
        """text.string gives you text. This is for backwards
        compatibility for Navigable*String, but for CData* it lets you
        get the string without the CData wrapper."""
        if attr == 'string':
            return self
        else:
            raise AttributeError, "'%s' object has no attribute '%s'" % (self.__class__.__name__, attr)

    def __unicode__(self):
        return str(self).decode(DEFAULT_OUTPUT_ENCODING)

    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):
        if encoding:
            return self.encode(encoding)
        else:
            return self

class CData(NavigableString):

    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):
        return "<![CDATA[%s]]>" % NavigableString.__str__(self, encoding)

class ProcessingInstruction(NavigableString):
    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):
        output = self
        if "%SOUP-ENCODING%" in output:
            output = self.substituteEncoding(output, encoding)
        return "<?%s?>" % self.toEncoding(output, encoding)

class Comment(NavigableString):
    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):
        return "<!--%s-->" % NavigableString.__str__(self, encoding)

class Declaration(NavigableString):
    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING):
        return "<!%s>" % NavigableString.__str__(self, encoding)

class Tag(PageElement):

    """Represents a found HTML tag with its attributes and contents."""

    def _invert(h):
        "Cheap function to invert a hash."
        i = {}
        for k,v in h.items():
            i[v] = k
        return i

    XML_ENTITIES_TO_SPECIAL_CHARS = { "apos" : "'",
                                      "quot" : '"',
                                      "amp" : "&",
                                      "lt" : "<",
                                      "gt" : ">" }

    XML_SPECIAL_CHARS_TO_ENTITIES = _invert(XML_ENTITIES_TO_SPECIAL_CHARS)

    def _convertEntities(self, match):
        """Used in a call to re.sub to replace HTML, XML, and numeric
        entities with the appropriate Unicode characters. If HTML
        entities are being converted, any unrecognized entities are
        escaped."""
        x = match.group(1)
        if self.convertHTMLEntities and x in name2codepoint:
            return unichr(name2codepoint[x])
        elif x in self.XML_ENTITIES_TO_SPECIAL_CHARS:
            if self.convertXMLEntities:
                return self.XML_ENTITIES_TO_SPECIAL_CHARS[x]
            else:
                return u'&%s;' % x
        elif len(x) > 0 and x[0] == '#':
            # Handle numeric entities
            if len(x) > 1 and x[1] == 'x':
                return unichr(int(x[2:], 16))
            else:
                return unichr(int(x[1:]))

        elif self.escapeUnrecognizedEntities:
            return u'&amp;%s;' % x
        else:
            return u'&%s;' % x

    def __init__(self, parser, name, attrs=None, parent=None,
                 previous=None):
        "Basic constructor."

        # We don't actually store the parser object: that lets extracted
        # chunks be garbage-collected
        self.parserClass = parser.__class__
        self.isSelfClosing = parser.isSelfClosingTag(name)
        self.name = name
        if attrs is None:
            attrs = []
        elif isinstance(attrs, dict):
            attrs = attrs.items()
        self.attrs = attrs
        self.contents = []
        self.setup(parent, previous)
        self.hidden = False
        self.containsSubstitutions = False
        self.convertHTMLEntities = parser.convertHTMLEntities
        self.convertXMLEntities = parser.convertXMLEntities
        self.escapeUnrecognizedEntities = parser.escapeUnrecognizedEntities

        # Convert any HTML, XML, or numeric entities in the attribute values.
        convert = lambda(k, val): (k,
                                   re.sub("&(#\d+|#x[0-9a-fA-F]+|\w+);",
                                          self._convertEntities,
                                          val))
        self.attrs = map(convert, self.attrs)

    def getString(self):
        if (len(self.contents) == 1
            and isinstance(self.contents[0], NavigableString)):
            return self.contents[0]

    def setString(self, string):
        """Replace the contents of the tag with a string"""
        self.clear()
        self.append(string)

    string = property(getString, setString)

    def getText(self, separator=u""):
        if not len(self.contents):
            return u""
        stopNode = self._lastRecursiveChild().next
        strings = []
        current = self.contents[0]
        while current is not stopNode:
            if isinstance(current, NavigableString):
                strings.append(current.strip())
            current = current.next
        return separator.join(strings)

    text = property(getText)

    def get(self, key, default=None):
        """Returns the value of the 'key' attribute for the tag, or
        the value given for 'default' if it doesn't have that
        attribute."""
        return self._getAttrMap().get(key, default)

    def clear(self):
        """Extract all children."""
        for child in self.contents[:]:
            child.extract()

    def index(self, element):
        for i, child in enumerate(self.contents):
            if child is element:
                return i
        raise ValueError("Tag.index: element not in tag")

    def has_key(self, key):
        return self._getAttrMap().has_key(key)

    def __getitem__(self, key):
        """tag[key] returns the value of the 'key' attribute for the tag,
        and throws an exception if it's not there."""
        return self._getAttrMap()[key]

    def __iter__(self):
        "Iterating over a tag iterates over its contents."
        return iter(self.contents)

    def __len__(self):
        "The length of a tag is the length of its list of contents."
        return len(self.contents)

    def __contains__(self, x):
        return x in self.contents

    def __nonzero__(self):
        "A tag is non-None even if it has no contents."
        return True

    def __setitem__(self, key, value):
        """Setting tag[key] sets the value of the 'key' attribute for the
        tag."""
        self._getAttrMap()
        self.attrMap[key] = value
        found = False
        for i in range(0, len(self.attrs)):
            if self.attrs[i][0] == key:
                self.attrs[i] = (key, value)
                found = True
        if not found:
            self.attrs.append((key, value))
        self._getAttrMap()[key] = value

    def __delitem__(self, key):
        "Deleting tag[key] deletes all 'key' attributes for the tag."
        for item in self.attrs:
            if item[0] == key:
                self.attrs.remove(item)
                #We don't break because bad HTML can define the same
                #attribute multiple times.
            self._getAttrMap()
            if self.attrMap.has_key(key):
                del self.attrMap[key]

    def __call__(self, *args, **kwargs):
        """Calling a tag like a function is the same as calling its
        findAll() method. Eg. tag('a') returns a list of all the A tags
        found within this tag."""
        return apply(self.findAll, args, kwargs)

    def __getattr__(self, tag):
        #print "Getattr %s.%s" % (self.__class__, tag)
        if len(tag) > 3 and tag.rfind('Tag') == len(tag)-3:
            return self.find(tag[:-3])
        elif tag.find('__') != 0:
            return self.find(tag)
        raise AttributeError, "'%s' object has no attribute '%s'" % (self.__class__, tag)

    def __eq__(self, other):
        """Returns true iff this tag has the same name, the same attributes,
        and the same contents (recursively) as the given tag.

        NOTE: right now this will return false if two tags have the
        same attributes in a different order. Should this be fixed?"""
        if other is self:
            return True
        if not hasattr(other, 'name') or not hasattr(other, 'attrs') or not hasattr(other, 'contents') or self.name != other.name or self.attrs != other.attrs or len(self) != len(other):
            return False
        for i in range(0, len(self.contents)):
            if self.contents[i] != other.contents[i]:
                return False
        return True

    def __ne__(self, other):
        """Returns true iff this tag is not identical to the other tag,
        as defined in __eq__."""
        return not self == other

    def __repr__(self, encoding=DEFAULT_OUTPUT_ENCODING):
        """Renders this tag as a string."""
        return self.__str__(encoding)

    def __unicode__(self):
        return self.__str__(None)

    BARE_AMPERSAND_OR_BRACKET = re.compile("([<>]|"
                                           + "&(?!#\d+;|#x[0-9a-fA-F]+;|\w+;)"
                                           + ")")

    def _sub_entity(self, x):
        """Used with a regular expression to substitute the
        appropriate XML entity for an XML special character."""
        return "&" + self.XML_SPECIAL_CHARS_TO_ENTITIES[x.group(0)[0]] + ";"

    def __str__(self, encoding=DEFAULT_OUTPUT_ENCODING,
                prettyPrint=False, indentLevel=0):
        """Returns a string or Unicode representation of this tag and
        its contents. To get Unicode, pass None for encoding.

        NOTE: since Python's HTML parser consumes whitespace, this
        method is not certain to reproduce the whitespace present in
        the original string."""

        encodedName = self.toEncoding(self.name, encoding)

        attrs = []
        if self.attrs:
            for key, val in self.attrs:
                fmt = '%s="%s"'
                if isinstance(val, basestring):
                    if self.containsSubstitutions and '%SOUP-ENCODING%' in val:
                        val = self.substituteEncoding(val, encoding)

                    # The attribute value either:
                    #
                    # * Contains no embedded double quotes or single quotes.
                    #   No problem: we enclose it in double quotes.
                    # * Contains embedded single quotes. No problem:
                    #   double quotes work here too.
                    # * Contains embedded double quotes. No problem:
                    #   we enclose it in single quotes.
                    # * Embeds both single _and_ double quotes. This
                    #   can't happen naturally, but it can happen if
                    #   you modify an attribute value after parsing
                    #   the document. Now we have a bit of a
                    #   problem. We solve it by enclosing the
                    #   attribute in single quotes, and escaping any
                    #   embedded single quotes to XML entities.
                    if '"' in val:
                        fmt = "%s='%s'"
                        if "'" in val:
                            # TODO: replace with apos when
                            # appropriate.
                            val = val.replace("'", "&squot;")

                    # Now we're okay w/r/t quotes. But the attribute
                    # value might also contain angle brackets, or
                    # ampersands that aren't part of entities. We need
                    # to escape those to XML entities too.
                    val = self.BARE_AMPERSAND_OR_BRACKET.sub(self._sub_entity, val)

                attrs.append(fmt % (self.toEncoding(key, encoding),
                                    self.toEncoding(val, encoding)))
        close = ''
        closeTag = ''
        if self.isSelfClosing:
            close = ' /'
        else:
            closeTag = '</%s>' % encodedName

        indentTag, indentContents = 0, 0
        if prettyPrint:
            indentTag = indentLevel
            space = (' ' * (indentTag-1))
            indentContents = indentTag + 1
        contents = self.renderContents(encoding, prettyPrint, indentContents)
        if self.hidden:
            s = contents
        else:
            s = []
            attributeString = ''
            if attrs:
                attributeString = ' ' + ' '.join(attrs)
            if prettyPrint:
                s.append(space)
            s.append('<%s%s%s>' % (encodedName, attributeString, close))
            if prettyPrint:
                s.append("\n")
            s.append(contents)
            if prettyPrint and contents and contents[-1] != "\n":
                s.append("\n")
            if prettyPrint and closeTag:
                s.append(space)
            s.append(closeTag)
            if prettyPrint and closeTag and self.nextSibling:
                s.append("\n")
            s = ''.join(s)
        return s

    def decompose(self):
        """Recursively destroys the contents of this tree."""
        self.extract()
        if len(self.contents) == 0:
            return
        current = self.contents[0]
        while current is not None:
            next = current.next
            if isinstance(current, Tag):
                del current.contents[:]
            current.parent = None
            current.previous = None
            current.previousSibling = None
            current.next = None
            current.nextSibling = None
            current = next

    def prettify(self, encoding=DEFAULT_OUTPUT_ENCODING):
        return self.__str__(encoding, True)

    def renderContents(self, encoding=DEFAULT_OUTPUT_ENCODING,
                       prettyPrint=False, indentLevel=0):
        """Renders the contents of this tag as a string in the given
        encoding. If encoding is None, returns a Unicode string.."""
        s=[]
        for c in self:
            text = None
            if isinstance(c, NavigableString):
                text = c.__str__(encoding)
            elif isinstance(c, Tag):
                s.append(c.__str__(encoding, prettyPrint, indentLevel))
            if text and prettyPrint:
                text = text.strip()
            if text:
                if prettyPrint:
                    s.append(" " * (indentLevel-1))
                s.append(text)
                if prettyPrint:
                    s.append("\n")
        return ''.join(s)

    #Soup methods

    def find(self, name=None, attrs={}, recursive=True, text=None,
             **kwargs):
        """Return only the first child of this Tag matching the given
        criteria."""
        r = None
        l = self.findAll(name, attrs, recursive, text, 1, **kwargs)
        if l:
            r = l[0]
        return r
    findChild = find

    def findAll(self, name=None, attrs={}, recursive=True, text=None,
                limit=None, **kwargs):
        """Extracts a list of Tag objects that match the given
        criteria.  You can specify the name of the Tag and any
        attributes you want the Tag to have.

        The value of a key-value pair in the 'attrs' map can be a
        string, a list of strings, a regular expression object, or a
        callable that takes a string and returns whether or not the
        string matches for some custom definition of 'matches'. The
        same is true of the tag name."""
        generator = self.recursiveChildGenerator
        if not recursive:
            generator = self.childGenerator
        return self._findAll(name, attrs, text, limit, generator, **kwargs)
    findChildren = findAll

    # Pre-3.x compatibility methods
    first = find
    fetch = findAll

    def fetchText(self, text=None, recursive=True, limit=None):
        return self.findAll(text=text, recursive=recursive, limit=limit)

    def firstText(self, text=None, recursive=True):
        return self.find(text=text, recursive=recursive)

    #Private methods

    def _getAttrMap(self):
        """Initializes a map representation of this tag's attributes,
        if not already initialized."""
        if not getattr(self, 'attrMap'):
            self.attrMap = {}
            for (key, value) in self.attrs:
                self.attrMap[key] = value
        return self.attrMap

    #Generator methods
    def childGenerator(self):
        # Just use the iterator from the contents
        return iter(self.contents)

    def recursiveChildGenerator(self):
        if not len(self.contents):
            raise StopIteration
        stopNode = self._lastRecursiveChild().next
        current = self.contents[0]
        while current is not stopNode:
            yield current
            current = current.next


# Next, a couple classes to represent queries and their results.
class SoupStrainer:
    """Encapsulates a number of ways of matching a markup element (tag or
    text)."""

    def __init__(self, name=None, attrs={}, text=None, **kwargs):
        self.name = name
        if isinstance(attrs, basestring):
            kwargs['class'] = _match_css_class(attrs)
            attrs = None
        if kwargs:
            if attrs:
                attrs = attrs.copy()
                attrs.update(kwargs)
            else:
                attrs = kwargs
        self.attrs = attrs
        self.text = text

    def __str__(self):
        if self.text:
            return self.text
        else:
            return "%s|%s" % (self.name, self.attrs)

    def searchTag(self, markupName=None, markupAttrs={}):
        found = None
        markup = None
        if isinstance(markupName, Tag):
            markup = markupName
            markupAttrs = markup
        callFunctionWithTagData = callable(self.name) \
                                and not isinstance(markupName, Tag)

        if (not self.name) \
               or callFunctionWithTagData \
               or (markup and self._matches(markup, self.name)) \
               or (not markup and self._matches(markupName, self.name)):
            if callFunctionWithTagData:
                match = self.name(markupName, markupAttrs)
            else:
                match = True
                markupAttrMap = None
                for attr, matchAgainst in self.attrs.items():
                    if not markupAttrMap:
                         if hasattr(markupAttrs, 'get'):
                            markupAttrMap = markupAttrs
                         else:
                            markupAttrMap = {}
                            for k,v in markupAttrs:
                                markupAttrMap[k] = v
                    attrValue = markupAttrMap.get(attr)
                    if not self._matches(attrValue, matchAgainst):
                        match = False
                        break
            if match:
                if markup:
                    found = markup
                else:
                    found = markupName
        return found

    def search(self, markup):
        #print 'looking for %s in %s' % (self, markup)
        found = None
        # If given a list of items, scan it for a text element that
        # matches.
        if hasattr(markup, "__iter__") \
                and not isinstance(markup, Tag):
            for element in markup:
                if isinstance(element, NavigableString) \
                       and self.search(element):
                    found = element
                    break
        # If it's a Tag, make sure its name or attributes match.
        # Don't bother with Tags if we're searching for text.
        elif isinstance(markup, Tag):
            if not self.text:
                found = self.searchTag(markup)
        # If it's text, make sure the text matches.
        elif isinstance(markup, NavigableString) or \
                 isinstance(markup, basestring):
            if self._matches(markup, self.text):
                found = markup
        else:
            raise Exception, "I don't know how to match against a %s" \
                  % markup.__class__
        return found

    def _matches(self, markup, matchAgainst):
        #print "Matching %s against %s" % (markup, matchAgainst)
        result = False
        if matchAgainst is True:
            result = markup is not None
        elif callable(matchAgainst):
            result = matchAgainst(markup)
        else:
            #Custom match methods take the tag as an argument, but all
            #other ways of matching match the tag name as a string.
            if isinstance(markup, Tag):
                markup = markup.name
            if markup and not isinstance(markup, basestring):
                markup = unicode(markup)
            #Now we know that chunk is either a string, or None.
            if hasattr(matchAgainst, 'match'):
                # It's a regexp object.
                result = markup and matchAgainst.search(markup)
            elif hasattr(matchAgainst, '__iter__'): # list-like
                result = markup in matchAgainst
            elif hasattr(matchAgainst, 'items'):
                result = markup.has_key(matchAgainst)
            elif matchAgainst and isinstance(markup, basestring):
                if isinstance(markup, unicode):
                    matchAgainst = unicode(matchAgainst)
                else:
                    matchAgainst = str(matchAgainst)

            if not result:
                result = matchAgainst == markup
        return result

class ResultSet(list):
    """A ResultSet is just a list that keeps track of the SoupStrainer
    that created it."""
    def __init__(self, source):
        list.__init__([])
        self.source = source

# Now, some helper functions.

def buildTagMap(default, *args):
    """Turns a list of maps, lists, or scalars into a single map.
    Used to build the SELF_CLOSING_TAGS, NESTABLE_TAGS, and
    NESTING_RESET_TAGS maps out of lists and partial maps."""
    built = {}
    for portion in args:
        if hasattr(portion, 'items'):
            #It's a map. Merge it.
            for k,v in portion.items():
                built[k] = v
        elif hasattr(portion, '__iter__'): # is a list
            #It's a list. Map each item to the default.
            for k in portion:
                built[k] = default
        else:
            #It's a scalar. Map it to the default.
            built[portion] = default
    return built

# Now, the parser classes.

class BeautifulStoneSoup(Tag, SGMLParser):

    """This class contains the basic parser and search code. It defines
    a parser that knows nothing about tag behavior except for the
    following:

      You can't close a tag without closing all the tags it encloses.
      That is, "<foo><bar></foo>" actually means
      "<foo><bar></bar></foo>".

    [Another possible explanation is "<foo><bar /></foo>", but since
    this class defines no SELF_CLOSING_TAGS, it will never use that
    explanation.]

    This class is useful for parsing XML or made-up markup languages,
    or when BeautifulSoup makes an assumption counter to what you were
    expecting."""

    SELF_CLOSING_TAGS = {}
    NESTABLE_TAGS = {}
    RESET_NESTING_TAGS = {}
    QUOTE_TAGS = {}
    PRESERVE_WHITESPACE_TAGS = []

    MARKUP_MASSAGE = [(re.compile('(<[^<>]*)/>'),
                       lambda x: x.group(1) + ' />'),
                      (re.compile('<!\s+([^<>]*)>'),
                       lambda x: '<!' + x.group(1) + '>')
                      ]

    ROOT_TAG_NAME = u'[document]'

    HTML_ENTITIES = "html"
    XML_ENTITIES = "xml"
    XHTML_ENTITIES = "xhtml"
    # TODO: This only exists for backwards-compatibility
    ALL_ENTITIES = XHTML_ENTITIES

    # Used when determining whether a text node is all whitespace and
    # can be replaced with a single space. A text node that contains
    # fancy Unicode spaces (usually non-breaking) should be left
    # alone.
    STRIP_ASCII_SPACES = { 9: None, 10: None, 12: None, 13: None, 32: None, }

    def __init__(self, markup="", parseOnlyThese=None, fromEncoding=None,
                 markupMassage=True, smartQuotesTo=XML_ENTITIES,
                 convertEntities=None, selfClosingTags=None, isHTML=False):
        """The Soup object is initialized as the 'root tag', and the
        provided markup (which can be a string or a file-like object)
        is fed into the underlying parser.

        sgmllib will process most bad HTML, and the BeautifulSoup
        class has some tricks for dealing with some HTML that kills
        sgmllib, but Beautiful Soup can nonetheless choke or lose data
        if your data uses self-closing tags or declarations
        incorrectly.

        By default, Beautiful Soup uses regexes to sanitize input,
        avoiding the vast majority of these problems. If the problems
        don't apply to you, pass in False for markupMassage, and
        you'll get better performance.

        The default parser massage techniques fix the two most common
        instances of invalid HTML that choke sgmllib:

         <br/> (No space between name of closing tag and tag close)
         <! --Comment--> (Extraneous whitespace in declaration)

        You can pass in a custom list of (RE object, replace method)
        tuples to get Beautiful Soup to scrub your input the way you
        want."""

        self.parseOnlyThese = parseOnlyThese
        self.fromEncoding = fromEncoding
        self.smartQuotesTo = smartQuotesTo
        self.convertEntities = convertEntities
        # Set the rules for how we'll deal with the entities we
        # encounter
        if self.convertEntities:
            # It doesn't make sense to convert encoded characters to
            # entities even while you're converting entities to Unicode.
            # Just convert it all to Unicode.
            self.smartQuotesTo = None
            if convertEntities == self.HTML_ENTITIES:
                self.convertXMLEntities = False
                self.convertHTMLEntities = True
                self.escapeUnrecognizedEntities = True
            elif convertEntities == self.XHTML_ENTITIES:
                self.convertXMLEntities = True
                self.convertHTMLEntities = True
                self.escapeUnrecognizedEntities = False
            elif convertEntities == self.XML_ENTITIES:
                self.convertXMLEntities = True
                self.convertHTMLEntities = False
                self.escapeUnrecognizedEntities = False
        else:
            self.convertXMLEntities = False
            self.convertHTMLEntities = False
            self.escapeUnrecognizedEntities = False

        self.instanceSelfClosingTags = buildTagMap(None, selfClosingTags)
        SGMLParser.__init__(self)

        if hasattr(markup, 'read'):        # It's a file-type object.
            markup = markup.read()
        self.markup = markup
        self.markupMassage = markupMassage
        try:
            self._feed(isHTML=isHTML)
        except StopParsing:
            pass
        self.markup = None                 # The markup can now be GCed

    def convert_charref(self, name):
        """This method fixes a bug in Python's SGMLParser."""
        try:
            n = int(name)
        except ValueError:
            return
        if not 0 <= n <= 127 : # ASCII ends at 127, not 255
            return
        return self.convert_codepoint(n)

    def _feed(self, inDocumentEncoding=None, isHTML=False):
        # Convert the document to Unicode.
        markup = self.markup
        if isinstance(markup, unicode):
            if not hasattr(self, 'originalEncoding'):
                self.originalEncoding = None
        else:
            dammit = UnicodeDammit\
                     (markup, [self.fromEncoding, inDocumentEncoding],
                      smartQuotesTo=self.smartQuotesTo, isHTML=isHTML)
            markup = dammit.unicode
            self.originalEncoding = dammit.originalEncoding
            self.declaredHTMLEncoding = dammit.declaredHTMLEncoding
        if markup:
            if self.markupMassage:
                if not hasattr(self.markupMassage, "__iter__"):
                    self.markupMassage = self.MARKUP_MASSAGE
                for fix, m in self.markupMassage:
                    markup = fix.sub(m, markup)
                # TODO: We get rid of markupMassage so that the
                # soup object can be deepcopied later on. Some
                # Python installations can't copy regexes. If anyone
                # was relying on the existence of markupMassage, this
                # might cause problems.
                del(self.markupMassage)
        self.reset()

        SGMLParser.feed(self, markup)
        # Close out any unfinished strings and close all the open tags.
        self.endData()
        while self.currentTag.name != self.ROOT_TAG_NAME:
            self.popTag()

    def __getattr__(self, methodName):
        """This method routes method call requests to either the SGMLParser
        superclass or the Tag superclass, depending on the method name."""
        #print "__getattr__ called on %s.%s" % (self.__class__, methodName)

        if methodName.startswith('start_') or methodName.startswith('end_') \
               or methodName.startswith('do_'):
            return SGMLParser.__getattr__(self, methodName)
        elif not methodName.startswith('__'):
            return Tag.__getattr__(self, methodName)
        else:
            raise AttributeError

    def isSelfClosingTag(self, name):
        """Returns true iff the given string is the name of a
        self-closing tag according to this parser."""
        return self.SELF_CLOSING_TAGS.has_key(name) \
               or self.instanceSelfClosingTags.has_key(name)

    def reset(self):
        Tag.__init__(self, self, self.ROOT_TAG_NAME)
        self.hidden = 1
        SGMLParser.reset(self)
        self.currentData = []
        self.currentTag = None
        self.tagStack = []
        self.quoteStack = []
        self.pushTag(self)

    def popTag(self):
        tag = self.tagStack.pop()

        #print "Pop", tag.name
        if self.tagStack:
            self.currentTag = self.tagStack[-1]
        return self.currentTag

    def pushTag(self, tag):
        #print "Push", tag.name
        if self.currentTag:
            self.currentTag.contents.append(tag)
        self.tagStack.append(tag)
        self.currentTag = self.tagStack[-1]

    def endData(self, containerClass=NavigableString):
        if self.currentData:
            currentData = u''.join(self.currentData)
            if (currentData.translate(self.STRIP_ASCII_SPACES) == '' and
                not set([tag.name for tag in self.tagStack]).intersection(
                    self.PRESERVE_WHITESPACE_TAGS)):
                if '\n' in currentData:
                    currentData = '\n'
                else:
                    currentData = ' '
            self.currentData = []
            if self.parseOnlyThese and len(self.tagStack) <= 1 and \
                   (not self.parseOnlyThese.text or \
                    not self.parseOnlyThese.search(currentData)):
                return
            o = containerClass(currentData)
            o.setup(self.currentTag, self.previous)
            if self.previous:
                self.previous.next = o
            self.previous = o
            self.currentTag.contents.append(o)


    def _popToTag(self, name, inclusivePop=True):
        """Pops the tag stack up to and including the most recent
        instance of the given tag. If inclusivePop is false, pops the tag
        stack up to but *not* including the most recent instqance of
        the given tag."""
        #print "Popping to %s" % name
        if name == self.ROOT_TAG_NAME:
            return

        numPops = 0
        mostRecentTag = None
        for i in range(len(self.tagStack)-1, 0, -1):
            if name == self.tagStack[i].name:
                numPops = len(self.tagStack)-i
                break
        if not inclusivePop:
            numPops = numPops - 1

        for i in range(0, numPops):
            mostRecentTag = self.popTag()
        return mostRecentTag

    def _smartPop(self, name):

        """We need to pop up to the previous tag of this type, unless
        one of this tag's nesting reset triggers comes between this
        tag and the previous tag of this type, OR unless this tag is a
        generic nesting trigger and another generic nesting trigger
        comes between this tag and the previous tag of this type.

        Examples:
         <p>Foo<b>Bar *<p>* should pop to 'p', not 'b'.
         <p>Foo<table>Bar *<p>* should pop to 'table', not 'p'.
         <p>Foo<table><tr>Bar *<p>* should pop to 'tr', not 'p'.

         <li><ul><li> *<li>* should pop to 'ul', not the first 'li'.
         <tr><table><tr> *<tr>* should pop to 'table', not the first 'tr'
         <td><tr><td> *<td>* should pop to 'tr', not the first 'td'
        """

        nestingResetTriggers = self.NESTABLE_TAGS.get(name)
        isNestable = nestingResetTriggers != None
        isResetNesting = self.RESET_NESTING_TAGS.has_key(name)
        popTo = None
        inclusive = True
        for i in range(len(self.tagStack)-1, 0, -1):
            p = self.tagStack[i]
            if (not p or p.name == name) and not isNestable:
                #Non-nestable tags get popped to the top or to their
                #last occurance.
                popTo = name
                break
            if (nestingResetTriggers is not None
                and p.name in nestingResetTriggers) \
                or (nestingResetTriggers is None and isResetNesting
                    and self.RESET_NESTING_TAGS.has_key(p.name)):

                #If we encounter one of the nesting reset triggers
                #peculiar to this tag, or we encounter another tag
                #that causes nesting to reset, pop up to but not
                #including that tag.
                popTo = p.name
                inclusive = False
                break
            p = p.parent
        if popTo:
            self._popToTag(popTo, inclusive)

    def unknown_starttag(self, name, attrs, selfClosing=0):
        #print "Start tag %s: %s" % (name, attrs)
        if self.quoteStack:
            #This is not a real tag.
            #print "<%s> is not real!" % name
            attrs = ''.join([' %s="%s"' % (x, y) for x, y in attrs])
            self.handle_data('<%s%s>' % (name, attrs))
            return
        self.endData()

        if not self.isSelfClosingTag(name) and not selfClosing:
            self._smartPop(name)

        if self.parseOnlyThese and len(self.tagStack) <= 1 \
               and (self.parseOnlyThese.text or not self.parseOnlyThese.searchTag(name, attrs)):
            return

        tag = Tag(self, name, attrs, self.currentTag, self.previous)
        if self.previous:
            self.previous.next = tag
        self.previous = tag
        self.pushTag(tag)
        if selfClosing or self.isSelfClosingTag(name):
            self.popTag()
        if name in self.QUOTE_TAGS:
            #print "Beginning quote (%s)" % name
            self.quoteStack.append(name)
            self.literal = 1
        return tag

    def unknown_endtag(self, name):
        #print "End tag %s" % name
        if self.quoteStack and self.quoteStack[-1] != name:
            #This is not a real end tag.
            #print "</%s> is not real!" % name
            self.handle_data('</%s>' % name)
            return
        self.endData()
        self._popToTag(name)
        if self.quoteStack and self.quoteStack[-1] == name:
            self.quoteStack.pop()
            self.literal = (len(self.quoteStack) > 0)

    def handle_data(self, data):
        self.currentData.append(data)

    def _toStringSubclass(self, text, subclass):
        """Adds a certain piece of text to the tree as a NavigableString
        subclass."""
        self.endData()
        self.handle_data(text)
        self.endData(subclass)

    def handle_pi(self, text):
        """Handle a processing instruction as a ProcessingInstruction
        object, possibly one with a %SOUP-ENCODING% slot into which an
        encoding will be plugged later."""
        if text[:3] == "xml":
            text = u"xml version='1.0' encoding='%SOUP-ENCODING%'"
        self._toStringSubclass(text, ProcessingInstruction)

    def handle_comment(self, text):
        "Handle comments as Comment objects."
        self._toStringSubclass(text, Comment)

    def handle_charref(self, ref):
        "Handle character references as data."
        if self.convertEntities:
            data = unichr(int(ref))
        else:
            data = '&#%s;' % ref
        self.handle_data(data)

    def handle_entityref(self, ref):
        """Handle entity references as data, possibly converting known
        HTML and/or XML entity references to the corresponding Unicode
        characters."""
        data = None
        if self.convertHTMLEntities:
            try:
                data = unichr(name2codepoint[ref])
            except KeyError:
                pass

        if not data and self.convertXMLEntities:
                data = self.XML_ENTITIES_TO_SPECIAL_CHARS.get(ref)

        if not data and self.convertHTMLEntities and \
            not self.XML_ENTITIES_TO_SPECIAL_CHARS.get(ref):
                # TODO: We've got a problem here. We're told this is
                # an entity reference, but it's not an XML entity
                # reference or an HTML entity reference. Nonetheless,
                # the logical thing to do is to pass it through as an
                # unrecognized entity reference.
                #
                # Except: when the input is "&carol;" this function
                # will be called with input "carol". When the input is
                # "AT&T", this function will be called with input
                # "T". We have no way of knowing whether a semicolon
                # was present originally, so we don't know whether
                # this is an unknown entity or just a misplaced
                # ampersand.
                #
                # The more common case is a misplaced ampersand, so I
                # escape the ampersand and omit the trailing semicolon.
                data = "&amp;%s" % ref
        if not data:
            # This case is different from the one above, because we
            # haven't already gone through a supposedly comprehensive
            # mapping of entities to Unicode characters. We might not
            # have gone through any mapping at all. So the chances are
            # very high that this is a real entity, and not a
            # misplaced ampersand.
            data = "&%s;" % ref
        self.handle_data(data)

    def handle_decl(self, data):
        "Handle DOCTYPEs and the like as Declaration objects."
        self._toStringSubclass(data, Declaration)

    def parse_declaration(self, i):
        """Treat a bogus SGML declaration as raw data. Treat a CDATA
        declaration as a CData object."""
        j = None
        if self.rawdata[i:i+9] == '<![CDATA[':
             k = self.rawdata.find(']]>', i)
             if k == -1:
                 k = len(self.rawdata)
             data = self.rawdata[i+9:k]
             j = k+3
             self._toStringSubclass(data, CData)
        else:
            try:
                j = SGMLParser.parse_declaration(self, i)
            except SGMLParseError:
                toHandle = self.rawdata[i:]
                self.handle_data(toHandle)
                j = i + len(toHandle)
        return j

class BeautifulSoup(BeautifulStoneSoup):

    """This parser knows the following facts about HTML:

    * Some tags have no closing tag and should be interpreted as being
      closed as soon as they are encountered.

    * The text inside some tags (ie. 'script') may contain tags which
      are not really part of the document and which should be parsed
      as text, not tags. If you want to parse the text as tags, you can
      always fetch it and parse it explicitly.

    * Tag nesting rules:

      Most tags can't be nested at all. For instance, the occurance of
      a <p> tag should implicitly close the previous <p> tag.

       <p>Para1<p>Para2
        should be transformed into:
       <p>Para1</p><p>Para2

      Some tags can be nested arbitrarily. For instance, the occurance
      of a <blockquote> tag should _not_ implicitly close the previous
      <blockquote> tag.

       Alice said: <blockquote>Bob said: <blockquote>Blah
        should NOT be transformed into:
       Alice said: <blockquote>Bob said: </blockquote><blockquote>Blah

      Some tags can be nested, but the nesting is reset by the
      interposition of other tags. For instance, a <tr> tag should
      implicitly close the previous <tr> tag within the same <table>,
      but not close a <tr> tag in another table.

       <table><tr>Blah<tr>Blah
        should be transformed into:
       <table><tr>Blah</tr><tr>Blah
        but,
       <tr>Blah<table><tr>Blah
        should NOT be transformed into
       <tr>Blah<table></tr><tr>Blah

    Differing assumptions about tag nesting rules are a major source
    of problems with the BeautifulSoup class. If BeautifulSoup is not
    treating as nestable a tag your page author treats as nestable,
    try ICantBelieveItsBeautifulSoup, MinimalSoup, or
    BeautifulStoneSoup before writing your own subclass."""

    def __init__(self, *args, **kwargs):
        if not kwargs.has_key('smartQuotesTo'):
            kwargs['smartQuotesTo'] = self.HTML_ENTITIES
        kwargs['isHTML'] = True
        BeautifulStoneSoup.__init__(self, *args, **kwargs)

    SELF_CLOSING_TAGS = buildTagMap(None,
                                    ('br' , 'hr', 'input', 'img', 'meta',
                                    'spacer', 'link', 'frame', 'base', 'col'))

    PRESERVE_WHITESPACE_TAGS = set(['pre', 'textarea'])

    QUOTE_TAGS = {'script' : None, 'textarea' : None}

    #According to the HTML standard, each of these inline tags can
    #contain another tag of the same type. Furthermore, it's common
    #to actually use these tags this way.
    NESTABLE_INLINE_TAGS = ('span', 'font', 'q', 'object', 'bdo', 'sub', 'sup',
                            'center')

    #According to the HTML standard, these block tags can contain
    #another tag of the same type. Furthermore, it's common
    #to actually use these tags this way.
    NESTABLE_BLOCK_TAGS = ('blockquote', 'div', 'fieldset', 'ins', 'del')

    #Lists can contain other lists, but there are restrictions.
    NESTABLE_LIST_TAGS = { 'ol' : [],
                           'ul' : [],
                           'li' : ['ul', 'ol'],
                           'dl' : [],
                           'dd' : ['dl'],
                           'dt' : ['dl'] }

    #Tables can contain other tables, but there are restrictions.
    NESTABLE_TABLE_TAGS = {'table' : [],
                           'tr' : ['table', 'tbody', 'tfoot', 'thead'],
                           'td' : ['tr'],
                           'th' : ['tr'],
                           'thead' : ['table'],
                           'tbody' : ['table'],
                           'tfoot' : ['table'],
                           }

    NON_NESTABLE_BLOCK_TAGS = ('address', 'form', 'p', 'pre')

    #If one of these tags is encountered, all tags up to the next tag of
    #this type are popped.
    RESET_NESTING_TAGS = buildTagMap(None, NESTABLE_BLOCK_TAGS, 'noscript',
                                     NON_NESTABLE_BLOCK_TAGS,
                                     NESTABLE_LIST_TAGS,
                                     NESTABLE_TABLE_TAGS)

    NESTABLE_TAGS = buildTagMap([], NESTABLE_INLINE_TAGS, NESTABLE_BLOCK_TAGS,
                                NESTABLE_LIST_TAGS, NESTABLE_TABLE_TAGS)

    # Used to detect the charset in a META tag; see start_meta
    CHARSET_RE = re.compile("((^|;)\s*charset=)([^;]*)", re.M)

    def start_meta(self, attrs):
        """Beautiful Soup can detect a charset included in a META tag,
        try to convert the document to that charset, and re-parse the
        document from the beginning."""
        httpEquiv = None
        contentType = None
        contentTypeIndex = None
        tagNeedsEncodingSubstitution = False

        for i in range(0, len(attrs)):
            key, value = attrs[i]
            key = key.lower()
            if key == 'http-equiv':
                httpEquiv = value
            elif key == 'content':
                contentType = value
                contentTypeIndex = i

        if httpEquiv and contentType: # It's an interesting meta tag.
            match = self.CHARSET_RE.search(contentType)
            if match:
                if (self.declaredHTMLEncoding is not None or
                    self.originalEncoding == self.fromEncoding):
                    # An HTML encoding was sniffed while converting
                    # the document to Unicode, or an HTML encoding was
                    # sniffed during a previous pass through the
                    # document, or an encoding was specified
                    # explicitly and it worked. Rewrite the meta tag.
                    def rewrite(match):
                        return match.group(1) + "%SOUP-ENCODING%"
                    newAttr = self.CHARSET_RE.sub(rewrite, contentType)
                    attrs[contentTypeIndex] = (attrs[contentTypeIndex][0],
                                               newAttr)
                    tagNeedsEncodingSubstitution = True
                else:
                    # This is our first pass through the document.
                    # Go through it again with the encoding information.
                    newCharset = match.group(3)
                    if newCharset and newCharset != self.originalEncoding:
                        self.declaredHTMLEncoding = newCharset
                        self._feed(self.declaredHTMLEncoding)
                        raise StopParsing
                    pass
        tag = self.unknown_starttag("meta", attrs)
        if tag and tagNeedsEncodingSubstitution:
            tag.containsSubstitutions = True

class StopParsing(Exception):
    pass

class ICantBelieveItsBeautifulSoup(BeautifulSoup):

    """The BeautifulSoup class is oriented towards skipping over
    common HTML errors like unclosed tags. However, sometimes it makes
    errors of its own. For instance, consider this fragment:

     <b>Foo<b>Bar</b></b>

    This is perfectly valid (if bizarre) HTML. However, the
    BeautifulSoup class will implicitly close the first b tag when it
    encounters the second 'b'. It will think the author wrote
    "<b>Foo<b>Bar", and didn't close the first 'b' tag, because
    there's no real-world reason to bold something that's already
    bold. When it encounters '</b></b>' it will close two more 'b'
    tags, for a grand total of three tags closed instead of two. This
    can throw off the rest of your document structure. The same is
    true of a number of other tags, listed below.

    It's much more common for someone to forget to close a 'b' tag
    than to actually use nested 'b' tags, and the BeautifulSoup class
    handles the common case. This class handles the not-co-common
    case: where you can't believe someone wrote what they did, but
    it's valid HTML and BeautifulSoup screwed up by assuming it
    wouldn't be."""

    I_CANT_BELIEVE_THEYRE_NESTABLE_INLINE_TAGS = \
     ('em', 'big', 'i', 'small', 'tt', 'abbr', 'acronym', 'strong',
      'cite', 'code', 'dfn', 'kbd', 'samp', 'strong', 'var', 'b',
      'big')

    I_CANT_BELIEVE_THEYRE_NESTABLE_BLOCK_TAGS = ('noscript',)

    NESTABLE_TAGS = buildTagMap([], BeautifulSoup.NESTABLE_TAGS,
                                I_CANT_BELIEVE_THEYRE_NESTABLE_BLOCK_TAGS,
                                I_CANT_BELIEVE_THEYRE_NESTABLE_INLINE_TAGS)

class MinimalSoup(BeautifulSoup):
    """The MinimalSoup class is for parsing HTML that contains
    pathologically bad markup. It makes no assumptions about tag
    nesting, but it does know which tags are self-closing, that
    <script> tags contain Javascript and should not be parsed, that
    META tags may contain encoding information, and so on.

    This also makes it better for subclassing than BeautifulStoneSoup
    or BeautifulSoup."""

    RESET_NESTING_TAGS = buildTagMap('noscript')
    NESTABLE_TAGS = {}

class BeautifulSOAP(BeautifulStoneSoup):
    """This class will push a tag with only a single string child into
    the tag's parent as an attribute. The attribute's name is the tag
    name, and the value is the string child. An example should give
    the flavor of the change:

    <foo><bar>baz</bar></foo>
     =>
    <foo bar="baz"><bar>baz</bar></foo>

    You can then access fooTag['bar'] instead of fooTag.barTag.string.

    This is, of course, useful for scraping structures that tend to
    use subelements instead of attributes, such as SOAP messages. Note
    that it modifies its input, so don't print the modified version
    out.

    I'm not sure how many people really want to use this class; let me
    know if you do. Mainly I like the name."""

    def popTag(self):
        if len(self.tagStack) > 1:
            tag = self.tagStack[-1]
            parent = self.tagStack[-2]
            parent._getAttrMap()
            if (isinstance(tag, Tag) and len(tag.contents) == 1 and
                isinstance(tag.contents[0], NavigableString) and
                not parent.attrMap.has_key(tag.name)):
                parent[tag.name] = tag.contents[0]
        BeautifulStoneSoup.popTag(self)

#Enterprise class names! It has come to our attention that some people
#think the names of the Beautiful Soup parser classes are too silly
#and "unprofessional" for use in enterprise screen-scraping. We feel
#your pain! For such-minded folk, the Beautiful Soup Consortium And
#All-Night Kosher Bakery recommends renaming this file to
#"RobustParser.py" (or, in cases of extreme enterprisiness,
#"RobustParserBeanInterface.class") and using the following
#enterprise-friendly class aliases:
class RobustXMLParser(BeautifulStoneSoup):
    pass
class RobustHTMLParser(BeautifulSoup):
    pass
class RobustWackAssHTMLParser(ICantBelieveItsBeautifulSoup):
    pass
class RobustInsanelyWackAssHTMLParser(MinimalSoup):
    pass
class SimplifyingSOAPParser(BeautifulSOAP):
    pass

######################################################
#
# Bonus library: Unicode, Dammit
#
# This class forces XML data into a standard format (usually to UTF-8
# or Unicode).  It is heavily based on code from Mark Pilgrim's
# Universal Feed Parser. It does not rewrite the XML or HTML to
# reflect a new encoding: that happens in BeautifulStoneSoup.handle_pi
# (XML) and BeautifulSoup.start_meta (HTML).

# Autodetects character encodings.
# Download from http://chardet.feedparser.org/
try:
    import chardet
#    import chardet.constants
#    chardet.constants._debug = 1
except ImportError:
    chardet = None

# cjkcodecs and iconv_codec make Python know about more character encodings.
# Both are available from http://cjkpython.i18n.org/
# They're built in if you use Python 2.4.
try:
    import cjkcodecs.aliases
except ImportError:
    pass
try:
    import iconv_codec
except ImportError:
    pass

class UnicodeDammit:
    """A class for detecting the encoding of a *ML document and
    converting it to a Unicode string. If the source encoding is
    windows-1252, can replace MS smart quotes with their HTML or XML
    equivalents."""

    # This dictionary maps commonly seen values for "charset" in HTML
    # meta tags to the corresponding Python codec names. It only covers
    # values that aren't in Python's aliases and can't be determined
    # by the heuristics in find_codec.
    CHARSET_ALIASES = { "macintosh" : "mac-roman",
                        "x-sjis" : "shift-jis" }

    def __init__(self, markup, overrideEncodings=[],
                 smartQuotesTo='xml', isHTML=False):
        self.declaredHTMLEncoding = None
        self.markup, documentEncoding, sniffedEncoding = \
                     self._detectEncoding(markup, isHTML)
        self.smartQuotesTo = smartQuotesTo
        self.triedEncodings = []
        if markup == '' or isinstance(markup, unicode):
            self.originalEncoding = None
            self.unicode = unicode(markup)
            return

        u = None
        for proposedEncoding in overrideEncodings:
            u = self._convertFrom(proposedEncoding)
            if u: break
        if not u:
            for proposedEncoding in (documentEncoding, sniffedEncoding):
                u = self._convertFrom(proposedEncoding)
                if u: break

        # If no luck and we have auto-detection library, try that:
        if not u and chardet and not isinstance(self.markup, unicode):
            u = self._convertFrom(chardet.detect(self.markup)['encoding'])

        # As a last resort, try utf-8 and windows-1252:
        if not u:
            for proposed_encoding in ("utf-8", "windows-1252"):
                u = self._convertFrom(proposed_encoding)
                if u: break

        self.unicode = u
        if not u: self.originalEncoding = None

    def _subMSChar(self, orig):
        """Changes a MS smart quote character to an XML or HTML
        entity."""
        sub = self.MS_CHARS.get(orig)
        if isinstance(sub, tuple):
            if self.smartQuotesTo == 'xml':
                sub = '&#x%s;' % sub[1]
            else:
                sub = '&%s;' % sub[0]
        return sub

    def _convertFrom(self, proposed):
        proposed = self.find_codec(proposed)
        if not proposed or proposed in self.triedEncodings:
            return None
        self.triedEncodings.append(proposed)
        markup = self.markup

        # Convert smart quotes to HTML if coming from an encoding
        # that might have them.
        if self.smartQuotesTo and proposed.lower() in("windows-1252",
                                                      "iso-8859-1",
                                                      "iso-8859-2"):
            markup = re.compile("([\x80-\x9f])").sub \
                     (lambda(x): self._subMSChar(x.group(1)),
                      markup)

        try:
            # print "Trying to convert document to %s" % proposed
            u = self._toUnicode(markup, proposed)
            self.markup = u
            self.originalEncoding = proposed
        except Exception, e:
            # print "That didn't work!"
            # print e
            return None
        #print "Correct encoding: %s" % proposed
        return self.markup

    def _toUnicode(self, data, encoding):
        '''Given a string and its encoding, decodes the string into Unicode.
        %encoding is a string recognized by encodings.aliases'''

        # strip Byte Order Mark (if present)
        if (len(data) >= 4) and (data[:2] == '\xfe\xff') \
               and (data[2:4] != '\x00\x00'):
            encoding = 'utf-16be'
            data = data[2:]
        elif (len(data) >= 4) and (data[:2] == '\xff\xfe') \
                 and (data[2:4] != '\x00\x00'):
            encoding = 'utf-16le'
            data = data[2:]
        elif data[:3] == '\xef\xbb\xbf':
            encoding = 'utf-8'
            data = data[3:]
        elif data[:4] == '\x00\x00\xfe\xff':
            encoding = 'utf-32be'
            data = data[4:]
        elif data[:4] == '\xff\xfe\x00\x00':
            encoding = 'utf-32le'
            data = data[4:]
        newdata = unicode(data, encoding)
        return newdata

    def _detectEncoding(self, xml_data, isHTML=False):
        """Given a document, tries to detect its XML encoding."""
        xml_encoding = sniffed_xml_encoding = None
        try:
            if xml_data[:4] == '\x4c\x6f\xa7\x94':
                # EBCDIC
                xml_data = self._ebcdic_to_ascii(xml_data)
            elif xml_data[:4] == '\x00\x3c\x00\x3f':
                # UTF-16BE
                sniffed_xml_encoding = 'utf-16be'
                xml_data = unicode(xml_data, 'utf-16be').encode('utf-8')
            elif (len(xml_data) >= 4) and (xml_data[:2] == '\xfe\xff') \
                     and (xml_data[2:4] != '\x00\x00'):
                # UTF-16BE with BOM
                sniffed_xml_encoding = 'utf-16be'
                xml_data = unicode(xml_data[2:], 'utf-16be').encode('utf-8')
            elif xml_data[:4] == '\x3c\x00\x3f\x00':
                # UTF-16LE
                sniffed_xml_encoding = 'utf-16le'
                xml_data = unicode(xml_data, 'utf-16le').encode('utf-8')
            elif (len(xml_data) >= 4) and (xml_data[:2] == '\xff\xfe') and \
                     (xml_data[2:4] != '\x00\x00'):
                # UTF-16LE with BOM
                sniffed_xml_encoding = 'utf-16le'
                xml_data = unicode(xml_data[2:], 'utf-16le').encode('utf-8')
            elif xml_data[:4] == '\x00\x00\x00\x3c':
                # UTF-32BE
                sniffed_xml_encoding = 'utf-32be'
                xml_data = unicode(xml_data, 'utf-32be').encode('utf-8')
            elif xml_data[:4] == '\x3c\x00\x00\x00':
                # UTF-32LE
                sniffed_xml_encoding = 'utf-32le'
                xml_data = unicode(xml_data, 'utf-32le').encode('utf-8')
            elif xml_data[:4] == '\x00\x00\xfe\xff':
                # UTF-32BE with BOM
                sniffed_xml_encoding = 'utf-32be'
                xml_data = unicode(xml_data[4:], 'utf-32be').encode('utf-8')
            elif xml_data[:4] == '\xff\xfe\x00\x00':
                # UTF-32LE with BOM
                sniffed_xml_encoding = 'utf-32le'
                xml_data = unicode(xml_data[4:], 'utf-32le').encode('utf-8')
            elif xml_data[:3] == '\xef\xbb\xbf':
                # UTF-8 with BOM
                sniffed_xml_encoding = 'utf-8'
                xml_data = unicode(xml_data[3:], 'utf-8').encode('utf-8')
            else:
                sniffed_xml_encoding = 'ascii'
                pass
        except:
            xml_encoding_match = None
        xml_encoding_match = re.compile(
            '^<\?.*encoding=[\'"](.*?)[\'"].*\?>').match(xml_data)
        if not xml_encoding_match and isHTML:
            regexp = re.compile('<\s*meta[^>]+charset=([^>]*?)[;\'">]', re.I)
            xml_encoding_match = regexp.search(xml_data)
        if xml_encoding_match is not None:
            xml_encoding = xml_encoding_match.groups()[0].lower()
            if isHTML:
                self.declaredHTMLEncoding = xml_encoding
            if sniffed_xml_encoding and \
               (xml_encoding in ('iso-10646-ucs-2', 'ucs-2', 'csunicode',
                                 'iso-10646-ucs-4', 'ucs-4', 'csucs4',
                                 'utf-16', 'utf-32', 'utf_16', 'utf_32',
                                 'utf16', 'u16')):
                xml_encoding = sniffed_xml_encoding
        return xml_data, xml_encoding, sniffed_xml_encoding


    def find_codec(self, charset):
        return self._codec(self.CHARSET_ALIASES.get(charset, charset)) \
               or (charset and self._codec(charset.replace("-", ""))) \
               or (charset and self._codec(charset.replace("-", "_"))) \
               or charset

    def _codec(self, charset):
        if not charset: return charset
        codec = None
        try:
            codecs.lookup(charset)
            codec = charset
        except (LookupError, ValueError):
            pass
        return codec

    EBCDIC_TO_ASCII_MAP = None
    def _ebcdic_to_ascii(self, s):
        c = self.__class__
        if not c.EBCDIC_TO_ASCII_MAP:
            emap = (0,1,2,3,156,9,134,127,151,141,142,11,12,13,14,15,
                    16,17,18,19,157,133,8,135,24,25,146,143,28,29,30,31,
                    128,129,130,131,132,10,23,27,136,137,138,139,140,5,6,7,
                    144,145,22,147,148,149,150,4,152,153,154,155,20,21,158,26,
                    32,160,161,162,163,164,165,166,167,168,91,46,60,40,43,33,
                    38,169,170,171,172,173,174,175,176,177,93,36,42,41,59,94,
                    45,47,178,179,180,181,182,183,184,185,124,44,37,95,62,63,
                    186,187,188,189,190,191,192,193,194,96,58,35,64,39,61,34,
                    195,97,98,99,100,101,102,103,104,105,196,197,198,199,200,
                    201,202,106,107,108,109,110,111,112,113,114,203,204,205,
                    206,207,208,209,126,115,116,117,118,119,120,121,122,210,
                    211,212,213,214,215,216,217,218,219,220,221,222,223,224,
                    225,226,227,228,229,230,231,123,65,66,67,68,69,70,71,72,
                    73,232,233,234,235,236,237,125,74,75,76,77,78,79,80,81,
                    82,238,239,240,241,242,243,92,159,83,84,85,86,87,88,89,
                    90,244,245,246,247,248,249,48,49,50,51,52,53,54,55,56,57,
                    250,251,252,253,254,255)
            import string
            c.EBCDIC_TO_ASCII_MAP = string.maketrans( \
            ''.join(map(chr, range(256))), ''.join(map(chr, emap)))
        return s.translate(c.EBCDIC_TO_ASCII_MAP)

    MS_CHARS = { '\x80' : ('euro', '20AC'),
                 '\x81' : ' ',
                 '\x82' : ('sbquo', '201A'),
                 '\x83' : ('fnof', '192'),
                 '\x84' : ('bdquo', '201E'),
                 '\x85' : ('hellip', '2026'),
                 '\x86' : ('dagger', '2020'),
                 '\x87' : ('Dagger', '2021'),
                 '\x88' : ('circ', '2C6'),
                 '\x89' : ('permil', '2030'),
                 '\x8A' : ('Scaron', '160'),
                 '\x8B' : ('lsaquo', '2039'),
                 '\x8C' : ('OElig', '152'),
                 '\x8D' : '?',
                 '\x8E' : ('#x17D', '17D'),
                 '\x8F' : '?',
                 '\x90' : '?',
                 '\x91' : ('lsquo', '2018'),
                 '\x92' : ('rsquo', '2019'),
                 '\x93' : ('ldquo', '201C'),
                 '\x94' : ('rdquo', '201D'),
                 '\x95' : ('bull', '2022'),
                 '\x96' : ('ndash', '2013'),
                 '\x97' : ('mdash', '2014'),
                 '\x98' : ('tilde', '2DC'),
                 '\x99' : ('trade', '2122'),
                 '\x9a' : ('scaron', '161'),
                 '\x9b' : ('rsaquo', '203A'),
                 '\x9c' : ('oelig', '153'),
                 '\x9d' : '?',
                 '\x9e' : ('#x17E', '17E'),
                 '\x9f' : ('Yuml', ''),}

#######################################################################


#By default, act as an HTML pretty-printer.
#if __name__ == '__main__':
#    import sys
#    soup = BeautifulSoup(sys.stdin)
#    print soup.prettify()


def dbg(msg):
  if __DEBUG__:
    logging.info(msg)

if __name__ == '__main__':
  logging.basicConfig(level=logging.DEBUG,
                      format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                      filename='output.log',
                      filemode='w'
                      )
  import sys
  import urllib2
  response = urllib2.urlopen(sys.argv[1])
  html = response.read()
  df = Readability(html, url=sys.argv[1], footnote_links=True, readable_footnote_links=True, service_uri='http://ahrefs.appspot.com/g?u=%s')
  df.process_document()
  if __OUTPUT__:
    print df.get_html(prettyPrint=True)
