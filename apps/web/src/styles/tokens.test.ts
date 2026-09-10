import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// Guards the story's core invariant: tokens.css is the ONLY place raw
// color values may appear in apps/web -- every other stylesheet must
// reference a `var(--token-name)` instead. Without this, a future edit
// could silently reintroduce a hardcoded color and neither `tsc` nor
// eslint (which don't parse .css) would catch it.
const stylesDir = dirname(fileURLToPath(import.meta.url))
const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(/g

describe('design tokens are the single source of raw color values', () => {
  const otherCssFiles = readdirSync(stylesDir).filter(
    (file) => file.endsWith('.css') && file !== 'tokens.css',
  )

  it('found at least one non-token stylesheet to check', () => {
    expect(otherCssFiles.length).toBeGreaterThan(0)
  })

  it.each(otherCssFiles)('%s contains no raw hex/rgb(a) color values', (file) => {
    const content = readFileSync(join(stylesDir, file), 'utf-8')
    expect(content.match(RAW_COLOR)).toBeNull()
  })
})
