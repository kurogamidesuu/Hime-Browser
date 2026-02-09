import socket
import ssl
import os
import html
import time
import gzip
from constants import COOKIE_JAR

SOCKETS = {}
CACHE = {}

class URL:
  def __init__(self, url):
    self.view_source = False
    try:
      self.scheme, url = url.split(":", 1)
      assert self.scheme in ["http", "https", "file", "data", "view-source"]

      if self.scheme == "view-source":
        self.view_source = True
        self.scheme, url = url.split(":", 1)

      if self.scheme == "data":
        self.mime_type, self.content = url.split(",", 1)
        return

      _, url = url.split("//", 1)

      if self.scheme == "file":
        _, self.path = url.split("/", 1)
        return
      
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
      
      self.headers = {
        "Connection": "keep-alive",
        "User-Agent": "Hempushp's Browser 1.0",
        "Accept-Encoding": "gzip"
      }

    except Exception:
      print("Malformed URL found")
      print("  URL was: " + str(url))
      self.__init__("file:///C:/Coding/Projects/Web-Browser-Engineering/hello-browser.html")
  
  def resolve(self, url):
    if "://" in url: return URL(url)

    if self.scheme == "data":
      return URL(url)

    if not url.startswith("/"):
      dir, _ = self.path.rsplit("/", 1)
      while url.startswith("../"):
        _, url = url.split("/", 1)
        if "/" in dir:
          dir, _ = dir.rsplit("/", 1)
      url = dir + "/" + url

    if self.scheme == "file":
      return URL(self.scheme + "://" + url)
    
    if url.startswith("//"):
      return URL(self.scheme + ":" + url)
    else:
      return URL(self.scheme + "://" + self.host + ":" + str(self.port) + url)

  def request(self, referrer, payload=None):
    if self.scheme == "file":
      path = os.path.normpath(self.path)
      with open(path, "rb") as f:
        body = f.read()
      
      if self.view_source:
        text = body.decode("utf8", "replace")
        body = html.escape(text).encode("utf8")
      
      return {}, body
      
    if self.scheme == "data":
      body = str(self.content).encode("utf8")

      if self.view_source:
        text = body.decode("utf8", "replace")
        body = html.escape(text).encode("utf8")

      return {}, body
    
    url = self.__str__()
    if url in CACHE:
      cached_response_headers, cached_content, cached_timestamp = CACHE[url]
      max_age = self.get_maxage(cached_response_headers)

      if (time.time() - cached_timestamp) < max_age:
        if self.view_source:
          text = cached_content.decode("utf8", "replace")
          return cached_response_headers, html.escape(text).encode("utf8")
        return cached_response_headers, cached_content

    key = (self.scheme, self.host, self.port)

    if key in SOCKETS:
      s = SOCKETS[key]
    else:
      s = self.new_socket()      
      SOCKETS[key] = s

    method = "POST" if payload else "GET"
    body = "{} {} HTTP/1.1\r\n".format(method, self.path)
    body += "Host: {}\r\n".format(self.host)
    for header, value in self.headers.items():
      body += "{}: {}\r\n".format(header, value)

    if self.host in COOKIE_JAR:
      cookie, params = COOKIE_JAR[self.host]
      allow_cookie = True
      if referrer and params.get("samesite", "none") == "lax":
        if method != "GET":
          allow_cookie = self.host == referrer.host
      if allow_cookie:
        body += "Cookie: {}\r\n".format(cookie)

    if payload:
      content_length = len(payload.encode("utf8"))
      body += "Content-Length: {}\r\n".format(content_length)

    body += "\r\n"
    if payload: body += payload

    try:
      s.send(body.encode("utf8"))
    except:
      s.close()
      if key in SOCKETS:
        del SOCKETS[key]
      s = self.new_socket()
      SOCKETS[key] = s
      s.send(body.encode("utf8"))

    response = s.makefile("rb")

    statusline = response.readline().decode("utf8")
    if not statusline:
      s.close()
      if key in SOCKETS:
        del SOCKETS[key]
      return self.request(referrer, payload)
    
    version, status, explanation = statusline.split(" ", 2)

    response_headers = {}
    while True:
      line = response.readline().decode("utf8")
      if line == "\r\n": break
      header, value = line.split(":", 1)
      response_headers[header.casefold()] = value.strip()

    if int(status) in range(300, 400):
      content_length = int(response_headers.get("content-length", 0))
      response.read(content_length)

      location = response_headers.get("location")
      new_url = self.resolve(location)

      return new_url.request(referrer, payload)

    if "set-cookie" in response_headers:
      cookie = response_headers["set-cookie"]
      params = {}
      if ";" in cookie:
        cookie, rest = cookie.split(";", 1)
        for param in rest.split(";"):
          if "=" in param:
            param, value = param.split("=", 1)
          else:
            value = "true"
          params[param.strip().casefold()] = value.casefold()
      COOKIE_JAR[self.host] = (cookie, params)

    content = b""
    if response_headers.get("transfer-encoding") == "chunked":
      while True:
        line = response.readline()
        chunk_size = int(line, 16)

        if chunk_size == 0:
          response.read(2)
          break

        chunked_content = response.read(chunk_size)
        content += chunked_content
        response.read(2)
    else:
      content = response.read(int(response_headers.get("content-length", 0)))

    if response_headers.get("content-encoding") == "gzip":
      content = gzip.decompress(content)

    if response_headers.get("connection") == "close":
      s.close()
      if key in SOCKETS:
        del SOCKETS[key]

    max_age = self.get_maxage(response_headers)
    if max_age > 0:
      CACHE[url] = (response_headers, content, time.time())

    if self.view_source:
      text = content.decode("utf8", "replace")
      content = html.escape(text).encode("utf8")

    return response_headers, content
  
  def new_socket(self):
    s = socket.socket(
      family=socket.AF_INET,
      type=socket.SOCK_STREAM,
      proto=socket.IPPROTO_TCP,
    )
    s.connect((self.host, self.port))

    if self.scheme == "https":
      ctx = ssl.create_default_context()
      s = ctx.wrap_socket(s, server_hostname=self.host)
    
    return s
  
  def origin(self):
    if self.scheme == "file":
      return self.scheme + "://" + self.path
    if self.scheme == "data":
      return self.scheme + ":" + self.mime_type + "," + self.content
    return self.scheme + "://" + self.host + ":" + str(self.port)
  
  def get_maxage(self, headers):
    if "cache-control" not in headers:
      return 0
    
    cache_header = headers["cache-control"]

    for part in cache_header.split(","):
      part = part.strip()
      if part.startswith("max-age="):
        try:
          return int(part.split("=", 1)[1])
        except:
          return 0
    
    return 0
  
  def __str__(self):
    if self.scheme == "file":
      return self.scheme + "://" + str(os.path.normpath(self.path)).replace("\\", "/")
    if self.scheme == "data":
      return self.scheme + ":" + str(self.mime_type) + "," + str(self.content)
    port_part = ":" + str(self.port)
    if self.scheme == "https" and self.port == 443:
      port_part = ""
    if self.scheme == "http" and self.port == 80:
      port_part = ""
    return self.scheme + "://" + self.host + port_part + self.path