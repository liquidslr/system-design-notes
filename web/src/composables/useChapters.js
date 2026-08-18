import manifest from '../data/chapters.json'

export function useChapters() {
  const chapters = manifest.chapters

  function getChapter(id) {
    return chapters.find((c) => c.id === id)
  }

  function getAdjacent(id) {
    const index = chapters.findIndex((c) => c.id === id)
    return {
      prev: index > 0 ? chapters[index - 1] : null,
      next: index >= 0 && index < chapters.length - 1 ? chapters[index + 1] : null,
    }
  }

  return { manifest, chapters, getChapter, getAdjacent }
}
