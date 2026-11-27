try {
  const theme = localStorage.getItem("theme")
  if (theme === "light" || theme === "dark") {
    document.documentElement.classList.add(theme)
    for (const meta of document.querySelectorAll('meta[name="theme-color"][data-scheme]')) {
      meta.media = meta.dataset.scheme === theme ? "all" : "not all"
    }
  }
} catch (error) {
  if (!(error instanceof DOMException)) {
    throw error
  }
}
