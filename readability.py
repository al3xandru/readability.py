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
import re

from BeautifulSoup import ICantBelieveItsBeautifulSoup, Comment, Tag, NavigableString

__DEBUG__ = False
__OUTPUT__ = True

unlikelyCandidatesRe = re.compile('combx|comment|disqus|foot|header|menu|meta|nav|rss|shoutbox|sidebar|sponsor', re.IGNORECASE)
okMaybeItsACandidateRe = re.compile('and|article|body|column|main', re.IGNORECASE)
positiveRe = re.compile('article|body|content|entry|hentry|page|pagination|post|text', re.IGNORECASE)
negativeRe = re.compile('combx|comment|contact|foot|footer|footnote|link|media|meta|promo|related|scroll|shoutbox|sponsor|tags|widget', re.IGNORECASE)
divToPElementsRe = re.compile('<(a|blockquote|dl|div|img|ol|p|pre|table|ul)', re.IGNORECASE)
replaceBrsRe = re.compile('(<br[^>]*>[ \n\r\t]*){2,}', re.IGNORECASE | re.MULTILINE)
replaceFontsRe = re.compile('<(/?)font[^>]*>', re.IGNORECASE | re.MULTILINE)
trimRe = re.compile('^\s+|\s+$', re.MULTILINE)
normalizeRe = re.compile('\s{2,}', re.MULTILINE)
killBreaksRe = re.compile('(<br\s*/?>(\s|&nbsp;?)*){1,}', re.MULTILINE)
killMoreBreaksRe = re.compile('<br[^>]*>\s*<p', re.MULTILINE)
videoRe = re.compile('http://(www\.)?(youtube|vimeo|blip)\.(com|tv)', re.IGNORECASE)
unknownRe = re.compile('\.( |$)')

READ_STYLES = ('style-newspaper', 'style-novel', 'style-athelas', 'style-ebook', 'style-apertura')
READ_MARGINS = ('margin-x-narrow', 'margin-narrow', 'margin-medium', 'margin-wide', 'margin-x-wide')
SIZES = ('size-x-small', 'size-small', 'size-medium', 'size-large', 'size-x-large')

# TODO:
# - frames (?)
# - use Tag.fetchText()

