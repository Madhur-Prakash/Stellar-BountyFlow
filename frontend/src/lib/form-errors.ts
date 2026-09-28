import type { FieldValues, Path, UseFormSetError } from 'react-hook-form'

import { errorMessage, isApiError } from '@/lib/api/client'

/**
 * Maps a `validation_error` envelope onto react-hook-form fields.
 * Returns a message for the form-level alert when something could not be
 * attached to a visible field (or for non-validation errors).
 */
export function applyApiErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly Path<T>[],
): string | null {
  if (isApiError(error) && error.code === 'validation_error') {
    const entries = Object.entries(error.fieldErrors)
    let unmatched = entries.length === 0
    for (const [field, message] of entries) {
      const key = field.split('.').pop() as Path<T>
      if (fields.includes(key)) setError(key, { type: 'server', message })
      else unmatched = true
    }
    return unmatched ? errorMessage(error) : null
  }
  return errorMessage(error)
}
