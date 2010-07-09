# About

readability.py is a Python port of the [Arc90's JavaScript-based implementation](http://code.google.com/p/arc90labs-readability).

# Requirements

Current module requires [BeautifulSoup](http://www.crummy.com/software/BeautifulSoup/)

# Usage

    readability = Readability(html)
    readability.processDocument()
    readability.get_html()

Readability accepts a couple of parameters:
- read_style: ('style-newspaper', 'style-novel', 'style-athelas', 'style-ebook', 'style-apertura')
- read_margin: ('margin-x-narrow', 'margin-narrow', 'margin-medium', 'margin-wide', 'margin-x-wide')
- read_size: ('size-x-small', 'size-small', 'size-medium', 'size-large', 'size-x-large')

For output:
- prettyPrint: a nice formatting flag
- removeComments: remove all HTML comments from the generated output

# License

Readability.py is licensed under Apache License, Version 2.0

