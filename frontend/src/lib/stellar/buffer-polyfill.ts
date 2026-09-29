/**
 * passkey-kit (and the base64url package it uses) expect Node's global `Buffer`. Imported first by the lazy
 * passkey chunk only, so the main bundle never carries it.
 */
import { Buffer } from 'buffer'

const scope = globalThis as unknown as { Buffer?: typeof Buffer }
scope.Buffer ??= Buffer
