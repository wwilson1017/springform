# Springform brand

The mark is a foundation of app tiles. One tile has left its place, which stays behind as a faded copper
tile, and a three-stroke spring lifts it off the foundation as a copper circle:
the platform stays, what you build on it comes alive. The foundation is ink (cream on dark pages);
everything that moves is copper.

Files, all the same drawing:

- `springform-mark.svg` follows the viewer's light or dark setting.
- `springform-icon.svg` is the mark in cream on a copper badge, for browser tabs and app icons,
  where the bare mark disappears against the tab colour. The favicons (`frontend/public/favicon.svg`,
  `site/favicon.svg`) are copies of it.
- `springform-mark-light.svg` (ink foundation) and `springform-mark-dark.svg` (cream foundation) are
  for places that pick a version themselves, such as the README's `<picture>`.

The wordmark is the word **springform** set in the system sans, lowercase, weight 700,
letter-spacing -0.02em, placed 0.4em to the right of the mark and matched to the mark's height.
There is no wordmark file on purpose: every surface that shows the name already has the font.

## Colours

| Name | Light | Dark | Use |
|---|---|---|---|
| Cream | `#f1f1e8` | `#1c1b19` | page background (the app's `--color-sf-bg`) |
| Ink | `#292929` | the app's dark `--color-sf-ink` | text |
| Copper, fill | `#b5542d` | `#b5542d` | the mark, buttons, borders, bars |
| Copper, text | `#9a4322` | `#e4916a` | copper painted as a glyph |

Copper text on cream is 5.7:1, white on copper fill is 4.9:1, and dark copper text on the dark
page is 7.1:1 (all WCAG AA). The app's status hues (green, amber, red) and the assistant blue are
not brand colours and stay as they are.

## Words

- One-liner: an open-source foundation for small-business software. One SQLite file, one
  container, apps on a launcher, a private fork per client.
- Headline: Small-business software, minus the plumbing.
- Motto: Fork it. Bake it. Release it.

Voice: short sentences, plain words, say what it does not do. One kitchen metaphor per page at
most; the product is software, the pan is only the name.

## Do and don't

- Keep the foundation ink on cream, or cream on the dark page, and the moving parts copper; a
  one-colour ink version is fine in print.
- Keep clear space of a quarter of the mark's width around it.
- Do not recolour the mark, add a gradient, rotate it, mirror it, or straighten the spring.
- Below 24 pixels the spring blurs into a short bar; that is expected, do not redraw it.
- Write Springform in prose and springform in the lockup, never SpringForm or Spring Form.

Where it is used: the two favicons (the badge), `site/index.html` (inline, so it follows the page's own
colours), and the README.
