import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const assets = join(process.cwd(), 'dist', 'assets')
const scripts = readdirSync(assets).filter((name) => name.endsWith('.js'))
const initial = scripts.find((name) => name.startsWith('index-'))
if (!initial) throw new Error('Initial dashboard chunk was not produced.')

const initialBytes = statSync(join(assets, initial)).size
const largest = scripts.map((name) => [name, statSync(join(assets, name)).size]).sort((a, b) => b[1] - a[1])[0]
const INITIAL_BUDGET = 250_000
const CHUNK_BUDGET = 500_000

if (initialBytes > INITIAL_BUDGET) {
  throw new Error(`Initial chunk ${initial} is ${initialBytes} bytes; budget is ${INITIAL_BUDGET}.`)
}
if (largest[1] > CHUNK_BUDGET) {
  throw new Error(`Chunk ${largest[0]} is ${largest[1]} bytes; budget is ${CHUNK_BUDGET}.`)
}
process.stdout.write(`Bundle budgets passed: initial=${initialBytes} bytes, largest=${largest[1]} bytes.\n`)
