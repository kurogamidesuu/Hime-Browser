# Hime Browser

**Hime Browser** is a toy web browser engine built entirely from scratch in Python. It was developed following the architectural concepts and educational journey from the incredible [Web Browser Engineering](https://browser.engineering/) book.

This project is a deep dive into the inner workings of web browsers. It bypasses standard web view components and GUI frameworks, implementing everything from the ground up: raw socket HTTP networking, HTML parsing, DOM tree generation, CSS styling, a custom layout engine, and a multi-threaded, GPU-accelerated rendering pipeline.



## Tech Stack

* **Language:** Python 3
* **Graphics & Windowing:** SDL2 (`pysdl2`) & OpenGL (`PyOpenGL`)
* **Rendering Engine:** Skia (`skia-python`)
* **JavaScript Engine:** Duktape (via `dukpy` bindings)

## Features Implemented

* **Networking:** HTTP request handling and parsing directly over raw sockets.
* **Parsing:** Custom HTML and CSS parsers to build the DOM and CSSOM trees.
* **Layout Engine:** Block and Inline layout calculations, including text measuring, wrapping, and absolute positioning.
* **Multi-threaded Rendering:** A modern, multi-threaded rendering pipeline featuring Display Lists, Compositing, and GPU Rasterization.
* **Interactivity:** Mouse clicks, scrolling, and keyboard focus handling.
* **Accessibility:** Generation of an Accessibility Tree for screen-reader compatibility.
* **Tabs & Chrome:** Basic browser UI ("Chrome") with an address bar and tab state management.

## How to Run Locally

If you want to test the browser, explore the architecture, or contribute, follow these steps to get it running on your local machine.

### Prerequisites
* Python 3.8 or higher installed on your system.
* Git.

### Setup Instructions

1. **Clone the repository:**

   ```bash
   git clone https://github.com/kurogamidesuu/Hime-Browser.git
   cd Hime-Browser
   ```

2. **Create a virtual environment (Recommended):**

   ```bash
   python -m venv .venv

   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies:**

   Make sure you have the required libraries installed via the ` requirements.txt ` file.

   ```bash
   pip install -r requirements.txt
   ```

4. **Launch the browser:**

   Run the main script and pass a URL to load. (The Web Browser Engineering site is a great test page!)

   ```bash
   python main.py https://browser.engineering/
   ```

## Project Architecture Overview

For those interested in the code, here is a quick map of the core engine components:
- `main.py` & `browser_ui.py`: Initializes the SDL2 window, Skia context, and manages the main event loop, UI Chrome, and multi-threading locks.

- `network.py`: Handles socket connections, HTTP headers, and caching.

- `dom.py` & `css.py`: Parses raw text into structured DOM and CSSOM nodes.

- `layout.py`: The math-heavy core that computes the absolute X/Y coordinates and dimensions for every node on the screen.

- `draw.py` & `task.py`: Manages the conversion of layout nodes into Skia drawing commands, layers, and asynchronous background tasks.

## Contributing
Contributions, discussions, and optimizations are welcome! Feel free to open an issue or submit a pull request if you want to help improve the layout engine, fix concurrency bugs, or add new CSS properties.
