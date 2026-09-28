import { http, seg } from '../client'
import type {
  ForgotPasswordRequest,
  ForgotPasswordResponse,
  LoginRequest,
  Me,
  RegisterRequest,
  ResetPasswordRequest,
  Session,
  VerifyEmailRequest,
  VerifyEmailResponse,
} from '../types'

export const authApi = {
  register: (body: RegisterRequest) => http.post<Me>('/auth/register', body),
  login: (body: LoginRequest) => http.post<Me>('/auth/login', body),
  logout: () => http.post<void>('/auth/logout'),
  refresh: () => http.post<Me>('/auth/refresh', undefined, { skipRefresh: true }),
  verifyEmail: (body: VerifyEmailRequest) => http.post<VerifyEmailResponse>('/auth/verify-email', body),
  resendVerification: () => http.post<void>('/auth/resend-verification'),
  forgotPassword: (body: ForgotPasswordRequest) =>
    http.post<ForgotPasswordResponse>('/auth/forgot-password', body),
  resetPassword: (body: ResetPasswordRequest) => http.post<void>('/auth/reset-password', body),
  me: () => http.get<Me>('/auth/me'),
  sessions: () => http.get<Session[]>('/auth/sessions'),
  revokeSession: (sessionId: string) => http.delete<void>(`/auth/sessions/${seg(sessionId)}`),
}
