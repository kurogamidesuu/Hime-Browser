import html

def print_tree(node, indent=0):
  from layout import ProtectedField

  print(' ' * indent, node)
  children = node.children
  if isinstance(children, ProtectedField):
    children = children.get()
  for child in children:
    print_tree(child, indent + 2)

def tree_to_list(tree, list):
  from layout import ProtectedField

  list.append(tree)
  children = tree.children
  if isinstance(children, ProtectedField):
    children = children.get()

  for child in children:
    tree_to_list(child, list)
  return list

class Text:
  def __init__(self, text, parent):
    self.text = text
    self.children = []
    self.parent = parent
    self.style = None
    self.is_focused = False
    self.animations = {}
    self.layout_object = None
  
  def __repr__(self):
    return repr(self.text)

class Element:
  def __init__(self, tag, attributes, parent):
    self.tag = tag
    self.attributes = attributes
    self.children = []
    self.parent = parent
    self.style = None
    self.is_focused = False
    self.animations = {}
    self.layout_object = None

  def __repr__(self):
    return "<" + self.tag + ">"
  
class HTMLParser:
  SELF_CLOSING_TAGS = [
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
  ]
  HEAD_TAGS = [
    "base", "basefont", "bgsound", "noscript",
    "link", "meta", "title", "style", "script",
  ]
  def __init__(self, body):
    self.body = body
    self.unfinished = []

  def parse(self):
    buffer = ""
    in_tag = False
    in_script = False
    
    body = self.body
    i = 0
    while i < len(body):
      if body.startswith("<!--", i):
        i = body.find("-->", i)

        if i == -1:break

        i += 3
        continue
      
      c = body[i]

      if c == "<":
        if in_script:
          if body[i:i+9].casefold() == "</script>":
            in_script = False
            in_tag = True
            if buffer: self.add_text(buffer)
            buffer = ""
          else:
            buffer += c
        else:
          in_tag = True
          if buffer: self.add_text(buffer)
          buffer = ""
      elif c == ">":
        in_tag = False
        self.add_tag(buffer)

        parts = buffer.split()
        tag_name = parts[0].casefold() if parts else ""

        if tag_name == "script":
          in_script = True

        buffer = ""
      else:
        buffer += c
      
      i += 1
    
    if not in_tag and buffer:
      self.add_text(buffer)

    return self.finish()
  
  def add_text(self, text):
    if text.isspace():
      in_pre = False
      for node in self.unfinished:
        if node.tag == "pre":
          in_pre = True
          break
      
      if not in_pre:
        return
      
    text = html.unescape(text)
    self.implicit_tags(None)
    parent = self.unfinished[-1]
    node = Text(text, parent)
    parent.children.append(node)
  
  def add_tag(self, tag):
    if not tag.strip(): 
      return
    
    tag, attributes = self.get_attributes(tag)
    if tag.startswith("!"): return
    self.implicit_tags(tag)
    if tag == "p":
      if any(n.tag == "p" for n in self.unfinished):
        self.add_tag("/p")
    elif tag == "li":
      for n in reversed(self.unfinished):
        if n.tag == "li":
          self.add_tag("/li")
          break
        if n.tag in ["ul", "ol"]:
          break

    if tag.startswith("/"):
      if len(self.unfinished) == 1: return

      closing_tag = tag[1:]
      open_tags = [n.tag for n in self.unfinished]

      if closing_tag in open_tags:
        while True:
          node = self.unfinished.pop()
          parent = self.unfinished[-1]
          parent.children.append(node)
          if node.tag == closing_tag:
            break
      return
    elif tag in self.SELF_CLOSING_TAGS:
      parent = self.unfinished[-1]
      node = Element(tag, attributes, parent)
      parent.children.append(node)
    else:
      parent = self.unfinished[-1] if self.unfinished else None
      node = Element(tag, attributes, parent)
      self.unfinished.append(node)

  def finish(self):
    if not self.unfinished:
      self.implicit_tags(None)
    while len(self.unfinished) > 1:
      node = self.unfinished.pop()
      parent = self.unfinished[-1]
      parent.children.append(node)
    return self.unfinished.pop()
  
  def get_attributes(self, text):
    parts = text.split()
    tag = parts[0].casefold()
    attributes = {}
    for attrpair in parts[1:]:
      if "=" in attrpair:
        key, value = attrpair.split("=", 1)
        if len(value) > 2 and value[0] in ["'", "\""]:
          value = value[1:-1]
        attributes[key.casefold()] = value
      else:
        attributes[attrpair.casefold()] = ""
    return tag, attributes
  
  def implicit_tags(self, tag):
    while True:
      open_tags = [node.tag for node in self.unfinished]
      if open_tags == [] and tag != "html":
        self.add_tag("html")
      elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
        if tag in self.HEAD_TAGS:
          self.add_tag("head")
        else:
          self.add_tag("body")
      elif open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS:
        self.add_tag("/head")
      else:
        break
