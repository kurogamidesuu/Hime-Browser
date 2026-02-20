# Hime Browser 🌐

A toy web browser engine built entirely from scratch in Python, following the architecture from [Web Browser Engineering](https://browser.engineering/). 

This project implements everything from raw socket HTTP requests and HTML parsing to a full layout engine and GPU-accelerated rendering.

## Tech Stack
* **Language:** Python 3
* **Graphics/Windowing:** SDL2 (`pysdl2`) & OpenGL
* **Rendering Engine:** Skia (`skia-python`)
* **JS Engine:** Duktape (via custom bindings)

## Features Implemented
* HTTP networking and HTML/CSS parsing
* DOM and CSSOM tree construction
* Block and Inline layout engine
* Multi-threaded rendering pipeline (Display Lists, Compositing, Rasterization)
* Accessibility tree generation

## How to Run
1. Clone the repo
2. Install dependencies: `pip install pysdl2 skia-python PyOpenGL`
3. Run the browser:
   ```bash
   python main.py https://browser.engineering/
