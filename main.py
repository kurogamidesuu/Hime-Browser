import sys
import tkinter
from network import URL
from browser_ui import Browser

if __name__ == "__main__":

  if len(sys.argv) < 2:
    input_url = ""
  else:
    input_url = sys.argv[1]

  try:
    url = URL(input_url)
  except:
    url = URL("about:blank")
  Browser().new_tab(url)
  tkinter.mainloop()