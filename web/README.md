# System Design Notes — Web App

Interactive Vue/Vite web app for browsing the [system-design-notes](https://github.com/kikikimbing/system-design-notes) markdown content with sidebar navigation, chapter cards, and dark mode.

## Stack

- **Vue 3** + **Vite**
- **Naive UI** component library
- **markdown-it** + **highlight.js** for rendering

## Development

```bash
cd web
npm install
npm run dev
```

The `sync` script runs automatically before `dev` and `build`, copying chapter markdown and images from the repo root into `public/content/`.

## Production build

```bash
npm run build
npm run preview
```

Output goes to `dist/` and can be deployed to any static host (GitHub Pages, Netlify, Vercel, etc.).

## Project structure

```
web/
├── scripts/sync-content.js   # Copies chapters → public/content, generates manifest
├── public/content/           # Synced markdown + images (generated)
├── src/
│   ├── components/           # Sidebar, MarkdownViewer
│   ├── views/                # Home, Chapter pages
│   ├── composables/          # Chapter data, markdown rendering
│   └── data/chapters.json    # Generated chapter manifest
```
