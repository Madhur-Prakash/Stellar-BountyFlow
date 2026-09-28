import { z } from 'zod'

export const USERNAME_RE = /^[a-z0-9_-]{3,30}$/
export const PASSWORD_MIN = 10
export const PASSWORD_MAX = 128

const email = z
  .string()
  .trim()
  .min(1, 'Enter your email address.')
  .pipe(z.email('Enter a valid email address.'))

/** Mirrors the API's rules so users see problems before submitting. */
const password = z
  .string()
  .min(PASSWORD_MIN, `Use at least ${PASSWORD_MIN} characters.`)
  .max(PASSWORD_MAX, `Use at most ${PASSWORD_MAX} characters.`)
  .refine((v) => v.trim() === v, 'Don’t start or end the password with a space.')
  .refine(
    (v) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length >= 2,
    'Mix at least two of: lowercase, uppercase, numbers, symbols.',
  )

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Enter your password.'),
})
export type LoginValues = z.infer<typeof loginSchema>

export const registerSchema = z
  .object({
    email,
    username: z
      .string()
      .trim()
      .min(3, 'Usernames are 3–30 characters.')
      .max(30, 'Usernames are 3–30 characters.')
      .regex(USERNAME_RE, 'Use only lowercase letters, numbers, underscores, and hyphens.'),
    display_name: z.string().trim().min(1, 'Enter a display name.').max(60, 'Keep it under 60 characters.'),
    password,
    confirm_password: z.string(),
    accept_terms: z.boolean().refine((v) => v, 'You need to accept the terms to continue.'),
  })
  .refine((v) => v.password === v.confirm_password, {
    path: ['confirm_password'],
    message: 'Passwords don’t match.',
  })
export type RegisterValues = z.infer<typeof registerSchema>

export const forgotPasswordSchema = z.object({ email })
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>

export const resetPasswordSchema = z
  .object({ password, confirm_password: z.string() })
  .refine((v) => v.password === v.confirm_password, {
    path: ['confirm_password'],
    message: 'Passwords don’t match.',
  })
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>

export type PasswordStrength = { score: 0 | 1 | 2 | 3 | 4; label: string; hints: string[] }

/**
 * Lightweight client-side strength estimate (length + variety + obvious
 * patterns). The server remains the source of truth for acceptance.
 */
export function passwordStrength(pw: string): PasswordStrength {
  if (!pw) return { score: 0, label: 'Too short', hints: [`Use at least ${PASSWORD_MIN} characters.`] }
  const hints: string[] = []
  let points = 0
  if (pw.length >= PASSWORD_MIN) points++
  else hints.push(`Use at least ${PASSWORD_MIN} characters.`)
  if (pw.length >= 14) points++
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length
  if (classes >= 3) points++
  else hints.push('Mix upper and lower case, numbers, and symbols.')
  if (classes === 4 && pw.length >= 12) points++
  if (/(.)\1{2,}/.test(pw) || /^(?:password|qwerty|123456|letmein)/i.test(pw)) {
    points = Math.max(0, points - 2)
    hints.push('Avoid repeated characters and common words.')
  }
  if (pw.length < PASSWORD_MIN) points = Math.min(points, 1)
  const score = Math.min(4, points) as PasswordStrength['score']
  const label = ['Too short', 'Weak', 'Fair', 'Good', 'Strong'][score]!
  return { score, label, hints }
}