class Readability(object):
  def __init__(self, content, **settings):
    self.content = replaceBrsRe.sub('</p><p>', content)
    self.osoup = ICantBelieveItsBeautifulSoup(content)
    self.read_style = settings.get('read_style', 'style-athelas')
    self.read_margin = settings.get('read_margin', 'margin-medium')
    self.read_size = settings.get('read_size', 'size-medium')
    self.fsoup = ICantBelieveItsBeautifulSoup(OUTPUT_BODY % dict(read_style=self.read_style, read_margin=self.read_margin, read_size=self.read_size))


  def process_document(self, preserveUnlikelyCandidates=False):
    self.prepare_document()

    articleContent = self.grab_article(preserveUnlikelyCandidates)
    #
    # If we attempted to strip unlikely candidates on the first run through, and we ended up with no content,
    # that may mean we stripped out the actual content so we couldn't parse it. So re-run init while preserving
    # unlikely candidates to have a better shot at getting our content out properly.
    #
    if not self.get_inner_text(articleContent, False):
      if not preserveUnlikelyCandidates:
        self.osoup = ICantBelieveItsBeautifulSoup(self.content)
        return self.process_document(preserveUnlikelyCandidates=True)
      else:
        articleContent = Tag(self.fsoup, 'p')
        articleContent.setString("Sorry, readability was unable to parse this page for content. If you feel like it should have been able to, please <a href='http://code.google.com/p/arc90labs-readability/issues/entry'>let us know by submitting an issue.</a>")


    divInner = self.fsoup.find('div', attrs={'id':'readInner'}) 
    divInner.insert(0, self.get_article_title())
    divInner.insert(1, articleContent)
    
    # prepare head
    head = self.osoup.find('head')
    screen_stylesheet = Tag(self.fsoup, 'link', attrs=[('rel', 'stylesheet'), 
                                                       ('href', 'http://lab.arc90.com/experiments/readability/css/readability.css'),
                                                       ('type', 'text/css'),
                                                       ('media', 'screen')])
    print_stylesheet = Tag(self.fsoup, 'link', attrs=[('rel', 'stylesheet'), 
                                                      ('href', 'http://lab.arc90.com/experiments/readability/css/readability-print.css'),
                                                      ('type', 'text/css'),
                                                      ('media', 'print')])
    self.fsoup.find('html').insert(0, head)
    head = self.fsoup.find('head')
    head.append(screen_stylesheet)
    head.append(print_stylesheet)


  def get_html(self, prettyPrint=False, removeComments=True):
    if removeComments:
      [comment.extract() for comment in self.fsoup.findAll(text=lambda text:isinstance(text, Comment))]

    output = self.fsoup.renderContents(prettyPrint=prettyPrint)
    output = killBreaksRe.sub('<br />', output)
    output = killMoreBreaksRe.sub('<p', output)
    return output

  def prepare_document(self):
    # remove all scripts
    [script.extract() for script in self.osoup.findAll('script')]
    
    # remove all stylesheets
    [style.extract() for style in self.osoup.findAll('style')]

    # remove all style tags in head
    head = self.osoup.find('head')
    [link.extract() for link in head.findAll('link', attrs={'rel': 'stylesheet'})]

    # remove fonts
    for font in self.osoup.findAll('font'):
      self.replace_element(self.osoup, font, 'span')

  def get_article_title(self):
    articleTitle = Tag(self.fsoup, 'h1')
    title = self.osoup.find('title')
    if title and title.string:
      articleTitle.contents.append(title.string)
    return articleTitle

  def grab_article(self, preserveUnlikelyCandidates):
    def match_unlikely_candidates(node):
      if not isinstance(node, Tag):
        return False
      if node.name == 'body':
        return False
      unlikelyMatchString = node.get('class', '') + node.get('id', '')
      return unlikelyMatchString and \
        unlikelyCandidatesRe.search(unlikelyMatchString) and \
        not okMaybeItsACandidateRe.search(unlikelyMatchString)

    if not preserveUnlikelyCandidates:
      for node in self.osoup.body.findAll(match_unlikely_candidates):
        dbg("Removing unlikely candidate - " + node.get('class', '') + node.get('id', ''))
        node.extract()

    # Turn all divs that don't have children block level elements into p's
    for node in self.osoup.body.findAll('div'):
      children = node.findAll(['a', 'blockquote', 'dl', 'div', 'img', 'ol', 'p', 'pre', 'table', 'ul'])
      if len(children) == 0:
        self.replace_element(self.osoup, node, 'p')
        dbg("Altering div to p")
      else:
        # experimental: replace text node with a p tag with the same content
        new_div = Tag(self.osoup, 'div', attrs=node.attrs)
        for c in [c for c in node.contents]:
          if isinstance(c, Comment):
            new_div.append(c)
          elif isinstance(c, NavigableString) and c.strip(' \n\t\r'):
            new_p = Tag(self.osoup, 'p', attrs=[('class', 'readability-styled'), ('style', 'display:inline;')])
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

    for paragraph in self.osoup.body.findAll('p'):
      parentNode      = paragraph.parent
      grandParentNode = parentNode.parent
      innerText       = self.get_inner_text(paragraph)

      # If this paragraph is less than 25 characters, don't even count it.
      if len(innerText) < 25:
        continue

      # Initialize readability data for the parent.
      if not getattr(parentNode, 'readability', None):
        self.initialize_node(parentNode)
        candidates.append(parentNode)

      # Initialize readability data for the grandparent.
      if not getattr(grandParentNode, 'readability', None):
        self.initialize_node(grandParentNode)
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
      dbg("before candidate found %s with contentScore: %d (%s:%s)" % (node.name, node.readability['contentScore'], node.get('class', ''), node.get('id', '')))
        
      node.readability['contentScore'] = node.readability['contentScore'] * (1-self.get_link_density(node))

      dbg('Candidate: ' + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ") with score " + str(node.readability['contentScore']))

      if not topCandidate or node.readability['contentScore'] > topCandidate.readability['contentScore']:
        topCandidate = node


    #
    # If we still have no top candidate, just use the body as a last resort.
    # We also have to copy the body node so it is something we can modify.
    #
    if not topCandidate or topCandidate.name == 'body':
      topCandidate = Tag(self.osoup, 'div')
      for c in self.osoup.body.contents:
        topCandidate.append(c)
      self.osoup.body.append(topCandidate)
      self.initialize_node(topCandidate)
      dbg('Candidate: ' + topCandidate.name + " ( ) with score " + topCandidate.readability['contentScore'])

    #
    # Now that we have the top candidate, look through its siblings for content that might also be related.
    # Things like preambles, content split by ads that we removed, etc.
    #
    articleContent = Tag(self.fsoup, 'div', attrs=[('id', 'readability-content')])
    siblingScoreThreshold = max(10, 0.2 * topCandidate.readability['contentScore'])
    
    for sibling in topCandidate.parent.contents:
      if not isinstance(sibling, Tag):
        continue

      dbg("Looking at sibling node: " + sibling.name + " (" + sibling.get('class', '') + ":" + sibling.get('id','') + ")")
      dbg("Sibling has score " + (str(sibling.readability['contentScore']) if getattr(sibling, 'readability') else 'Unknown'))

      append = (sibling == topCandidate)

      if getattr(sibling, 'readability') and sibling.readability['contentScore'] >= siblingScoreThreshold:
        append = True

      if sibling.name == "p":
        linkDensity = self.get_link_density(sibling)
        nodeContent = self.get_inner_text(sibling)
        nodeLength  = len(nodeContent)

        if nodeLength > 80 and linkDensity < 0.25:
          append = True
        elif nodeLength < 80 and linkDensity == 0 and unknownRe.match(nodeContent):
          append = True

      if append:
        dbg("Appending node: " + sibling.name + " (" + sibling.get('class', '') + ":" + sibling.get('id','') + ")" )

        # Append sibling and subtract from our list because it removes the node when you append to another node
        articleContent.append(sibling)

    #
    #So we have all of the content that we need. Now we clean it up for presentation.
    #
    self.prep_article(articleContent)

    return articleContent

  def prep_article(self, articleContent):
    self.clean_styles(articleContent)

    # this is better applied directly on the output string
    # self.kill_breaks(articleContent)

    self.clean(articleContent, 'form')
    self.clean(articleContent, 'object')
    self.clean(articleContent, 'h1')
    self.clean(articleContent, 'iframe')

    if len(articleContent.findAll('h2')) == 1:
      self.clean(articleContent, 'h2')

    for paragraph in articleContent.findAll('p'):
      imgCount = len(paragraph.findAll('img'))
      embedCount = len(paragraph.findAll(['embed', 'object']))
      if imgCount == 0 and embedCount == 0 and len(self.get_inner_text(paragraph)) == 0:
        paragraph.extract()
        
    self.clean_conditionally(articleContent, 'table')
    self.clean_conditionally(articleContent, 'ul')
    self.clean_conditionally(articleContent, 'div')
    

  def clean_styles(self, articleContent):
    for c in articleContent.contents:
      if isinstance(c, Tag):
        if c.get('class', '') != 'readability-styles' and c.has_key('style'):
          del c['style']
        self.clean_styles(c)
    
  def clean(self, articleContent, tag):
    is_embed = (tag in ('object', 'embed'))
    for c in articleContent.findAll(tag):
      if is_embed and videoRe.match(str(c)):
        continue
      c.extract()

  def clean_conditionally(self, articleContent, tag):
    for node in articleContent.findAll(tag):
      weight = self.get_class_weight(node)

      dbg("Cleaning Conditionally " + node.name + " (" + node.get('class', '') + ":" + node.get('id', '') + ")")
      dbg("Element has score " + (str(node.readability['contentScore']) if getattr(node, 'readability') else 'Unknown'))
      
      if weight < 0:
        node.extract()
      elif self.get_char_count(node, ',') < 10:
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
          if not videoRe.match(str(embed)):
            embedCount += 1

        linkDensity = self.get_link_density(node)
        contentLenght = len(self.get_inner_text(node))
        toRemove = False

        if img > p:
          toRemove = True
        elif li > p and tag != 'ul' and tag != 'ol':
          toRemove = True
        elif input > (p / 3):
          toRemove = True
        elif (contentLenght < 25) and (img == 0 or img > 2):
          toRemove = True
        elif weight < 25 and linkDensity > .2:
          toRemove = True
        elif weight >= 25 and linkDensity > .5:
          toRemove = True
        elif (embedCount == 1 and contentLenght < 75) or (embedCount > 1):
          toRemove = True

        if toRemove:
          node.extract()


  def get_char_count(self, node, separator=','):
    return len(self.get_inner_text(node).split(separator))
    
  def get_link_density(self, node):
    textLength = len(self.get_inner_text(node))
    linkLength = 0
    for l in node.findAll('a'):
      linkLength += len(self.get_inner_text(l))

    dbg("get_link_density for %s %d/%d with contentScore: %d (%s:%s)" % (node.name, linkLength, textLength, node.readability['contentScore'], node.get('class', ''), node.get('id', '')))
      
    if textLength == 0:
      return 1
    return float(linkLength) / textLength

  def initialize_node(self, node):
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

    dbg("initializeNode1: %s (%s:%s): %d " % (node.name, node.get('class', ''), node.get('id', ''), node.readability['contentScore']))
    node.readability['contentScore'] += self.get_class_weight(node)
    dbg("initializeNode2: %s (%s:%s): %d " % (node.name, node.get('class', ''), node.get('id', ''), node.readability['contentScore']))

  def get_class_weight(self, node):
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

    dbg("get_class_weight: %s (%s:%s): %d" % (node.name, class_name, node_id, weight))


    return weight  

  def get_inner_text(self, node, trimSpaces=True, normalizeSpaces=True):
    textContent = ''

    for c in node.contents:
      if isinstance(c, NavigableString):
        textContent = textContent + ' ' + c
      else:
        textContent = textContent + self.get_inner_text(c, trimSpaces=False, normalizeSpaces=False)

    if trimSpaces:
      textContent = trimRe.sub('', textContent)
    if normalizeSpaces:
      textContent = normalizeRe.sub(' ', textContent)
      
    return textContent

  def replace_element(self, soup, node, new_element):
    new_node = Tag(soup, new_element, attrs=node.attrs)
    for c in [c for c in node.contents]:
      new_node.append(c)
    node.replaceWith(new_node)

OUTPUT_BODY = """<html>
<body class='%(read_style)s'>
<div id='readOverlay' class='%(read_style)s'>
  <div id='readInner' class='%(read_margin)s %(read_size)s'>
  </div>
</div>
</body>
</html>"""

def dbg(msg):
  if __DEBUG__:
    print msg

if __name__ == '__main__':
  import sys
  import urllib2
  response = urllib2.urlopen(sys.argv[1])
  html = response.read()
  df = Readability(html)
  df.process_document()
  if __OUTPUT__:
    print df.get_html(prettyPrint=True)
