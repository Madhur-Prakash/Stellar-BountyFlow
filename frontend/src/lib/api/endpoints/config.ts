import { http } from '../client'
import type { PublicConfig } from '../types'

export const configApi = {
  getPublic: () => http.get<PublicConfig>('/config/public'),
}
