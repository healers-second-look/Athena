# Stitch design comps — Athena chat surface

Static HTML comps produced with Google Stitch during the design of the chat
interface (issue #103, PR #106). Kept for reference: they record the intended
visual language — the sage/periwinkle/apricot palette on warm parchment, the
Newsreader/Inter pairing, 12px cards with soft elevation.

## These are not code

They were previously checked in under `web/src/stitch-screens/`, inside the
Vite source tree, where nothing imported them and nothing built them. That
placement was misleading in a specific way: a comp that lives next to the
components it depicts reads as a source of truth, and comps do not track the
code they inspired. They are a snapshot of an intent, not a description of
what shipped.

The implemented UI is the authority:

| Comp | What actually ships it |
|---|---|
| `landing.html` | `web/src/routes/ChatLanding.jsx` |
| `chat.html` | `web/src/routes/ChatInterface.jsx`, `web/src/components/GraphViewer.jsx` |
| both | `web/src/styles/chat.css` |

If a comp and the implementation disagree, the implementation is what users
see. Update the comp or delete it; do not "fix" the code to match a picture
without checking that the picture is still the intent.

Open either file directly in a browser — they are self-contained and need no
build step.
