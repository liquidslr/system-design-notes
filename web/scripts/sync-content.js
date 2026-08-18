import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '../..')
const contentDir = path.resolve(__dirname, '../public/content')
const dataDir = path.resolve(__dirname, '../src/data')

function slugify(folderName) {
  const match = folderName.match(/^(\d+)\.\s*(.+)$/)
  if (!match) return folderName.toLowerCase().replace(/\s+/g, '-')
  const num = match[1]
  const title = match[2].trim().toLowerCase().replace(/\s+/g, '-')
  return `${num}-${title}`
}

function findReadme(dir) {
  for (const name of ['Readme.md', 'README.md']) {
    const file = path.join(dir, name)
    if (fs.existsSync(file)) return name
  }
  return null
}

function copyRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true })
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name)
    const destPath = path.join(dest, entry.name)
    if (entry.isDirectory()) {
      copyRecursive(srcPath, destPath)
    } else {
      fs.copyFileSync(srcPath, destPath)
    }
  }
}

function extractTitle(markdown, fallback) {
  const match = markdown.match(/^#\s+(.+)$/m)
  return match ? match[1].trim() : fallback
}

fs.rmSync(contentDir, { recursive: true, force: true })
fs.mkdirSync(contentDir, { recursive: true })
fs.mkdirSync(dataDir, { recursive: true })

const chapters = []
const entries = fs.readdirSync(repoRoot, { withFileTypes: true })

for (const entry of entries) {
  if (!entry.isDirectory() || !/^\d+\.\s/.test(entry.name)) continue

  const srcDir = path.join(repoRoot, entry.name)
  const readme = findReadme(srcDir)
  if (!readme) continue

  const slug = slugify(entry.name)
  const destDir = path.join(contentDir, slug)
  copyRecursive(srcDir, destDir)

  const markdown = fs.readFileSync(path.join(srcDir, readme), 'utf-8')
  const chapterNum = parseInt(entry.name.match(/^(\d+)/)[1], 10)

  chapters.push({
    id: slug,
    number: chapterNum,
    folder: entry.name,
    title: extractTitle(markdown, entry.name.replace(/^\d+\.\s*/, '')),
    readme,
  })
}

chapters.sort((a, b) => a.number - b.number)

const manifest = {
  title: 'System Design Interview Notes',
  subtitle: 'An interactive guide based on Alex Xu\'s System Design Interview (Vol 1 & 2)',
  source: 'https://github.com/kikikimbing/system-design-notes',
  chapters,
}

fs.writeFileSync(path.join(dataDir, 'chapters.json'), JSON.stringify(manifest, null, 2))
console.log(`Synced ${chapters.length} chapters to public/content/`)
