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

import htmlentitydefs
import logging
import re
import urlparse

from string import punctuation

from BeautifulSoup import ICantBelieveItsBeautifulSoup, Comment, Tag, NavigableString


__version__ = '1.7.1.10'
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
# - what happens if the HTML is completely screwed and there's no BODY

class Readability(object):
  def __init__(self, content, url=None, footnote_links=False, **settings):
    self.read_style = settings.get('read_style', 'style-athelas')
    self.read_margin = settings.get('read_margin', 'margin-medium')
    self.read_size = settings.get('read_size', 'size-medium')

    self._flag_strip_unlikelys = settings.get('strip_unlike', True)
    self._flag_weight_classes = settings.get('weight_classes', True)
    self._flag_clean_conditionally = settings.get('clean_conditionally', True)
  
    self._url = url or ""
    self._footnote_links = footnote_links
    
    self.content = replaceBrsRe.sub('</p><p>', content)
    try:
      self._osoup = ICantBelieveItsBeautifulSoup(self.content)
    except TypeError:
      raise ValueError('content cannot be converted to unicode')
#    dbg("content: %s" % self._osoup)
    self._fsoup = ICantBelieveItsBeautifulSoup(OUTPUT_BODY % dict(read_style=self.read_style, read_margin=self.read_margin, read_size=self.read_size))

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
    
    article_title = self._get_article_title()
    
    if not len(self._osoup.findAll('body')):
      articleContent = Tag(self._fsoup, 'p')
      articleContent.setString("Sorry, readability was unable to parse this page for content. If you feel like it should have been able to, please <a href='http://code.google.com/p/arc90labs-readability/issues/entry'>let us know by submitting an issue.</a>")
    else:
      articleContent = self.grabArticle()
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
    divInner.append(self._get_article_footer(article_title))

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

  def _get_article_footer(self, title):
#    articleFooter = Tag(self._fsoup, 'div', attrs=[('id', 'readFooter')])
#    articleFooter.setString("<div id='rdb-footer-print-'>Excerpted from: <cite>%s</cite>: <small>%s</small></div>" % (self.getInnerText(title), self._url))
    articleFooter = Tag(self._fsoup, 'div', attrs=[('id', 'readFooter')])
    if self._url:
      articleFooter.setString("<div id='rdb-footer-print-'><cite>%s</cite></div>" % self._url)
    
    return articleFooter

  def _post_process_content(self):
    ''' Adds footnotes for links, fixes images floats '''
    self._fix_lists()
    
    self._fix_links()
    
    if self._footnote_links:
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


    linkCount = len(articleFootnotes.findAll('li'))
    for link in self._fsoup.findAll('a'):
      if (not link.get('href')) or (link.get('class') == 'readability-DoNotFootnote') or (skipFootnoteLink.match(self.getInnerText(link))):
        continue
      if link['href'].startswith('#'):
        continue
      if self._url and link['href'] == self._url:
        continue
        
      linkCount += 1
      footnoteLink = Tag(self._fsoup, 'a', attrs=[('href', link.get('href'))])
      footnoteLink.setString(link['href'])
      footnoteLink['name'] = "readabilityFootnoteLink-%s" % linkCount
      
      footnote = Tag(self._fsoup, 'li')
      footnote.setString("<small>%s <sup><a href='#readabilityLink-%s' title='Jump to Link in Article'>^back</a></sup></small> " % (footnoteLink, linkCount))


      refLinkSup = Tag(self._fsoup, 'sup')
      refLink = Tag(self._fsoup, 'a', attrs=[('href', '#readabilityFootnoteLink-%s' % linkCount),
                                             ('class', 'readability-DoNotFootnote')])
      refLink.setString("[&nbsp;%s&nbsp;]" % linkCount)
      refLinkSup.append(refLink)

      olink = Tag(self._fsoup, 'a', attrs=[('href', link['href']),
                                           ('name', "readabilityLink-%s" % linkCount)])
      olink.setString(self.getInnerText(link))
      replElem = Tag(self._fsoup, 'span')
      replElem.append(olink)
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

  def _get_article_title(self):
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
    
    if len(possible_titles) == 0:
      articleTitle.setString(candidate_title)
      return articleTitle

    max_score = 0
    best_candidate = None
    score_tuple = None
    for inner_text, scoret in possible_titles.items():
      if scoret[0] > max_score:
        best_candidate = inner_text
        max_score = scoret[0]
        score_tuple = scoret

    if best_candidate:
      if alt_candidate_title.find(wordSplitRe.sub(' ', unescape(best_candidate))) > -1:
        dbg("_get_article_title::title best_candidate (success:%s:%s): '%s' (page title:%s)" % (score_tuple[0], score_tuple[2], best_candidate.encode('utf8'), candidate_title.encode('utf8')))
        candidate_title = best_candidate
      elif max_score > 0:
        dbg("_get_article_title::title best_candidate (unsure :%s:%s): '%s' (page title:%s)" % (score_tuple[0], score_tuple[2], best_candidate.encode('utf8'), candidate_title.encode('utf8')))
      else:
        dbg("_get_article_title::title best_candidate (failure:%s:%s): '%s' (page title:%s)" % (score_tuple[0], score_tuple[2], best_candidate.encode('utf8'), candidate_title.encode('utf8')))
    articleTitle.setString(candidate_title)

    return articleTitle


  def grabArticle(self):
    def match_unlikely_candidates(node):
      if not isinstance(node, Tag):
        return False
      if node.name == 'body':
        return False
      unlikelyMatchString = node.get('class', '') + node.get('id', '')
      return unlikelyMatchString and \
        unlikelyCandidatesRe.search(unlikelyMatchString) and \
        not okMaybeItsACandidateRe.search(unlikelyMatchString)

    if self._flag_strip_unlikelys:
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
      if self._flag_strip_unlikelys:
        self._flag_strip_unlikelys = False
        self._osoup = ICantBelieveItsBeautifulSoup(self.content)
        self._prepare_document()
        return self.grabArticle()
      if self._flag_weight_classes:
        self._flag_weight_classes = False
        self._osoup = ICantBelieveItsBeautifulSoup(self.content)
        self._prepare_document()
        return self.grabArticle()
      if self._flag_clean_conditionally:
        self._flag_clean_conditionally = False
        self._osoup = ICantBelieveItsBeautifulSoup(self.content)
        self._prepare_document()
        return self.grabArticle()

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
    if not self._flag_weight_classes:
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
  

OUTPUT_BODY = """<html>
<body id='readabilityBody' class='%(read_style)s'>
<div id='readOverlay' class='%(read_style)s'>
  <div id='readInner' class='%(read_margin)s %(read_size)s'>
  </div>
</div>
</body>
</html>"""

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
  df = Readability(html, url=sys.argv[1], footnote_links=False)
  df.process_document()
  if __OUTPUT__:
    print df.get_html(prettyPrint=True)
