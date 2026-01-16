import socket
import ssl

class URL:
  def __init__(self, url):
    try:
      self.scheme, url = url.split("://", 1)
      assert self.scheme in ["http", "https"]

      if "/" not in url:
        url = url + "/"
      self.host, url = url.split("/", 1)
      self.path = "/" + url

      if self.scheme == "http":
        self.port = 80
      elif self.scheme == "https":
        self.port = 443

      if ":" in self.host:
        self.host, port = self.host.split(":", 1)
        self.port = int(port)
    except:
      print("Malformed URL found, falling back to the Web Browser Engineering home page.")
      print("  URL was: " + url)
      self.__init__("https://browser.engineering")
  
  def resolve(self, url):
    if "://" in url: return URL(url)
    if not url.startswith("/"):
      dir, _ = self.path.rsplit("/", 1)
      while url.startswith("../"):
        _, url = url.split("/", 1)
        if "/" in dir:
          dir, _ = dir.rsplit("/", 1)
      url = dir + "/" + url
    if url.startswith("//"):
      return URL(self.scheme + ":" + url)
    else:
      return URL(self.scheme + "://" + self.host + ":" + str(self.port) + url)

  def request(self, payload=None):
    s = socket.socket(
      family=socket.AF_INET,
      type=socket.SOCK_STREAM,
      proto=socket.IPPROTO_TCP,
    )
    s.connect((self.host, self.port))

    if self.scheme == "https":
      ctx = ssl.create_default_context()
      s = ctx.wrap_socket(s, server_hostname=self.host)

    method = "POST" if payload else "GET"
    request = "{} {} HTTP/1.0\r\n".format(method, self.path)
    if payload:
      length = len(payload.encode("utf8"))
      request += "Content-Length: {}\r\n".format(length)
    request += "Host: {}\r\n".format(self.host)
    request += "\r\n"
    if payload: request += payload
    s.send(request.encode("utf8"))
    response = s.makefile("r", encoding="utf8", newline="\r\n")

    statusline = response.readline()
    version, status, explanation = statusline.split(" ", 2)

    response_headers = {}
    while True:
      line = response.readline()
      if line == "\r\n": break
      header, value = line.split(":", 1)
      response_headers[header.casefold()] = value.strip()

    assert "transfer-encoding" not in response_headers
    assert "content-encoding" not in response_headers

    content = response.read()
    s.close()
    return content
  
  def __str__(self):
    port_part = ":" + str(self.port)
    if self.scheme == "https" and self.port == 443:
      port_part = ""
    if self.scheme == "http" and self.port == 80:
      port_part = ""
    return self.scheme + "://" + self.host + port_part + self.path