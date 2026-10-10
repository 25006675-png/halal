# Halalah landing page and live demo

`index.html` is the built, self-contained page: the landing page plus the 3-tab live demo at `#demo` (Input, Agents, Application Pack). Open it in a browser; it needs no server.

To rebuild after editing anything in `src/`:

```
python3 build.py
```

`build.py` joins `src/head.html`, the CSS in `src/css/`, `src/body.html` and the JS in `src/js/` into one HTML file under `dist/`.
