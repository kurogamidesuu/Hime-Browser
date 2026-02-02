import skia

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
INPUT_WIDTH_PX = 200
REFRESH_RATE_SEC = 0.033
SHOW_COMPOSITED_LAYER_BORDERS = False
BROKEN_IMAGE = skia.Image.open("Broken_Image.png")
IFRAME_WIDTH_PX = 300
IFRAME_HEIGHT_PX = 150

COOKIE_JAR = {}

BLOCK_ELEMENTS = [
  "html", "body", "article", "section", "nav", "aside",
  "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "header",
  "footer", "address", "p", "hr", "pre", "blockquote",
  "ol", "ul", "menu", "li", "dl", "dt", "dd", "figure",
  "figcaption", "main", "div", "table", "form", "fieldset",
  "legend", "details", "summary"
]

INHERITED_PROPERTIES = {
  "font-size": "16px",
  "font-style": "normal",
  "font-weight": "normal",
  "color": "black",
}

NAMED_COLORS = {
  "black": "#000000",
  "gray":  "#808080",
  "white": "#ffffff",
  "red":   "#ff0000",
  "green": "#00ff00",
  "blue":  "#0000ff",
  "lightblue": "#add8e6",
  "lightgreen": "#90ee90",
  "orange": "#ffa500",
  "orangered": "#ff4500",
}