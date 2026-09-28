import { http } from '../client'
import type { Dashboard } from '../types'

export const dashboardApi = {
  get: () => http.get<Dashboard>('/dashboard'),
}
