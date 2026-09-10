import { Camera } from '@phosphor-icons/react'

/**
 * App shell -- Story 1.1 scope only. Proves the token set, the two
 * declared font families, and a Phosphor icon are wired end to end:
 * an app-bar (navy fill, white content, accent bottom stripe) with
 * one Phosphor icon at `regular` weight, and one `button-primary`
 * (accent fill, navy text). Scan capture, results, and admin screens
 * are later stories.
 */
function App() {
  return (
    <>
      <header className="app-bar">
        <Camera size={24} weight="regular" className="app-bar__icon" aria-hidden="true" />
        <h1 className="app-bar__title">Rocell Tile Scanner</h1>
      </header>
      <main>
        <button type="button" className="button-primary">
          Scan
        </button>
      </main>
    </>
  )
}

export default App
