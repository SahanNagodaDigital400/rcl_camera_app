import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App shell', () => {
  it('renders the app bar with a title', () => {
    render(<App />)

    expect(screen.getByRole('banner')).toHaveClass('app-bar')
    expect(screen.getByRole('heading', { name: 'Rocell Tile Scanner' })).toBeInTheDocument()
  })

  it('renders a Phosphor icon in the app bar', () => {
    const { container } = render(<App />)

    const icon = container.querySelector('.app-bar__icon')
    expect(icon).toBeInTheDocument()
    expect(icon?.tagName.toLowerCase()).toBe('svg')
  })

  it('renders one primary button', () => {
    render(<App />)

    const button = screen.getByRole('button', { name: 'Scan' })
    expect(button).toBeInTheDocument()
    expect(button).toHaveClass('button-primary')
  })
})
