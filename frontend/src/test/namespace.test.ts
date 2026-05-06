import { describe, it, expect } from 'vitest'

// Test the namespacing convention used by the backend
const SEP = '__'

function namespaceTool(server: string, tool: string) {
  return `${server}${SEP}${tool}`
}

function extractServer(namespaced: string): [string, string] | null {
  if (!namespaced.includes(SEP)) return null
  const idx = namespaced.indexOf(SEP)
  return [namespaced.slice(0, idx), namespaced.slice(idx + SEP.length)]
}

describe('tool namespacing convention', () => {
  it('creates namespaced tool names', () => {
    expect(namespaceTool('my-server', 'search')).toBe('my-server__search')
  })

  it('extracts server and tool from namespaced name', () => {
    expect(extractServer('my-server__search')).toEqual(['my-server', 'search'])
  })

  it('returns null for non-namespaced names', () => {
    expect(extractServer('plain_tool')).toBeNull()
  })

  it('handles tools with underscores', () => {
    expect(extractServer('srv__get_user_info')).toEqual(['srv', 'get_user_info'])
  })
})
