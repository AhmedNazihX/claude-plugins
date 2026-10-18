// Every workflow script must open with `export const meta = {...}` naming the workflow (workflow tool contract).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const WORKFLOWS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'workflows')
const scripts = existsSync(WORKFLOWS) ? readdirSync(WORKFLOWS).filter((name) => name.endsWith('.js')) : []

test('every workflow script declares meta with a name and a description', () => {
  for (const name of scripts) {
    const source = readFileSync(join(WORKFLOWS, name), 'utf8')
    assert.match(source, /^export const meta = \{/, `${name} must start with export const meta`)
    assert.match(source, /name:\s*'[a-z-]+'/, `${name} meta needs a name`)
    assert.match(source, /description:\s*'/, `${name} meta needs a description`)
  }
})
