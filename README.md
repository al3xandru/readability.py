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

# Todo

* multi-pages:
    - http://www.washingtonpost.com/wp-dyn/content/article/2010/09/25/AR2010092503767.html
    - http://www.theregister.co.uk/2010/09/24/google_percolator/
    - http://cloud.gigaom.com/2010/09/13/sensor-networks-top-social-networks-for-big-data/ [fail]
* better titles
    - http://www.links.org/?p=998
    - http://www.infoq.com/interviews/thorup-virding-erlangvm
    - http://www.theregister.co.uk/2010/09/24/google_percolator/
* [do not work yet]
    - http://scripting.com/stories/2010/09/16/theArchitectureOfRss.html
    - http://static.intelie.com.br/qconsp2010/presentation.html#slide1
